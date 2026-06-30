import inspect

from llama_index.core.schema import NodeWithScore, TextNode

from app import retrieval
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
    original_text = nodes[0].node.get_content()
    pp = ContextTokenBudgetPostprocessor(max_context_tokens=40, model="gpt-4o-mini")

    with retrieval_context_budget_trace_scope() as trace:
        kept = pp.postprocess_nodes(nodes)

    assert len(kept) == 1
    assert kept[0] is not nodes[0]
    assert len(kept[0].node.get_content()) < len(original_text)
    assert nodes[0].node.get_content() == original_text
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


def test_context_budget_runs_before_lost_in_middle_reorder_in_build_query_engine() -> None:
    """Regression guard: budget must trim relevance-ranked nodes *before* lost-in-middle
    reorders them, otherwise the budget cuts the tail that reorder just placed there as
    high-relevance (see docs/compliance_upgrade_plan.md audit notes)."""
    source = inspect.getsource(retrieval.build_query_engine)
    budget_pos = source.index("append_context_budget_postprocessor(")
    reorder_pos = source.index("append_lost_in_middle_reorder_postprocessor(")
    assert budget_pos < reorder_pos, (
        "append_context_budget_postprocessor must be called before "
        "append_lost_in_middle_reorder_postprocessor in build_query_engine"
    )
