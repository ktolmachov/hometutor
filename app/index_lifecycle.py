"""
Политика жизненного цикла индекса и производных артефактов (итерация 16 tail).

Сводная таблица — в doc/index_lifecycle.md. Здесь — хуки после успешной активации индекса
(eager sync learner lineage в user_state.db).
"""

from __future__ import annotations

from typing import Any

from app.user_state import run_learner_state_lineage_sync


def apply_index_activation_hooks(*, reset: bool) -> dict[str, Any]:
    """
    Вызывать после успешной активации новой generation (staging swap или reset).

    retrieval_cache и BM25 cache уже сброшены в clear_retrieval_cache / activate_staging_index.

    Args:
        reset: True если был build_index(reset=True).
    """
    return {
        "reset": reset,
        "learner_state_lineage": run_learner_state_lineage_sync(),
    }
