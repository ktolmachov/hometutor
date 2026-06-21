"""Lost-in-the-middle reorder for merged retrieval candidates.

After hybrid merge and cross-encoder rerank, place highest-relevance chunks at
the beginning and end of the LLM context window so they are less likely to be
ignored (Liu et al., "Lost in the Middle").
"""

from __future__ import annotations

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle


def reorder_nodes_lost_in_middle(nodes: list[NodeWithScore]) -> list[NodeWithScore]:
    """Reorder ranked nodes: best at edges, weaker items in the middle."""
    if len(nodes) <= 2:
        return list(nodes)
    reordered: list[NodeWithScore] = []
    left, right = 0, len(nodes) - 1
    while left <= right:
        if left == right:
            reordered.append(nodes[left])
        else:
            reordered.append(nodes[left])
            reordered.append(nodes[right])
        left += 1
        right -= 1
    return reordered


class LostInMiddleReorderPostprocessor(BaseNodePostprocessor):
    """NodePostprocessor: sandwich reorder after rerank / graph merge."""

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:
        return reorder_nodes_lost_in_middle(nodes)


def append_lost_in_middle_reorder_postprocessor(postprocessors: list) -> list:
    """Append reorder as the last postprocessor when enabled in retrieval settings."""
    from app.config import get_retrieval_settings

    if not get_retrieval_settings().enable_lost_in_middle_reorder:
        return postprocessors
    pp = list(postprocessors)
    pp.append(LostInMiddleReorderPostprocessor())
    return pp
