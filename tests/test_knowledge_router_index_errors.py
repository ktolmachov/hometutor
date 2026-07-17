from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.retrieval_cache import EmbedModelMismatchError
from app.routers import knowledge


def test_topics_returns_503_for_embed_model_mismatch(monkeypatch) -> None:
    def fail():
        raise EmbedModelMismatchError("requires full reindex")

    monkeypatch.setattr(knowledge.services, "get_topics_catalog", fail)

    with pytest.raises(HTTPException) as excinfo:
        knowledge.topics()

    assert excinfo.value.status_code == 503
    assert "requires full reindex" in str(excinfo.value.detail)


def test_kb_overview_returns_503_for_embed_model_mismatch(monkeypatch) -> None:
    def fail():
        raise EmbedModelMismatchError("requires full reindex")

    monkeypatch.setattr(knowledge.services, "get_kb_overview", fail)

    with pytest.raises(HTTPException) as excinfo:
        knowledge.kb_overview()

    assert excinfo.value.status_code == 503
    assert "requires full reindex" in str(excinfo.value.detail)
