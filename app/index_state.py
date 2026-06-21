from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings
from app import index_registry
from app.logging_config import setup_logging

logger = setup_logging()

# Kept for env compatibility; migration reads this path once into index_registry.json
ACTIVE_INDEX_STATE_PATH = Path(
    get_settings().active_index_state_path
)


def load_active_index_state() -> dict[str, Any]:
    """Active generation as flat dict (compat with pre-registry callers)."""
    return index_registry.to_active_index_state_dict()


def save_active_index_state(
    *,
    collection_name: str,
    summary_collection_name: str,
    version_marker: str | None = None,
    activated_at: str | None = None,
) -> dict[str, Any]:
    """
    Promote staging collections to active (registry bump + atomic write).
    version_marker / activated_at are ignored for storage; registry sets activated_at;
    version_marker in returned dict comes from to_active_index_state_dict().
    """
    _ = version_marker
    _ = activated_at
    index_registry.activate_staging_generation(
        chunks_collection=collection_name,
        summaries_collection=summary_collection_name,
    )
    return load_active_index_state()


def get_active_collection_names() -> tuple[str, str]:
    return index_registry.get_active_collection_names()
