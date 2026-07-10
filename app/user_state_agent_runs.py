"""Persistence helpers for AI Agent run observability.

Wave 2 keeps this append-only and compact: full tool payloads stay in memory
trace/debug; user-state stores enough metadata to inspect what happened
without recording raw RAG chunks or harness-injected identities.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.agent.contracts import AgentRunResult, AgentStep, ToolResult
from app.user_state_core import _utc_now_iso, _with_db

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "secret",
    "session_id",
    "token",
    "user_id",
)
_MAX_TEXT_CHARS = 500
_MAX_RESULT_TEXT_CHARS = 260
_MAX_ITEMS = 8


def persist_agent_run(
    *,
    run_id: str,
    scenario_id: str,
    question: str,
    answer_status: str,
    result: AgentRunResult,
) -> None:
    """Persist a compact, per-user agent run record."""
    now = _utc_now_iso()
    tool_calls = list(result.trace.get("tool_calls") or [])
    if not tool_calls:
        tool_calls = [step.tool_name for step in result.steps if step.tool_name]

    summary = {
        "answer_preview": _truncate_text(result.answer, _MAX_TEXT_CHARS),
        "source_count": len(result.sources),
        "step_count": len(result.steps),
        "trace": _compact_value(
            {
                "step_count": result.trace.get("step_count"),
                "stop_detail": result.trace.get("stop_detail"),
                "total_tokens": result.trace.get("total_tokens"),
                "total_cost_usd": result.trace.get("total_cost_usd"),
            }
        ),
    }

    def _work(conn):
        conn.execute(
            """
            INSERT INTO agent_runs(
                run_id, scenario_id, question, answer_status, stop_reason,
                state, tool_calls_json, summary_json, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                scenario_id or "generic",
                _truncate_text(question, _MAX_TEXT_CHARS),
                answer_status,
                result.stop_reason.value,
                result.state.value,
                _to_json(tool_calls),
                _to_json(summary),
                now,
                now,
            ),
        )
        for step in result.steps:
            conn.execute(
                """
                INSERT INTO agent_steps(
                    run_id, step_index, state, tool_name, tool_args_json,
                    tool_ok, tool_error, result_summary_json, repair_attempt,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step.step_index,
                    step.state.value,
                    step.tool_name,
                    _to_json(_compact_tool_args(step)),
                    _tool_ok(step.tool_result),
                    _truncate_text(step.tool_result.error, _MAX_RESULT_TEXT_CHARS)
                    if step.tool_result
                    else None,
                    _to_json(_compact_tool_result(step.tool_result)),
                    1 if step.repair_attempt else 0,
                    now,
                ),
            )
        conn.commit()

    _with_db(_work, write=True)


def get_agent_run(run_id: str) -> dict[str, Any] | None:
    """Load one persisted run with ordered compact steps."""

    def _work(conn):
        run = conn.execute(
            """
            SELECT *
            FROM agent_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run is None:
            return None
        step_rows = conn.execute(
            """
            SELECT *
            FROM agent_steps
            WHERE run_id = ?
            ORDER BY step_index ASC
            """,
            (run_id,),
        ).fetchall()
        return _row_to_run(run, step_rows)

    return _with_db(_work)


def list_agent_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    """List recent persisted runs without loading step rows."""
    safe_limit = max(1, min(int(limit), 100))

    def _work(conn):
        rows = conn.execute(
            """
            SELECT *
            FROM agent_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [_row_to_run(row, []) for row in rows]

    return _with_db(_work)


def _row_to_run(run_row, step_rows) -> dict[str, Any]:
    return {
        "run_id": run_row["run_id"],
        "scenario_id": run_row["scenario_id"],
        "question": run_row["question"],
        "answer_status": run_row["answer_status"],
        "stop_reason": run_row["stop_reason"],
        "state": run_row["state"],
        "tool_calls": _from_json(run_row["tool_calls_json"], default=[]),
        "summary": _from_json(run_row["summary_json"], default={}),
        "created_at": run_row["created_at"],
        "completed_at": run_row["completed_at"],
        "steps": [
            {
                "step_index": row["step_index"],
                "state": row["state"],
                "tool_name": row["tool_name"],
                "tool_args": _from_json(row["tool_args_json"], default={}),
                "tool_ok": _coerce_optional_bool(row["tool_ok"]),
                "tool_error": row["tool_error"],
                "result_summary": _from_json(row["result_summary_json"], default=None),
                "repair_attempt": bool(row["repair_attempt"]),
                "created_at": row["created_at"],
            }
            for row in step_rows
        ],
    }


def _compact_tool_args(step: AgentStep) -> Any:
    return _compact_value(step.tool_args or {}, text_limit=_MAX_RESULT_TEXT_CHARS)


def _compact_tool_result(result: ToolResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "ok": result.ok,
        "error": _truncate_text(result.error, _MAX_RESULT_TEXT_CHARS),
        "meta": _compact_value(result.meta, text_limit=_MAX_RESULT_TEXT_CHARS),
        "data": _compact_value(result.data, text_limit=_MAX_RESULT_TEXT_CHARS),
    }


def _compact_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 4,
    max_items: int = _MAX_ITEMS,
    text_limit: int = _MAX_TEXT_CHARS,
) -> Any:
    if depth > max_depth:
        return "<truncated>"
    if isinstance(value, BaseModel):
        return _compact_value(
            value.model_dump(mode="json"),
            depth=depth,
            max_depth=max_depth,
            max_items=max_items,
            text_limit=text_limit,
        )
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= max_items:
                compact["<truncated_items>"] = len(value) - max_items
                break
            key_text = str(key)
            if _is_sensitive_key(key_text):
                continue
            compact[key_text] = _compact_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                text_limit=text_limit,
            )
        return compact
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        compact_list = [
            _compact_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                text_limit=text_limit,
            )
            for item in seq[:max_items]
        ]
        if len(seq) > max_items:
            compact_list.append({"<truncated_items>": len(seq) - max_items})
        return compact_list
    if isinstance(value, str) or value is None:
        return _truncate_text(value, text_limit)
    if isinstance(value, (bool, int, float)):
        return value
    return _truncate_text(str(value), text_limit)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _truncate_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _tool_ok(result: ToolResult | None) -> int | None:
    if result is None:
        return None
    return 1 if result.ok else 0


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(value: str | None, *, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


__all__ = [
    "get_agent_run",
    "list_agent_runs",
    "persist_agent_run",
]
