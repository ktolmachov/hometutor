from types import SimpleNamespace

from app import faq_memory


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embed_api_base_resolved="http://127.0.0.1:1234/v1",
        faq_embedding_failure_cooldown_sec=60.0,
        faq_embedding_probe_timeout_sec=0.05,
        faq_dedup_min_score=0.92,
        faq_memory_collection_name="test_faq",
    )


def test_find_similar_questions_skips_when_loopback_unreachable(monkeypatch) -> None:
    faq_memory.reset_faq_embed_circuit_for_tests()
    called = {"embed": False}

    monkeypatch.setattr(faq_memory, "get_settings", _settings)
    monkeypatch.setattr(faq_memory, "_loopback_tcp_reachable", lambda *_args, **_kwargs: False)

    def fail_embed_model():
        called["embed"] = True
        raise AssertionError("embedding should be skipped when endpoint probe fails")

    monkeypatch.setattr(faq_memory, "_get_embed_model", fail_embed_model)

    assert faq_memory.find_similar_questions("question") == []
    assert called["embed"] is False


def test_save_interaction_opens_cooldown_after_embed_failure(monkeypatch) -> None:
    faq_memory.reset_faq_embed_circuit_for_tests()
    calls = {"embed_model": 0}

    class FailingEmbedModel:
        def get_text_embedding(self, _text):
            raise RuntimeError("connection error")

    monkeypatch.setattr(faq_memory, "get_settings", _settings)
    monkeypatch.setattr(faq_memory, "_loopback_tcp_reachable", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(faq_memory, "_migrate_jsonl_to_chroma_if_needed", lambda: None)

    def get_failing_embed_model():
        calls["embed_model"] += 1
        return FailingEmbedModel()

    monkeypatch.setattr(faq_memory, "_get_embed_model", get_failing_embed_model)

    faq_memory.save_interaction("question", "answer", [])
    faq_memory.save_interaction("question", "answer", [])

    assert calls["embed_model"] == 1
