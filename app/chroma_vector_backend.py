"""
Minimal vector index storage backend (Chroma PersistentClient).

Single implementation today; interface isolates collection lifecycle for tests and future backends.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import chromadb
from chromadb.errors import NotFoundError

from app.config import CHROMA_DIR

logger = logging.getLogger(__name__)


class ChromaVectorBackend:
    """Thin wrapper around chromadb.PersistentClient for index build and stats."""

    def __init__(self, persist_directory: Path | None = None) -> None:
        self.persist_directory = persist_directory or CHROMA_DIR

    def get_client(self) -> chromadb.PersistentClient:
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(self.persist_directory))

    def delete_collection(self, client: chromadb.PersistentClient, name: str) -> None:
        try:
            client.delete_collection(name)
        except NotFoundError:
            logger.debug("Chroma collection delete skipped | name=%s | reason=not_found", name)
        except Exception as exc:  # noqa: BLE001 - Chroma delete failures are non-fatal during reset/reindex.
            logger.warning("Chroma collection delete failed | name=%s | error=%s", name, exc)

    def get_or_create_collection(
        self,
        client: chromadb.PersistentClient,
        name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        if metadata is not None:
            return client.get_or_create_collection(name=name, metadata=dict(metadata))
        return client.get_or_create_collection(name=name)

    def get_collection(self, client: chromadb.PersistentClient, name: str) -> Any:
        return client.get_collection(name)

    def list_collections(self, client: chromadb.PersistentClient) -> list[str]:
        cols = client.list_collections()
        return [getattr(c, "name", str(c)) for c in cols]


def get_default_chroma_backend(persist_directory: Path | None = None) -> ChromaVectorBackend:
    """If persist_directory is omitted, uses ``BASE_DIR / chroma_db`` (same as ingestion)."""
    return ChromaVectorBackend(persist_directory)
