"""Tests: stop controller covers all Wave 1 stop conditions."""
from __future__ import annotations

from app.agent.contracts import StopReason
from app.agent.stop_controller import (
    RunState,
    compute_call_hash,
    evaluate_stop,
)


def test_continue_when_nothing_triggered():
    state = RunState(max_steps=6, step_count=2)
    decision = evaluate_stop(state)
    assert not decision.stop


def test_max_steps():
    state = RunState(max_steps=3, step_count=3)
    decision = evaluate_stop(state)
    assert decision.stop
    assert decision.reason is StopReason.MAX_STEPS


def test_guardrail_triggered():
    state = RunState(step_count=1, guardrail_triggered=True)
    decision = evaluate_stop(state)
    assert decision.stop
    assert decision.reason is StopReason.GUARDRAIL_TRIGGERED


def test_invalid_args_after_repair():
    state = RunState(step_count=1, invalid_args_after_repair=True)
    decision = evaluate_stop(state)
    assert decision.stop
    assert decision.reason is StopReason.INVALID_ARGS_AFTER_REPAIR


def test_tool_error_limit():
    state = RunState(step_count=1, tool_error_limit=2, consecutive_tool_errors=2)
    decision = evaluate_stop(state)
    assert decision.stop
    assert decision.reason is StopReason.TOOL_ERROR_LIMIT


def test_tool_error_below_limit_continues():
    state = RunState(step_count=1, tool_error_limit=2, consecutive_tool_errors=1)
    assert not evaluate_stop(state).stop


def test_repeated_tool_call_detection():
    state = RunState(step_count=1)
    args = {"query": "RAG"}
    state.record_tool_call("rag.search", args)
    assert state.is_duplicate_call("rag.search", args)
    assert not state.is_duplicate_call("rag.search", {"query": "different"})


def test_compute_call_hash_stable():
    h1 = compute_call_hash("rag.search", {"query": "x", "top_k": 4})
    h2 = compute_call_hash("rag.search", {"top_k": 4, "query": "x"})
    assert h1 == h2  # order-independent


def test_max_time_placeholder():
    import time

    state = RunState(
        max_steps=100,
        max_time_sec=0.01,
        started_at=time.monotonic() - 1.0,
    )
    decision = evaluate_stop(state)
    assert decision.stop
    assert decision.reason is StopReason.MAX_TIME


def test_max_time_zero_means_disabled():
    import time

    state = RunState(
        max_steps=100,
        max_time_sec=0.0,
        started_at=time.monotonic() - 9999.0,
    )
    assert not evaluate_stop(state).stop


def test_max_tokens_placeholder():
    state = RunState(max_steps=100, max_tokens=100, total_tokens=150)
    decision = evaluate_stop(state)
    assert decision.stop
    assert decision.reason is StopReason.MAX_TOKENS


def test_max_tokens_zero_means_disabled():
    state = RunState(max_steps=100, max_tokens=0, total_tokens=999999)
    assert not evaluate_stop(state).stop


def test_reset_tool_errors():
    state = RunState(tool_error_limit=2)
    state.increment_tool_error()
    state.increment_tool_error()
    assert evaluate_stop(state).stop
    state.reset_tool_errors()
    assert not evaluate_stop(state).stop
