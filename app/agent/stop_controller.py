"""Stop controller for the agent loop (Урок 4: harness owns control).

Every stop produces an explicit :class:`StopReason`. The controller is pure —
it inspects :class:`RunState` and returns a :class:`StopDecision` without side
effects.

Wave 1 stop conditions (docs/agent_roadmap.md §Wave 1):
- ``max_steps`` (from ``settings.agent_max_steps``)
- ``max_time`` / ``max_tokens`` / ``max_cost`` (placeholders — interfaces
  provided; accounting wired in Wave 2)
- ``repeated_tool_call`` (hash of tool_name + args)
- ``tool_error_limit`` (default 2 consecutive tool errors)
- ``invalid_args_after_repair`` (set by runner after a failed repair)
- ``guardrail_triggered`` (set by runner when output guardrail fires)
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

from app.agent.contracts import StopDecision, StopReason


def compute_call_hash(tool_name: str, args: dict) -> str:
    """Stable hash of a tool call for duplicate detection."""
    blob = json.dumps(
        {"tool": tool_name, "args": args},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class RunState:
    """Mutable run-level accounting consumed by the stop controller."""

    max_steps: int = 6
    max_time_sec: float = 0.0
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    tool_error_limit: int = 2
    step_count: int = 0
    tool_call_hashes: list[str] = field(default_factory=list)
    consecutive_tool_errors: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    started_at: float = field(default_factory=time.monotonic)
    guardrail_triggered: bool = False
    invalid_args_after_repair: bool = False

    def record_tool_call(self, tool_name: str, args: dict) -> str:
        call_hash = compute_call_hash(tool_name, args)
        self.tool_call_hashes.append(call_hash)
        return call_hash

    def is_duplicate_call(self, tool_name: str, args: dict) -> bool:
        return compute_call_hash(tool_name, args) in self.tool_call_hashes

    def reset_tool_errors(self) -> None:
        self.consecutive_tool_errors = 0

    def increment_tool_error(self) -> None:
        self.consecutive_tool_errors += 1


def evaluate_stop(state: RunState) -> StopDecision:
    """Pure function: inspect ``state`` and return whether the loop should halt."""
    if state.guardrail_triggered:
        return StopDecision.halt(StopReason.GUARDRAIL_TRIGGERED)

    if state.invalid_args_after_repair:
        return StopDecision.halt(
            StopReason.INVALID_ARGS_AFTER_REPAIR,
            "tool args remained invalid after one repair attempt",
        )

    if state.step_count >= state.max_steps:
        return StopDecision.halt(
            StopReason.MAX_STEPS,
            f"step_count={state.step_count} >= max_steps={state.max_steps}",
        )

    if state.max_time_sec > 0:
        elapsed = time.monotonic() - state.started_at
        if elapsed > state.max_time_sec:
            return StopDecision.halt(
                StopReason.MAX_TIME,
                f"elapsed={elapsed:.1f}s > max={state.max_time_sec}s",
            )

    if state.max_tokens > 0 and state.total_tokens > 0:
        if state.total_tokens >= state.max_tokens:
            return StopDecision.halt(
                StopReason.MAX_TOKENS,
                f"tokens={state.total_tokens} >= max={state.max_tokens}",
            )

    if state.max_cost_usd > 0 and state.total_cost_usd > 0:
        if state.total_cost_usd >= state.max_cost_usd:
            return StopDecision.halt(
                StopReason.MAX_COST,
                f"cost={state.total_cost_usd:.4f} >= max={state.max_cost_usd}",
            )

    if state.consecutive_tool_errors >= state.tool_error_limit:
        return StopDecision.halt(
            StopReason.TOOL_ERROR_LIMIT,
            f"consecutive_tool_errors={state.consecutive_tool_errors} "
            f">= limit={state.tool_error_limit}",
        )

    return StopDecision.continue_run()


def make_run_state_from_settings() -> RunState:
    """Build a :class:`RunState` from ``get_settings()`` agent config."""
    from app.config import get_settings

    s = get_settings()
    return RunState(
        max_steps=s.agent_max_steps,
        max_time_sec=s.agent_max_run_seconds,
        max_tokens=s.agent_max_run_tokens,
        max_cost_usd=s.agent_max_run_cost_usd,
    )


__all__ = [
    "RunState",
    "compute_call_hash",
    "evaluate_stop",
    "make_run_state_from_settings",
]
