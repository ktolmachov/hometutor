from __future__ import annotations

import sys
import types

from app import ssr_semantic_cache


def _reset_model_state(monkeypatch) -> None:
    monkeypatch.setattr(ssr_semantic_cache, "_EMBEDDINGS_MODEL", None)
    monkeypatch.setattr(ssr_semantic_cache, "_MODEL_LOAD_ATTEMPTED", False)


def test_semantic_cache_model_load_is_local_only(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    expected_model = object()

    class FakeSentenceTransformer:
        def __new__(cls, model_name: str, **kwargs):
            calls.append((model_name, kwargs))
            return expected_model

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    _reset_model_state(monkeypatch)

    assert ssr_semantic_cache._load_embeddings_model() is expected_model
    assert calls == [
        (
            "all-MiniLM-L6-v2",
            {"device": "cpu", "local_files_only": True},
        )
    ]


def test_missing_local_model_is_not_retried(monkeypatch) -> None:
    calls = 0

    class MissingSentenceTransformer:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal calls
            calls += 1
            raise OSError("local snapshot missing")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = MissingSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    _reset_model_state(monkeypatch)

    assert ssr_semantic_cache._load_embeddings_model() is None
    assert ssr_semantic_cache._load_embeddings_model() is None
    assert calls == 1
