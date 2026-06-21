"""Профили вызовов SSR LLM (карточка «Почему сейчас») для сравнения с основным ``LLM_MODEL``.

Пишет JSONL-строки в ``ssr_llm_profile_log_dir`` (по умолчанию ``logs/ssr_llm_profiles/``).
Каждая строка содержит уникальный ``event_id`` для корреляции с логами/трейсами.
Основной чат и прочие стадии — в ``logs/cost_logs/cost_logs_*.jsonl`` (поле ``model``, при необходимости ``prompt_type``).

Сравнение: агрегировать по ``outcome``, ``effective_model``, ``used_main_chat_client``; latency — ``latency_ms``;
токены — ``total_tokens`` (если провайдер отдал usage). Сводка: ``scripts/summarize_ssr_llm_profiles.py``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.provider import normalize_openai_compatible_api_base
from app.prompts import SSR_LLM_EXPLANATION_PROMPT_VERSION

logger = logging.getLogger(__name__)


def _effective_model_from_llm(llm: Any | None) -> str | None:
    if llm is None:
        return None
    m = getattr(llm, "model", None)
    return str(m).strip() if m is not None else None


def record_ssr_llm_profile(
    *,
    outcome: str,
    latency_ms: float | None = None,
    used_main_chat_client: bool = False,
    llm: Any | None = None,
    effective_model: str | None = None,
    total_tokens: int | None = None,
    token_hard_cap_hit: bool = False,
    error_type: str | None = None,
    hint_kind: str | None = None,
    primary_nav: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """
    Одна строка JSONL на попытку генерации SSR-объяснения (включая cache hit и template fallback).

    ``outcome``: ``template_only`` | ``cache_hit`` | ``llm_success`` | ``template_fallback_timeout`` |
    ``template_fallback_empty`` | ``template_fallback_token_budget`` | ``error``.

    Returns:
        ``event_id`` если запись включена и записана, иначе ``None``.
    """
    s = get_settings()
    if not getattr(s, "enable_ssr_llm_profiling", True):
        return None

    raw_base = (s.ssr_llm_api_base or "").strip()
    ssr_base = normalize_openai_compatible_api_base(raw_base or s.lmstudio_api_base)
    eff = (effective_model or "").strip() or _effective_model_from_llm(llm)

    log_dir = getattr(s, "ssr_llm_profile_log_dir", None)
    if log_dir is None:
        return None
    event_id = str(uuid.uuid4())

    row: dict[str, Any] = {
        "kind": "ssr_llm_explanation",
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "prompt_version": SSR_LLM_EXPLANATION_PROMPT_VERSION,
        "outcome": outcome,
        "latency_ms": None if latency_ms is None else round(float(latency_ms), 3),
        "main_llm_model": s.llm_model,
        "configured_ssr_model": (s.ssr_llm_model or "").strip() or None,
        "effective_model": eff,
        "ssr_api_base": ssr_base,
        "used_main_chat_client": bool(used_main_chat_client),
        "total_tokens": total_tokens,
        "token_hard_cap_hit": bool(token_hard_cap_hit),
        "error_type": error_type,
        "hint_kind": hint_kind,
        "primary_nav": primary_nav,
    }
    if extra:
        row["extra"] = extra

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = log_dir / f"ssr_llm_profile_{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.warning("ssr_llm_profile_write_failed", extra={"error": str(exc)})
        return None
    return event_id
