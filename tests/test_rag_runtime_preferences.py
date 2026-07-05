import pytest

import app.rag_runtime_preferences as rag_prefs
from app.config import get_retrieval_settings, get_settings, reset_settings_cache
from app.models import PipelineOverrides


@pytest.fixture()
def kv_store(monkeypatch):
    store: dict[str, str] = {}

    def fake_get_kv(key: str, default: str | None = None) -> str | None:
        return store.get(key, default)

    def fake_set_kv(key: str, value: str) -> None:
        store[key] = value

    monkeypatch.setattr(rag_prefs, "_read_raw_kv", fake_get_kv)
    monkeypatch.setattr(rag_prefs, "_write_raw_kv", fake_set_kv)
    monkeypatch.setattr(rag_prefs, "_ensure_auth_context", lambda: None)
    return store


def test_set_and_clear_override(kv_store) -> None:
    base_mode = get_retrieval_settings().retrieval_mode
    alt_mode = "vector_only" if base_mode != "vector_only" else "bm25_only"

    rag_prefs.set_override("retrieval_mode", alt_mode)
    assert rag_prefs.get_overrides()["retrieval_mode"] == alt_mode
    assert rag_prefs.effective_retrieval_settings().retrieval_mode == alt_mode

    rag_prefs.set_override("retrieval_mode", base_mode)
    assert rag_prefs.get_overrides() == {}

    rag_prefs.set_override("similarity_top_k", 12)
    assert rag_prefs.get_overrides()["similarity_top_k"] == 12

    rag_prefs.clear_overrides()
    assert rag_prefs.get_overrides() == {}


def test_effective_settings_merge(kv_store, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_REWRITE", "false")
    reset_settings_cache()
    try:
        rag_prefs.set_override("enable_rewrite", True)
        assert rag_prefs.effective_settings().enable_rewrite is True
    finally:
        rag_prefs.clear_overrides()
        reset_settings_cache()


def test_pipeline_overrides_from_prefs(kv_store) -> None:
    base_profile = get_retrieval_settings().rag_profile
    alt_profile = "fast" if base_profile != "fast" else "graph_aware"

    rag_prefs.set_override("rag_profile", alt_profile)
    rag_prefs.set_override("enable_reranker", False)

    overrides = rag_prefs.pipeline_overrides_from_prefs()
    assert isinstance(overrides, PipelineOverrides)
    assert overrides.rag_profile == alt_profile
    assert overrides.enable_reranker is False


def test_set_override_rejects_invalid_option(kv_store) -> None:
    with pytest.raises(ValueError):
        rag_prefs.set_override("retrieval_mode", "invalid_mode_xyz")


def test_ingestion_model_empty_clears_override(kv_store) -> None:
    rag_prefs.set_override("ingestion_model", "custom-model")
    assert rag_prefs.get_overrides()["ingestion_model"] == "custom-model"

    rag_prefs.set_override("ingestion_model", "")
    assert "ingestion_model" not in rag_prefs.get_overrides()
