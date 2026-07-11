"""
Политика жизненного цикла индекса и производных артефактов (итерация 16 tail).

Сводная таблица — в doc/index_lifecycle.md. Здесь — хуки после успешной активации индекса
(eager sync learner lineage в user_state.db).
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.user_state import run_learner_state_lineage_sync


def lifecycle_policy_summary() -> dict[str, Any]:
    """Return a compact summary of index lifecycle policies for diagnostics."""
    return {
        "clear_faq_on_index_activation": "configurable via CLEAR_FAQ_ON_INDEX_ACTIVATION",
        "learner_state_lineage": "eager sync after index activation",
        "note": "See doc/index_lifecycle.md for the full lifecycle policy table.",
    }


def apply_index_activation_hooks(*, reset: bool) -> dict[str, Any]:
    """
    Вызывать после успешной активации новой generation (staging swap или reset).

    retrieval_cache и BM25 cache уже сброшены в clear_retrieval_cache / activate_staging_index.

    Args:
        reset: True если был build_index(reset=True).
    """
    if get_settings().clear_faq_on_index_activation:
        from app.faq_memory import clear_faq_memory_file

        clear_faq_memory_file()

    return {
        "reset": reset,
        "learner_state_lineage": run_learner_state_lineage_sync(),
    }
