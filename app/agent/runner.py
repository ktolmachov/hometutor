"""AgentRunner FSM: ``running → tool_call / repairing / stopped / completed``.

Wave 1: read-only loop only. No persistence — trace goes into
``AgentRunResult.trace`` (consumed as ``ctx.trace["agent"]``).
The final answer passes through ``apply_output_guardrails`` where appropriate.
No writes to user_state.

Stop conditions are delegated to :mod:`app.agent.stop_controller`.
The decision layer is :mod:`app.agent.decide` (JSON-decision backend).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from pydantic import ValidationError

from app.agent.contracts import (
    AgentRunResult,
    AgentState,
    AgentStep,
    StopReason,
    ToolContext,
    ToolResult,
)
from app.agent.decision import DecisionResult, build_messages, build_repair_messages
from app.agent.stop_controller import RunState, evaluate_stop
from app.agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

DecideFn = Callable[[list[Any]], tuple[DecisionResult, dict[str, int] | None]]

_MAX_HISTORY_RESULT_CHARS = 1500
_FALLBACK_STOP_ANSWER = (
    "Агент достиг лимита шагов и не смог завершить ответ. "
    "Попробуйте уточнить вопрос."
)


def _format_result_for_history(result: ToolResult, limits: dict[str, Any]) -> str:
    """Compact text of a tool result for the decision prompt history."""
    max_chars = int(limits.get("max_result_chars", _MAX_HISTORY_RESULT_CHARS))
    try:
        blob = json.dumps(result.data, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 - data may not be JSON-serializable
        blob = str(result.data)
    if len(blob) > max_chars:
        blob = blob[:max_chars] + "…"
    if result.ok:
        return blob
    return f"ERROR: {result.error}"


class AgentRunner:
    """FSM runner for the read-only agent loop.

    Parameters:
        registry: tool registry (read-only tools).
        run_state: resource/stop accounting (created from settings if omitted).
        decide_fn: override for the decision call (testing). When ``None``,
            uses :func:`app.agent.decision.decide_action` with ``llm``.
        llm: LLM client (required when ``decide_fn`` is ``None``).
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        run_state: RunState | None = None,
        decide_fn: DecideFn | None = None,
        llm: Any = None,
    ) -> None:
        self._registry = registry
        self._state = run_state or RunState()
        self._decide_fn = decide_fn
        self._llm = llm

    @property
    def run_state(self) -> RunState:
        return self._state

    def run(self, *, question: str, tool_ctx: ToolContext) -> AgentRunResult:
        steps: list[AgentStep] = []
        sources: list[dict[str, Any]] = []
        history_parts: list[str] = []
        tools_description = self._registry.describe_tools_for_prompt()
        answer: str | None = None

        while True:
            self._state.step_count += 1

            stop = evaluate_stop(self._state)
            if stop.stop:
                reason = stop.reason or StopReason.MAX_STEPS
                if answer is None:
                    answer = _FALLBACK_STOP_ANSWER
                return self._build_result(
                    answer=answer,
                    sources=sources,
                    steps=steps,
                    reason=reason,
                    detail=stop.detail,
                )

            messages = build_messages(
                question=question,
                tools_description=tools_description,
                history="\n".join(history_parts),
            )

            step = AgentStep(
                step_index=self._state.step_count,
                state=AgentState.RUNNING,
            )
            steps.append(step)

            decision, usage = self._call_decide(messages)
            step.thought = decision.thought
            step.decision_raw = decision.raw
            self._accumulate_usage(usage)

            if decision.action == "final_answer":
                step.state = AgentState.COMPLETED
                answer = decision.final_answer or ""
                answer, guardrail_redacted = self._apply_guardrails(answer, sources)
                if self._state.guardrail_triggered:
                    return self._build_result(
                        answer=answer,
                        sources=sources,
                        steps=steps,
                        reason=StopReason.GUARDRAIL_TRIGGERED,
                        detail="output guardrail rejected final answer",
                        extra_trace={
                            "guardrail_redacted": guardrail_redacted,
                            "fallback_decision": decision.fallback,
                        },
                    )
                return self._build_result(
                    answer=answer,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.COMPLETED,
                    extra_trace={
                        "guardrail_redacted": guardrail_redacted,
                        "fallback_decision": decision.fallback,
                    },
                )

            # action == "tool_call"
            tool_name = decision.tool_name or ""
            step.tool_name = tool_name
            spec = self._registry.get_spec(tool_name)
            if spec is None:
                step.state = AgentState.STOPPED
                step.error = f"unknown tool: {tool_name!r}"
                return self._build_result(
                    answer=answer or _FALLBACK_STOP_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.UNKNOWN_TOOL,
                    detail=(
                        f"tool={tool_name!r}; "
                        f"available={', '.join(self._registry.tool_names)}"
                    ),
                )

            step.tool_args = decision.tool_args
            args_model, validation_error = self._validate_args(
                spec.args_schema, decision.tool_args
            )
            if args_model is None:
                step.tool_args_valid = False
                handled = self._handle_repair(
                    question=question,
                    tools_description=tools_description,
                    history_parts=history_parts,
                    step=step,
                    tool_name=tool_name,
                    validation_error=validation_error,
                )
                if handled is not None:
                    if handled.get("final_answer") is not None:
                        answer = handled["final_answer"]
                        answer, guardrail_redacted = self._apply_guardrails(
                            answer, sources
                        )
                        if self._state.guardrail_triggered:
                            return self._build_result(
                                answer=answer,
                                sources=sources,
                                steps=steps,
                                reason=StopReason.GUARDRAIL_TRIGGERED,
                                detail="output guardrail rejected repaired final answer",
                                extra_trace={
                                    "guardrail_redacted": guardrail_redacted,
                                    "recovered_via_repair": True,
                                },
                            )
                        return self._build_result(
                            answer=answer,
                            sources=sources,
                            steps=steps,
                            reason=StopReason.COMPLETED,
                            extra_trace={
                                "guardrail_redacted": guardrail_redacted,
                                "recovered_via_repair": True,
                            },
                        )
                    decision = handled["decision"]
                    args_model, _ = self._validate_args(
                        spec.args_schema, decision.tool_args
                    )
                    if args_model is None:
                        self._state.invalid_args_after_repair = True
                        step.state = AgentState.STOPPED
                        continue

            step.tool_args_valid = True
            tool_args = args_model.model_dump()

            if self._state.is_duplicate_call(tool_name, tool_args):
                step.state = AgentState.STOPPED
                step.error = "repeated identical tool call"
                return self._build_result(
                    answer=answer or _FALLBACK_STOP_ANSWER,
                    sources=sources,
                    steps=steps,
                    reason=StopReason.REPEATED_TOOL_CALL,
                    detail=f"tool={tool_name} args={tool_args}",
                )

            self._state.record_tool_call(tool_name, tool_args)
            step.state = AgentState.TOOL_CALL
            handler = self._registry.get_handler(tool_name)
            result = self._execute_tool(handler, tool_ctx, args_model)
            step.tool_result = result

            if result.ok:
                self._state.reset_tool_errors()
                result_sources = result.meta.get("sources")
                if isinstance(result_sources, list):
                    sources.extend(result_sources)
            else:
                self._state.increment_tool_error()

            history_parts.append(
                f"Step {self._state.step_count}: called {tool_name}({tool_args}) "
                f"→ {_format_result_for_history(result, spec.limits)}"
            )

        # Unreachable — loop only exits via return.

    def _call_decide(
        self, messages: list[Any]
    ) -> tuple[DecisionResult, dict[str, int] | None]:
        if self._decide_fn is not None:
            return self._decide_fn(messages)
        from app.agent.decision import decide_action

        return decide_action(self._llm, messages)

    def _validate_args(
        self, schema: type, raw_args: Any
    ) -> tuple[Any, str]:
        """Validate raw args against the Pydantic schema.

        Returns ``(model, "")`` on success or ``(None, error_message)``.
        """
        try:
            model = schema.model_validate(raw_args or {})
            return model, ""
        except ValidationError as exc:
            return None, str(exc)[:500]

    def _handle_repair(
        self,
        *,
        question: str,
        tools_description: str,
        history_parts: list[str],
        step: AgentStep,
        tool_name: str,
        validation_error: str,
    ) -> dict[str, Any] | None:
        """One repair attempt. Returns ``None`` if repair is not applicable."""
        step.state = AgentState.REPAIRING
        step.repair_attempt = True
        step.tool_args_valid = False

        repair_messages = build_repair_messages(
            question=question,
            tools_description=tools_description,
            history="\n".join(history_parts),
            tool_name=tool_name,
            error=validation_error[:500],
        )
        repaired_decision, usage = self._call_decide(repair_messages)
        self._accumulate_usage(usage)

        if repaired_decision.action == "final_answer":
            return {"final_answer": repaired_decision.final_answer or ""}
        return {"decision": repaired_decision}

    def _execute_tool(
        self,
        handler: Any,
        tool_ctx: ToolContext,
        args_model: Any,
    ) -> ToolResult:
        try:
            return handler(tool_ctx, args_model)
        except Exception as exc:  # noqa: BLE001 - tool must not crash the loop
            logger.debug("agent.tool_execution_failed: %s", exc)
            return ToolResult.failure(f"tool execution error: {exc}")

    def _apply_guardrails(
        self, answer: str, sources: list[dict[str, Any]]
    ) -> tuple[str, bool]:
        """Apply output guardrails; handle agent-context gracefully.

        PII / suspicious-output violations halt the loop. ``missing_sources``
        does NOT halt — the agent's grounding lives in the tool-call trace, not
        necessarily in formal RAG source dicts. ``empty_answer`` is replaced by
        a safe fallback so the agent never returns an empty string.
        """
        from app.guardrails import (
            SAFE_FALLBACK_MESSAGES,
            OutputGuardrailError,
            apply_output_guardrails,
        )

        try:
            return apply_output_guardrails(answer, sources)
        except OutputGuardrailError as exc:
            code = str(exc.code or "")
            if code in ("missing_sources",):
                return str(answer), False
            if code in ("empty_answer",):
                return SAFE_FALLBACK_MESSAGES.get("empty_answer", str(answer)), False
            self._state.guardrail_triggered = True
            fallback = (
                SAFE_FALLBACK_MESSAGES.get(code)
                or SAFE_FALLBACK_MESSAGES.get("suspicious_output")
                or _FALLBACK_STOP_ANSWER
            )
            return fallback, False

    def _accumulate_usage(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        self._state.total_tokens += int(usage.get("total_tokens") or 0)

    def _build_result(
        self,
        *,
        answer: str,
        sources: list[dict[str, Any]],
        steps: list[AgentStep],
        reason: StopReason,
        detail: str = "",
        extra_trace: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        trace: dict[str, Any] = {
            "stop_reason": reason.value,
            "stop_detail": detail,
            "step_count": self._state.step_count,
            "tool_calls": [
                s.tool_name for s in steps if s.tool_name
            ],
            "tool_errors": self._state.consecutive_tool_errors,
            "total_tokens": self._state.total_tokens,
            "max_steps": self._state.max_steps,
        }
        if extra_trace:
            trace.update(extra_trace)
        return AgentRunResult(
            answer=answer,
            sources=sources,
            steps=steps,
            stop_reason=reason,
            state=AgentState.COMPLETED if reason.is_success else AgentState.STOPPED,
            trace=trace,
        )


__all__ = [
    "AgentRunner",
    "DecideFn",
]
