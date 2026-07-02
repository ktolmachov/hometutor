from app.models import QueryContext, QueryOptions
from app.retrieval import resolve_query_execution_plan
from scripts.home_rag_product_baseline_v1 import _evaluate_product_case


def test_study_quiz_request_uses_qa_prompt_not_keyword_prompt() -> None:
    options = QueryOptions(study_mode=True, relative_path="product/mitochondria_quiz_source.md", rag_profile="quality")
    ctx = QueryContext(
        original_question="Generate one multiple-choice question about ATP from the mitochondria notes.",
        query_options=options,
        query_type="keyword",
        prompt_key="keyword",
        retrieval_strategy="bm25_only",
    )

    plan = resolve_query_execution_plan(ctx.original_question, options, query_context=ctx)

    assert plan.query_type == "qa"
    assert plan.prompt_key == "qa"
    assert plan.retrieval_mode != "bm25_only"


def test_quiz_validity_rejects_refusal_like_answer() -> None:
    case = {
        "id": "quiz_refusal",
        "type": "quiz_generation",
        "category": "quiz_generation",
        "metrics": ["quiz_validity"],
        "must_include_any": [["ATP"], ["energy"], ["вариант"]],
        "must_not_include": [],
        "require_sources": True,
        "require_citation": True,
    }
    result = {
        "answer": "В доступных материалах недостаточно информации для генерации вопроса. Варианты не приведены [1].",
        "sources": [{"relative_path": "product/mitochondria_quiz_source.md", "text": "ATP is usable energy."}],
    }

    row = _evaluate_product_case(case, result)

    assert row["refusal_like"] is True
    assert row["metrics"] == {"quiz_validity": False}
    assert row["status"] == "NEEDS_WORK"
