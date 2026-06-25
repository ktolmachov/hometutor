from app.models import PipelineOverrides, QueryContext, QueryOptions
from app.pipeline_runner import resolve_retrieval_strategy, run_pipeline


def test_run_pipeline_preserves_context_contract() -> None:
    ctx = run_pipeline("Explain vector search", QueryOptions())

    assert isinstance(ctx, QueryContext)
    assert ctx.original_question == "Explain vector search"
    assert ctx.effective_query == "Explain vector search"
    assert ctx.trace["pre_retrieval_pipeline"] == ["classify", "condense", "rewrite"]
    assert ctx.trace["pre_retrieval_completed"] == ["classify", "condense", "rewrite"]
    assert ctx.trace["condense"] == "skipped_no_session"
    assert ctx.pipeline_steps == ["classify"]
    assert ctx.trace["schema_version"] >= 1


def test_resolve_retrieval_strategy_honors_override_first() -> None:
    ctx = QueryContext(original_question="Find exact keyword")
    ctx.retrieval_strategy = "bm25_only"

    assert (
        resolve_retrieval_strategy(
            ctx,
            PipelineOverrides(retrieval_mode="hybrid"),
        )
        == "hybrid"
    )
