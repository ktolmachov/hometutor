"""Tests: rag.answer tool cannot recurse into query_mode='agent'.

The recursion guard: ``rag.answer`` calls ``answer_question`` with
``query_mode=None``, which bypasses the agent branch even when
``AGENT_ENABLED=true``.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import patch

from app.agent.contracts import ToolContext
from app.agent.tools_rag import RagAnswerArgs, _format_node, _rag_answer_handler
from app.models import QueryOptions


def test_rag_answer_forces_non_agent_query_mode(monkeypatch):
    """rag.answer must pass query_mode=None to answer_question (no recursion)."""
    captured = {}

    def _fake_answer_question(question, options):
        captured["question"] = question
        captured["query_mode"] = options.query_mode
        return {"answer": "test answer", "sources": [{"file": "x.md"}]}

    monkeypatch.setattr("app.query_service.answer_question", _fake_answer_question)

    agent_opts = QueryOptions(query_mode="agent", session_id="s1")
    ctx = ToolContext(
        user_id="local",
        question="original agent question",
        query_options=agent_opts,
        session_id="s1",
    )
    result = _rag_answer_handler(ctx, RagAnswerArgs(query="sub question"))

    assert result.ok
    assert captured["question"] == "sub question"
    assert captured["query_mode"] is None  # recursion guard!
    assert "test answer" in result.data["answer"]


def test_rag_answer_preserves_other_options(monkeypatch):
    """query_mode is cleared but other options survive."""
    captured = {}

    def _fake_answer_question(question, options):
        captured["folder"] = options.folder
        captured["session_id"] = options.session_id
        captured["query_mode"] = options.query_mode
        return {"answer": "ok", "sources": []}

    monkeypatch.setattr("app.query_service.answer_question", _fake_answer_question)

    agent_opts = QueryOptions(query_mode="agent", folder="my_folder", session_id="s2")
    ctx = ToolContext(
        user_id="local",
        question="q",
        query_options=agent_opts,
        session_id="s2",
    )
    result = _rag_answer_handler(ctx, RagAnswerArgs(query="sub"))
    assert result.ok
    assert captured["query_mode"] is None
    assert captured["folder"] == "my_folder"
    assert captured["session_id"] == "s2"


def test_rag_answer_empty_query_returns_failure():
    ctx = ToolContext(
        user_id="local",
        question="q",
        query_options=QueryOptions(),
    )
    result = _rag_answer_handler(ctx, RagAnswerArgs(query=""))
    assert not result.ok
    assert "required" in (result.error or "")


def test_rag_answer_error_returns_failure(monkeypatch):
    def _boom(question, options):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("app.query_service.answer_question", _boom)

    ctx = ToolContext(
        user_id="local",
        question="q",
        query_options=QueryOptions(query_mode="agent"),
    )
    result = _rag_answer_handler(ctx, RagAnswerArgs(query="sub"))
    assert not result.ok
    assert "failed" in (result.error or "")


def test_format_node_extracts_text_and_metadata_from_node_with_score():
    from llama_index.core.schema import NodeWithScore, TextNode

    node = NodeWithScore(
        node=TextNode(text="grounded chunk", metadata={"file_name": "lesson.md"}),
        score=0.75,
    )

    formatted = _format_node(node, 1)

    assert formatted["text"] == "grounded chunk"
    assert formatted["file"] == "lesson.md"
    assert formatted["score"] == 0.75
    assert formatted["node_id"]
