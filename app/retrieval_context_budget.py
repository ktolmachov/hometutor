"""Token budget guard for retrieved RAG context before LLM synthesis."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

from llama_index.core.bridge.pydantic import Field
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle

from app.token_utils import estimate_tokens

_TRACE_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "retrieval_context_budget_trace",
    default=None,
)


@contextmanager
def retrieval_context_budget_trace_scope() -> Iterator[dict[str, Any]]:
    """Collect per-query context-budget diagnostics without storing request state in cached engines."""
    trace: dict[str, Any] = {}
    token = _TRACE_CONTEXT.set(trace)
    try:
        yield trace
    finally:
        _TRACE_CONTEXT.reset(token)


def _node_text(node: NodeWithScore) -> str:
    inner = getattr(node, "node", None)
    if inner is None:
        return ""
    try:
        return str(inner.get_content(metadata_mode=MetadataMode.NONE) or "")
    except Exception:  # noqa: BLE001 - node implementations vary across LlamaIndex stores.
        return str(getattr(inner, "text", "") or "")


def _set_node_text(node: NodeWithScore, text: str) -> None:
    inner = getattr(node, "node", None)
    if inner is not None and getattr(inner, "set_content", None):
        inner.set_content(text)


def _trim_to_token_budget(text: str, *, budget: int, model: str) -> str:
    if budget <= 0 or not text:
        return ""
    if estimate_tokens(text, model=model) <= budget:
        return text

    lo = 0
    hi = len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip()
        if estimate_tokens(candidate, model=model) <= budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best.rstrip()


class ContextTokenBudgetPostprocessor(BaseNodePostprocessor):
    """Keep retrieved context under a token budget before response synthesis."""

    max_context_tokens: int = Field(description="Maximum tokens allowed for retrieved node text.")
    model: str = Field(default="gpt-4o-mini", description="Tokenizer model for estimates.")

    def __init__(self, max_context_tokens: int, model: str = "gpt-4o-mini") -> None:
        super().__init__(
            max_context_tokens=max(0, int(max_context_tokens or 0)),
            model=(model or "gpt-4o-mini"),
        )

    @classmethod
    def class_name(cls) -> str:
        return "ContextTokenBudgetPostprocessor"

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:
        if self.max_context_tokens <= 0 or not nodes:
            return nodes

        kept: list[NodeWithScore] = []
        used_tokens = 0
        original_tokens = 0
        truncated_nodes = 0

        for node in nodes:
            text = _node_text(node)
            node_tokens = estimate_tokens(text, model=self.model)
            original_tokens += node_tokens
            if node_tokens <= 0:
                kept.append(node)
                continue

            remaining = self.max_context_tokens - used_tokens
            if remaining <= 0:
                continue

            if node_tokens <= remaining:
                kept.append(node)
                used_tokens += node_tokens
                continue

            trimmed = _trim_to_token_budget(text, budget=remaining, model=self.model)
            if trimmed:
                _set_node_text(node, trimmed)
                kept.append(node)
                used_tokens += estimate_tokens(trimmed, model=self.model)
                truncated_nodes += 1

        trace = _TRACE_CONTEXT.get()
        if trace is not None:
            trace.update(
                {
                    "applied": len(kept) != len(nodes) or truncated_nodes > 0,
                    "budget_tokens": self.max_context_tokens,
                    "original_nodes": len(nodes),
                    "kept_nodes": len(kept),
                    "dropped_nodes": max(0, len(nodes) - len(kept)),
                    "truncated_nodes": truncated_nodes,
                    "original_context_tokens_estimate": original_tokens,
                    "kept_context_tokens_estimate": used_tokens,
                }
            )

        return kept


def append_context_budget_postprocessor(postprocessors: list) -> list:
    """Append the context budget guard as the final source-node postprocessor."""
    from app.config import get_settings

    settings = get_settings()
    budget = int(getattr(settings, "rag_context_token_budget", 0) or 0)
    if budget <= 0:
        return postprocessors
    pp = list(postprocessors)
    pp.append(
        ContextTokenBudgetPostprocessor(
            max_context_tokens=budget,
            model=getattr(settings, "llm_model", None) or "gpt-4o-mini",
        )
    )
    return pp


__all__ = [
    "ContextTokenBudgetPostprocessor",
    "append_context_budget_postprocessor",
    "retrieval_context_budget_trace_scope",
]
