from types import SimpleNamespace

from app.config import DEFAULT_EMBED_API_BASE, DEFAULT_EMBED_MODEL, Settings
from app.ingestion_env_diag import _resolve_embed_api_base


def test_embedding_defaults_are_local_first() -> None:
    assert Settings.model_fields["embed_api_base"].default == DEFAULT_EMBED_API_BASE
    assert Settings.model_fields["embed_model"].default == DEFAULT_EMBED_MODEL
    assert Settings().embed_api_base_resolved == DEFAULT_EMBED_API_BASE


def test_rag_context_budget_is_opt_in_by_default() -> None:
    assert Settings().rag_context_token_budget == 0


def test_empty_embed_api_base_does_not_fall_back_to_openai_api_base() -> None:
    settings = Settings(
        embed_api_base="",
        openai_api_base="https://openrouter.ai/api/v1",
    )

    assert settings.embed_api_base_resolved == DEFAULT_EMBED_API_BASE


def test_ingest_diag_embed_base_fallback_is_local_first_for_fake_settings() -> None:
    settings = SimpleNamespace(openai_api_base="https://openrouter.ai/api/v1")

    assert _resolve_embed_api_base(settings) == DEFAULT_EMBED_API_BASE
