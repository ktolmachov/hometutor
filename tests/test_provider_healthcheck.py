from types import SimpleNamespace

from app import provider


def _settings(*, profile: str) -> SimpleNamespace:
    return SimpleNamespace(
        home_rag_local_profile=profile,
        openai_api_key="test-key",
        openai_api_base="https://openrouter.ai/api/v1",
        lmstudio_api_base="http://127.0.0.1:8080/v1",
        llm_api_base="http://127.0.0.1:8080/v1",
        llm_model="meta-llama/llama-3.2-3b-instruct:free",
    )


def test_healthcheck_llm_uses_cloud_base_for_cloud_fast(monkeypatch) -> None:
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            kwargs["http_client"].close()

    monkeypatch.setattr(provider, "get_settings", lambda: _settings(profile="cloud_fast"))
    monkeypatch.setattr(provider, "OpenAI", FakeOpenAI)

    provider.get_healthcheck_llm(timeout_sec=1.0)

    assert captured["api_base"] == "https://openrouter.ai/api/v1"
    assert captured["model"] == "meta-llama/llama-3.2-3b-instruct:free"
    assert captured["timeout"] == 1.0


def test_healthcheck_llm_keeps_local_base_for_balanced(monkeypatch) -> None:
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            kwargs["http_client"].close()

    monkeypatch.setattr(provider, "get_settings", lambda: _settings(profile="balanced"))
    monkeypatch.setattr(provider, "OpenAI", FakeOpenAI)

    provider.get_healthcheck_llm(timeout_sec=1.0)

    assert captured["api_base"] == "http://127.0.0.1:8080/v1"


def test_ssr_shares_cloud_primary_base_for_cloud_fast() -> None:
    settings = _settings(profile="cloud_fast")
    settings.ssr_llm_api_base = "https://openrouter.ai/api/v1"

    assert provider.ssr_llm_shares_main_api_base(settings) is True
