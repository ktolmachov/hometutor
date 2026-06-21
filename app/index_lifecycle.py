"""
Политика жизненного цикла индекса и производных артефактов (итерация 16 tail).

Сводная таблица — в doc/index_lifecycle.md. Здесь — хуки после успешной активации индекса
(FAQ по флагу, eager sync learner lineage в user_state.db).
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.logging_config import setup_logging
from app.user_state import run_learner_state_lineage_sync

logger = setup_logging()


def apply_index_activation_hooks(*, reset: bool) -> dict[str, Any]:
    """
    Вызывать после успешной активации новой generation (staging swap или reset).

    retrieval_cache и BM25 cache уже сброшены в clear_retrieval_cache / activate_staging_index.

    Args:
        reset: True если был build_index(reset=True).
    """
    settings = get_settings()
    result: dict[str, Any] = {
        "reset": reset,
        "faq_cleared": False,
        "learner_state_lineage": run_learner_state_lineage_sync(),
    }

    if settings.clear_faq_on_index_activation:
        from app import faq_memory

        faq_memory.clear_faq_memory_file()
        result["faq_cleared"] = True
        logger.info("index_activation_hooks | faq_cleared=True | reset=%s", reset)

    return result


def lifecycle_policy_summary() -> dict[str, Any]:
    """Краткое JSON-представление политики (для тестов и опциональных endpoint)."""
    return {
        "clear_faq_on_index_activation": get_settings().clear_faq_on_index_activation,
        "note": "Полная таблица артефактов: doc/index_lifecycle.md",
    }
