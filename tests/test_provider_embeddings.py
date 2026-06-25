import asyncio
from types import SimpleNamespace

from app import provider


def _settings(embed_api_base: str) -> SimpleNamespace:
    return SimpleNamespace(
        embed_api_base_resolved=embed_api_base,
        embed_model="text-embedding-qwen3-embedding-0.6b",
        embed_dimensions=1024,
        openai_api_key="test-key",
        embed_batch_size=32,
        embed_num_workers=4,
        embed_request_timeout=60,
        embed_connect_timeout_sec=10.0,
        embed_max_retries=2,
    )


def test_embed_api_base_adds_v1_for_bare_loopback() -> None:
    assert provider._embed_api_base(_settings("http://127.0.0.1:1234")) == "http://127.0.0.1:1234/v1"


def test_make_embed_model_passes_normalized_api_base(monkeypatch) -> None:
    captured = {}

    class FakeOpenAIEmbedding:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            async_client = kwargs.get("async_http_client")
            if async_client is not None:
                asyncio.run(async_client.aclose())

    monkeypatch.setattr(provider, "OpenAIEmbedding", FakeOpenAIEmbedding)

    provider._make_embed_model(_settings("http://127.0.0.1:1234"))

    assert captured["api_base"] == "http://127.0.0.1:1234/v1"
