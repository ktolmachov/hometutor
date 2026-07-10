"""Agent package facade.

``run_agent_flow`` is the entry point called from
``app.query_service.answer_question`` when ``query_mode == "agent"`` and
``settings.agent_enabled`` is true.

Wave 1: read-only single-agent MVP behind ``AGENT_ENABLED``.
JSON-decision is the only implemented backend; ``native``/``auto`` fall back
to json with a warning (explicit unsupported/future path).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.agent.contracts import AgentRunResult, ToolContext
from app.agent.runner import AgentRunner
from app.agent.stop_controller import make_run_state_from_settings
from app.agent.tool_registry import ToolRegistry, build_default_registry
from app.config import get_settings

logger = logging.getLogger(__name__)

_NATIVE_NOT_SUPPORTED_MSG = (
    "agent_tool_call_mode=%s is not supported in Wave 1; "
    "falling back to json-decision. Native tools support is Wave 3."
)


def run_agent_flow(
    question: str,
    options: Any,
    ctx: Any,
    *,
    registry: ToolRegistry | None = None,
    runner: AgentRunner | None = None,
    started_at: float | None = None,
) -> dict[str, Any]:
    """Run the read-only agent loop and return a query-service-compatible dict.

    Called from ``answer_question`` inside the latency-budget wrapper. The
    result dict shape mirrors what ``_answer_question_main_flow`` returns so
    downstream consumers (history, session tape, debug) work unchanged.

    Parameters ``registry`` and ``runner`` are injection seams for tests.
    """
    from app.models import QueryOptions
    from app.auth_context import get_current_user_id

    started = started_at if started_at is not None else time.perf_counter()

    mode = str(getattr(get_settings(), "agent_tool_call_mode", "json") or "json").strip().lower()
    if mode in ("native", "auto"):
        logger.warning(_NATIVE_NOT_SUPPORTED_MSG, mode)

    active_registry = registry or build_default_registry()
    from app.agent.scenarios import get_agent_scenario

    scenario = get_agent_scenario(question)
    user_id = (get_current_user_id() or "").strip() or "local"
    tool_ctx = ToolContext(
        user_id=user_id,
        question=question,
        query_options=options if isinstance(options, QueryOptions) else QueryOptions(),
        session_id=getattr(options, "session_id", None),
    )

    if runner is None:
        runner = AgentRunner(
            active_registry,
            run_state=make_run_state_from_settings(),
            llm=_resolve_llm(),
            system_prompt=scenario.system_prompt if scenario else None,
            finalize_answer=scenario.finalize_answer if scenario else None,
        )

    result: AgentRunResult = runner.run(question=question, tool_ctx=tool_ctx)
    answer_status = _answer_status_for_agent_result(result)

    if ctx is not None:
        try:
            ctx.trace["agent"] = dict(result.trace)
            if scenario:
                ctx.trace["agent"]["scenario_id"] = scenario.scenario_id
            ctx.trace["agent"]["steps"] = [
                {
                    "step_index": s.step_index,
                    "state": s.state.value,
                    "tool": s.tool_name,
                    "ok": s.tool_result.ok if s.tool_result else None,
                    "error": s.error,
                    "repair": s.repair_attempt,
                }
                for s in result.steps
            ]
        except Exception:  # noqa: BLE001 - trace is best-effort
            pass

    total_ms = (time.perf_counter() - started) * 1000
    return {
        "answer": result.answer,
        "sources": result.sources,
        "debug": {
            "cache_hit": False,
            "total_answer_ms": round(total_ms, 3),
            "agent_trace": {
                **dict(result.trace),
                **({"scenario_id": scenario.scenario_id} if scenario else {}),
            },
            "answer_path": {
                "mode": "agent",
                **({"scenario_id": scenario.scenario_id} if scenario else {}),
            },
        },
        "answer_status": answer_status,
    }


def _answer_status_for_agent_result(result: AgentRunResult) -> str:
    """Map agent stop reasons to the public ``AskResponse.answer_status`` enum."""
    from app.agent.contracts import StopReason

    if result.stop_reason is StopReason.GUARDRAIL_TRIGGERED:
        return "guardrails_fallback"
    if result.is_success:
        return "grounded"
    return "abstain"


def _resolve_llm() -> Any:
    """Resolve the LLM for the agent decision layer (provider-layer only).

    Uses ``get_llm()`` — the same primary chat LLM with CB-aware fallback.
    A dedicated ``get_agent_planner_llm()`` is Wave 3.
    """
    from app.provider import get_llm

    return get_llm()


__all__ = [
    "run_agent_flow",
]
