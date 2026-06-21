"""Offline conversion of Langfuse JSON exports into home-rag eval datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from app.guardrails import redact_sensitive_text


def load_trace_export(path: Path) -> list[dict[str, Any]]:
    """Load a Langfuse-style JSON array/envelope or JSONL export."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    payload = json.loads(text)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "traces"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [payload]
    raise ValueError("trace export must be a JSON object, array, or JSONL rows")


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _text_field(value: Any, *keys: str) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if not isinstance(value, dict):
        return None
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _trace_failed(trace: dict[str, Any]) -> bool:
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    level = str(trace.get("level") or trace.get("status") or "").strip().lower()
    return bool(
        trace.get("failed") is True
        or trace.get("success") is False
        or metadata.get("failed") is True
        or level in {"error", "failed", "failure"}
    )


def _expected_sources(trace: dict[str, Any]) -> list[str]:
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    raw = trace.get("expected_sources") or metadata.get("expected_sources") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return sorted({str(item).strip() for item in raw if str(item).strip()})


def _case_id(question: str, reference: str | None, sources: list[str]) -> str:
    canonical = json.dumps(
        {"question": question, "reference": reference, "sources": sources},
        ensure_ascii=False,
        sort_keys=True,
    )
    return "lf-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def trace_to_eval_case(
    trace: dict[str, Any],
    *,
    failed_only: bool = True,
) -> dict[str, Any] | None:
    """Convert one exported trace; return None for incomplete/non-failing rows."""
    clean = _redact_value(trace)
    if failed_only and not _trace_failed(clean):
        return None

    metadata = clean.get("metadata") if isinstance(clean.get("metadata"), dict) else {}
    question = (
        _text_field(clean.get("input"), "question", "query", "prompt")
        or _text_field(metadata, "question", "query", "prompt")
    )
    if not question:
        return None

    reference = (
        _text_field(clean.get("expectedOutput"), "answer", "reference")
        or _text_field(clean.get("expected_output"), "answer", "reference")
        or _text_field(metadata, "reference", "reference_answer", "expected_answer")
    )
    sources = _expected_sources(clean)
    category = str(metadata.get("category") or clean.get("category") or "qa").strip() or "qa"
    trace_id = str(clean.get("id") or clean.get("traceId") or "").strip() or None

    case: dict[str, Any] = {
        "id": _case_id(question, reference, sources),
        "question": question,
        "expected_sources": sources,
        "category": category,
        "source": "langfuse_export",
    }
    if reference:
        case["reference_answer"] = reference
    if trace_id:
        case["source_trace_id"] = trace_id
    return case


def build_eval_dataset(
    traces: Iterable[dict[str, Any]],
    *,
    failed_only: bool = True,
) -> list[dict[str, Any]]:
    """Convert and deterministically deduplicate trace rows."""
    by_id: dict[str, dict[str, Any]] = {}
    for trace in traces:
        case = trace_to_eval_case(trace, failed_only=failed_only)
        if case is not None:
            by_id.setdefault(case["id"], case)
    return [by_id[key] for key in sorted(by_id)]


def write_eval_dataset(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
