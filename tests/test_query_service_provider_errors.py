import time

from app.models import QueryOptions
from app.query_service import _handle_answer_question_exception


class FakeProviderRateLimitError(Exception):
    pass


def test_answer_question_rate_limit_returns_user_friendly_fallback():
    error = FakeProviderRateLimitError(
        "Error code: 429 - {'error': {'message': 'Provider returned error', "
        "'code': 429, 'metadata': {'raw': 'model is temporarily rate-limited upstream', "
        "'retry_after_seconds': 30}}}"
    )

    result = _handle_answer_question_exception(
        error,
        started_at=time.perf_counter(),
        question="Что дальше?",
        options=QueryOptions(),
        include_timed_out=False,
    )

    assert result["answer_status"] == "provider_rate_limited"
    assert "30 секунд" in result["answer"]
    assert "LLM_MODEL" in result["answer"]
    assert result["sources"] == []
    assert result["debug"]["provider_status_code"] == 429
    assert result["debug"]["retry_after_seconds"] == 30
