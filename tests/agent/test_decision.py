"""Tests: decision layer normalization and native unsupported path."""
from __future__ import annotations

import pytest

from app.agent.decision import DecisionResult, decide_native, normalize_decision
from app.prompts._impl import AGENT_SYSTEM_PROMPT


def test_normalize_tool_call():
    raw = {"action": "tool_call", "tool": "rag.search", "args": {"query": "RAG"}, "thought": "search"}
    d = normalize_decision(raw)
    assert d.action == "tool_call"
    assert d.tool_name == "rag.search"
    assert d.tool_args == {"query": "RAG"}
    assert not d.fallback


def test_normalize_final_answer():
    raw = {"action": "final_answer", "answer": "RAG is ...", "thought": "done"}
    d = normalize_decision(raw)
    assert d.action == "final_answer"
    assert d.final_answer == "RAG is ..."
    assert not d.fallback


def test_normalize_invalid_action_falls_back():
    raw = {"action": "fly_to_moon", "answer": "huh"}
    d = normalize_decision(raw)
    assert d.action == "final_answer"
    assert d.fallback


def test_normalize_empty_answer_falls_back():
    raw = {"action": "final_answer", "answer": ""}
    d = normalize_decision(raw)
    assert d.action == "final_answer"
    assert d.fallback
    assert d.final_answer  # non-empty safe message


def test_normalize_tool_call_missing_tool_name():
    raw = {"action": "tool_call", "args": {}}
    d = normalize_decision(raw)
    assert d.action == "tool_call"
    assert d.tool_name is None


def test_normalize_tool_call_non_dict_args():
    raw = {"action": "tool_call", "tool": "rag.search", "args": "not a dict"}
    d = normalize_decision(raw)
    assert d.tool_args == {}


def test_normalize_none_input():
    d = normalize_decision(None)
    assert d.action == "final_answer"
    assert d.fallback


def test_decide_native_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="Wave 1"):
        decide_native(llm=None, messages=[], openai_tools=[])


def test_build_messages_has_system_and_user():
    from app.agent.decision import build_messages
    from app.prompts._impl import PROMPTS

    msgs = build_messages(
        question="What is RAG?",
        tools_description="- rag.search: search",
        history="(none)",
    )
    assert len(msgs) == 2
    assert msgs[0].content == AGENT_SYSTEM_PROMPT
    assert PROMPTS["agent_system"] == AGENT_SYSTEM_PROMPT
    assert "What is RAG?" in msgs[1].content


def test_build_repair_messages_appends_instruction():
    from app.agent.decision import build_repair_messages

    msgs = build_repair_messages(
        question="q",
        tools_description="tools",
        history="history",
        tool_name="rag.search",
        error="field required",
    )
    assert len(msgs) == 3  # system + user + repair instruction
    assert "rag.search" in msgs[2].content
    assert "field required" in msgs[2].content
