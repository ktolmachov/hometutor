"""
Режим «офлайн» и диагностика доступности LLM-endpoint.

Важно: полноценный локальный RAG на Ollama + отдельный индекс **не** реализован здесь —
текущее ядро (``provider.py``, llama-index, Chroma) завязано на OpenAI-compatible API и
``get_embed_model()`` / ``get_llm()``. Флаг ``offline_mode`` и этот модуль нужны для
явного UX/API-сигнала и будущей интеграции в ``provider.py``, а не для дублирования Chroma.

Кэш pre-generate для слабых тем: см. ``precompute_weak_topic_quizzes`` (опционально, требует LLM).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from urllib.parse import urlparse

from app.config import DATA_DIR, get_settings
from app.knowledge_graph import get_active_knowledge_graph
from app.learner_state_scope import weak_concepts_for_kg
from app.provider import (
    _is_loopback_hostname,
    _lmstudio_api_base,
    normalize_openai_compatible_api_base,
)

logger = logging.getLogger(__name__)

_probe_cache: tuple[float, dict[str, Any]] | None = None
# Cache the LLM probe result for 5 minutes. At 60 s the log was flooded with
# "llm base probe failed" entries every minute when LM Studio was offline.
_CACHE_TTL_SEC = 300.0


def offline_mode_enabled() -> bool:
    return bool(get_settings().offline_mode)


def _local_llm_probe_bases(settings) -> list[str]:
    """Уникальные loopback-базы для offline-probe: основной LLM, graph и SSR."""
    cloud_norm = normalize_openai_compatible_api_base(
        getattr(settings, "openai_api_base", "") or ""
    )
    seen: set[str] = set()
    out: list[str] = []
    for raw in (
        _lmstudio_api_base(settings),
        (getattr(settings, "graph_llm_api_base", None) or "").strip(),
        (getattr(settings, "ssr_llm_api_base", None) or "").strip(),
    ):
        base = normalize_openai_compatible_api_base(raw)
        if not base or base in seen:
            continue
        if cloud_norm and base == cloud_norm:
            continue
        host = (urlparse(base).hostname or "").lower()
        if not (_is_loopback_hostname(host) or host == "host.docker.internal"):
            continue
        seen.add(base)
        out.append(base)
    return out


def probe_llm_base_reachable(*, timeout_sec: float = 2.0) -> bool:
    """
    Проверка доступности локальных OpenAI-compatible LLM (llama.cpp, LM Studio и т.п.).

    Перебирает ``LLM_API_BASE`` / ``LMSTUDIO_API_BASE``, ``GRAPH_LLM_API_BASE`` и
    ``SSR_LLM_API_BASE`` (loopback). Успех, если хотя бы один endpoint отвечает на
    ``GET /v1/models`` (см. ``llm_local_health.probe_local_llm``).
    """
    from app.llm_local_health import probe_local_llm

    bases = _local_llm_probe_bases(get_settings())
    if not bases:
        return False
    for base in bases:
        result = probe_local_llm(base, None, timeout_sec=timeout_sec)
        if result.get("reachable"):
            logger.debug(
                "llm base probe ok | base=%s latency_ms=%s",
                base,
                result.get("latency_ms"),
            )
            return True
        logger.debug(
            "llm base probe failed | base=%s err=%s",
            base,
            result.get("error"),
        )
    return False


def get_offline_status(*, use_cache: bool = True) -> dict[str, Any]:
    """
    Сводка для UI и ``GET /dashboard/offline_status``.

    - ``offline_mode``: явный флаг из настроек (пользователь заявляет офлайн/автономный сценарий).
    - ``llm_reachable``: результат probe (может быть None, если probe отключён).
    """
    global _probe_cache
    s = get_settings()
    now = time.monotonic()
    if use_cache and _probe_cache is not None:
        ts, payload = _probe_cache
        if now - ts < _CACHE_TTL_SEC:
            return dict(payload)

    reachable: bool | None
    if s.offline_mode or not s.offline_probe_llm_endpoint:
        reachable = None
    else:
        reachable = probe_llm_base_reachable()

    probe_bases = _local_llm_probe_bases(s)
    out: dict[str, Any] = {
        "offline_mode": bool(s.offline_mode),
        "llm_reachable": reachable,
        "lmstudio_api_base": _lmstudio_api_base(s).strip(),
        "llm_probe_bases": probe_bases,
        "hint": (
            "Полный локальный inference (Ollama) и отдельный «local pipeline» в коде не подключены; "
            "см. provider.py и vision.md. При недоступности API проверьте сеть и ключ."
            if not s.offline_mode
            else "offline_mode=True: UI может работать без сети для уже закэшированных сценариев; "
            "генерация и эмбеддинги по-прежнему требуют согласованной доработки provider/ingestion."
        ),
    }
    _probe_cache = (now, dict(out))
    return out


def precompute_weak_topic_quizzes(*, max_topics: int = 5) -> dict[str, Any]:
    """
    Опционально сгенерировать scoped-quiz по слабым концептам и сохранить JSON в ``data/offline_quiz_cache/``.

    Требует рабочий LLM (как и ``generate_scoped_quiz``). Не вызывается автоматически при старте.
    """
    from app.quiz_service import generate_scoped_quiz

    out_dir = DATA_DIR / "offline_quiz_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    weak = weak_concepts_for_kg(
        get_active_knowledge_graph(),
        threshold=60,
        limit=max(1, int(max_topics)),
    )
    saved: list[str] = []
    errors: list[dict[str, str]] = []
    for topic in weak:
        try:
            quiz = generate_scoped_quiz("topic", topic)
            if not quiz.get("success"):
                errors.append({"topic": topic, "error": quiz.get("error") or "failed"})
                continue
            import json

            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic)[:80]
            path = out_dir / f"quiz_topic_{safe}.json"
            path.write_text(json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8")
            saved.append(str(path))
        except Exception as e:
            errors.append({"topic": topic, "error": str(e)})
    return {"saved": saved, "errors": errors, "weak_topics": weak}


__all__ = [
    "get_offline_status",
    "offline_mode_enabled",
    "precompute_weak_topic_quizzes",
    "probe_llm_base_reachable",
]
