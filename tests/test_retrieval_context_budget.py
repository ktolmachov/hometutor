from llama_index.core.schema import NodeWithScore, TextNode

from app.retrieval_context_budget import (
    ContextTokenBudgetPostprocessor,
    retrieval_context_budget_trace_scope,
)


def _node(text: str) -> NodeWithScore:
    return NodeWithScore(node=TextNode(text=text), score=1.0)


def test_context_budget_keeps_nodes_under_budget() -> None:
    nodes = [_node("alpha " * 100), _node("beta " * 100), _node("gamma " * 100)]
    pp = ContextTokenBudgetPostprocessor(max_context_tokens=60, model="gpt-4o-mini")

    with retrieval_context_budget_trace_scope() as trace:
        kept = pp.postprocess_nodes(nodes)

    assert kept
    assert len(kept) < len(nodes) or trace["truncated_nodes"] > 0
    assert trace["kept_context_tokens_estimate"] <= 60
    assert trace["budget_tokens"] == 60


def test_context_budget_can_truncate_single_large_node() -> None:
    nodes = [_node("retrieval context " * 500)]
    pp = ContextTokenBudgetPostprocessor(max_context_tokens=40, model="gpt-4o-mini")

    with retrieval_context_budget_trace_scope() as trace:
        kept = pp.postprocess_nodes(nodes)

    assert len(kept) == 1
    assert len(kept[0].node.get_content()) < len("retrieval context " * 500)
    assert trace["truncated_nodes"] == 1
    assert trace["kept_context_tokens_estimate"] <= 40


def test_context_budget_counts_llm_metadata() -> None:
    node = _node("short body")
    node.node.metadata["window"] = "metadata context " * 300
    pp = ContextTokenBudgetPostprocessor(max_context_tokens=80, model="gpt-4o-mini")

    with retrieval_context_budget_trace_scope() as trace:
        kept = pp.postprocess_nodes([node])

    assert len(kept) <= 1
    assert trace["original_context_tokens_estimate"] > 80
    assert trace["kept_context_tokens_estimate"] <= 80
