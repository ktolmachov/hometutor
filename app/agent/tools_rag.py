"""RAG tools: ``rag.search`` (retrieval-only) and ``rag.answer`` (non-agent pipeline).

Both are read-only. ``rag.answer`` MUST call the non-agent path
(``query_mode=None``) to avoid recursion: agent → tool → agent
(docs/agent_roadmap.md §2.1).
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from app.agent.contracts import ToolArgModel, ToolContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

_MAX_SEARCH_CHUNKS = 6
_MAX_CHUNK_CHARS = 1200
_MAX_ANSWER_CHARS = 4000


class RagSearchArgs(ToolArgModel):
    query: str
    top_k: int = 4


class RagAnswerArgs(ToolArgModel):
    query: str


def _format_node(node: Any, index: int) -> dict[str, Any]:
    """Compact dict from a llama-index NodeWithScore for the agent context."""
    text = ""
    try:
        text = str(node.get_content() or node.text or "")
    except Exception:  # noqa: BLE001 - node shape varies across llama-index versions
        text = ""
    if len(text) > _MAX_CHUNK_CHARS:
        text = text[:_MAX_CHUNK_CHARS] + "…"
    meta = {}
    try:
        meta = dict(getattr(node, "metadata", {}) or {})
    except Exception:  # noqa: BLE001
        meta = {}
    score = None
    try:
        score = float(getattr(node, "score", None) or 0.0)
    except (TypeError, ValueError):  # noqa: BLE001
        score = None
    node_id = ""
    try:
        node_id = str(getattr(getattr(node, "node", None), "node_id", "") or "")
    except Exception:  # noqa: BLE001
        node_id = ""
    return {
        "index": index,
        "text": text,
        "score": score,
        "file": meta.get("file_name") or meta.get("file") or "",
        "node_id": node_id,
    }


def _rag_search_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    """Retrieval-only: return ranked source chunks without LLM generation."""
    assert isinstance(args, RagSearchArgs)
    query = (args.query or "").strip()
    if not query:
        return ToolResult.failure("query is required")
    try:
        from llama_index.core import QueryBundle

        from app.retrieval_cache import get_base_services

        services = get_base_services()
        index = services.get("index")
        if index is None:
            return ToolResult.failure("knowledge index is not available")
        top_k = max(1, min(int(args.top_k or 4), _MAX_SEARCH_CHUNKS))
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(QueryBundle(query))
        chunks = [_format_node(n, i + 1) for i, n in enumerate(nodes)]
        return ToolResult.success(
            data={"query": query, "chunks": chunks},
            sources=chunks,
            chunk_count=len(chunks),
        )
    except Exception as exc:  # noqa: BLE001 - tool errors must not crash the loop
        logger.debug("agent.rag_search_failed: %s", exc)
        return ToolResult.failure(f"rag.search failed: {exc}")


def _rag_answer_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    """Full RAG answer via the non-agent pipeline (recursion guard: query_mode=None)."""
    assert isinstance(args, RagAnswerArgs)
    sub_question = (args.query or "").strip()
    if not sub_question:
        return ToolResult.failure("query is required")
    try:
        from app.query_service import answer_question

        non_agent_opts = dataclasses.replace(ctx.query_options, query_mode=None)
        result = answer_question(sub_question, non_agent_opts)
        answer_text = str(result.get("answer") or "")
        if len(answer_text) > _MAX_ANSWER_CHARS:
            answer_text = answer_text[:_MAX_ANSWER_CHARS] + "…"
        sources = result.get("sources") or []
        if not isinstance(sources, list):
            sources = []
        return ToolResult.success(
            data={"answer": answer_text, "sources": sources},
            sources=sources,
        )
    except Exception as exc:  # noqa: BLE001 - tool errors must not crash the loop
        logger.debug("agent.rag_answer_failed: %s", exc)
        return ToolResult.failure(f"rag.answer failed: {exc}")


RAG_SEARCH_SPEC = ToolSpec(
    name="rag.search",
    description="Semantic search over the indexed knowledge base. Returns ranked source chunks (text excerpts) without generating an answer.",
    when_to_use="Use when you need to find relevant source material, facts, or excerpts to ground your answer. Prefer this before answering factual questions.",
    args_schema=RagSearchArgs,
    limits={"max_result_chars": _MAX_CHUNK_CHARS * _MAX_SEARCH_CHUNKS},
)

RAG_ANSWER_SPEC = ToolSpec(
    name="rag.answer",
    description="Run a full RAG answer for a sub-question through the standard pipeline (retrieval + synthesis). Returns a grounded answer with sources.",
    when_to_use="Use when a sub-question needs a complete synthesized answer grounded in the knowledge base, rather than just raw search chunks.",
    args_schema=RagAnswerArgs,
    limits={"max_result_chars": _MAX_ANSWER_CHARS},
)


def get_rag_tool_specs() -> list[tuple[ToolSpec, Any]]:
    """Return (spec, handler) pairs for RAG tools."""
    return [
        (RAG_SEARCH_SPEC, _rag_search_handler),
        (RAG_ANSWER_SPEC, _rag_answer_handler),
    ]


__all__ = [
    "RAG_ANSWER_SPEC",
    "RAG_SEARCH_SPEC",
    "RagAnswerArgs",
    "RagSearchArgs",
    "get_rag_tool_specs",
]
