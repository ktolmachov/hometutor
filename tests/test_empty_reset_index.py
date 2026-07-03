from types import SimpleNamespace

from app import ingestion_loader


class _FakeBackend:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.created: list[str] = []

    def get_client(self):
        return object()

    def delete_collection(self, _client, name: str) -> None:
        self.deleted.append(name)

    def get_or_create_collection(self, _client, name: str):
        self.created.append(name)
        return object()


def test_build_index_reset_true_empty_data_activates_empty_generation(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    chroma_dir = tmp_path / "chroma"
    data_dir.mkdir()
    backend = _FakeBackend()
    activated = {}

    settings = SimpleNamespace(
        openai_api_key=None,
        home_rag_e2e_offline=False,
        collection_name="chunks",
        summary_collection_name="summaries",
        embed_model="embed",
    )
    retrieval = SimpleNamespace(
        split_strategy="sentence_splitter",
        chunk_size=700,
        chunk_overlap=50,
        window_size=2,
    )

    monkeypatch.setattr(ingestion_loader, "get_settings", lambda: settings)
    monkeypatch.setattr(ingestion_loader, "get_retrieval_settings", lambda: retrieval)
    monkeypatch.setattr(ingestion_loader.ing, "DATA_DIR", data_dir)
    monkeypatch.setattr(ingestion_loader.ing, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(ingestion_loader, "get_default_chroma_backend", lambda _path: backend)
    monkeypatch.setattr(ingestion_loader, "clear_retrieval_cache", lambda: None)
    monkeypatch.setattr(ingestion_loader, "apply_index_activation_hooks", lambda *, reset: {"reset": reset})
    monkeypatch.setattr(ingestion_loader, "update_snapshot_after_index", lambda: None)
    monkeypatch.setattr(ingestion_loader, "save_content_hash_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(ingestion_loader, "activate_reset_generation", lambda **kwargs: activated.update(kwargs))

    ingestion_loader.build_index(reset=True)

    assert backend.deleted == ["chunks", "summaries"]
    assert backend.created == ["chunks", "summaries"]
    assert activated["documents_count"] == 0
    assert activated["nodes_count"] == 0
    assert ingestion_loader.ing._ingestion_status["status"] == "completed"
    assert ingestion_loader.ing._ingestion_status["ingest_run_summary"]["human_ru"] == "Индекс очищен: материалов нет"
