"""Deterministic helpers для UX graduation / localhost balance alignment.

Стендалон модуль восстановлен (AR-2026-04 удалил файл): только чистые функции без LLM-хардкода.
Course delight loop опирается на profile/data_mode через настройки.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings


def delight_data_mode_is_demo(settings: Any | None = None) -> bool:
    s = settings or get_settings()
    return str(getattr(s, "home_rag_data_mode", "real") or "real").strip().lower() == "demo"


def primary_profile_label(settings: Any | None = None) -> str:
    s = settings or get_settings()
    return str(getattr(s, "home_rag_local_profile", "balanced") or "balanced").strip().lower()


def delight_privacy_notice(*, demo: bool, profile_label: str) -> str:
    """Короткое текстовое пояснение для UI: контекст уходит в LLM, файлы локально — см. балансовый план §3.2."""
    if demo:
        return (
            "DEMO режим данных: возможна подмешка демонстрационного корпуса; "
            "LLM профиль задаёт HOME_RAG_LOCAL_PROFILE."
        )
    if profile_label == "cloud_fast":
        return "Файлы и индекс локально; primary chat обслуживается облаком (CLOUD_FAST)."
    if profile_label == "local_strict":
        return "Строго локально: ни primary chat LLM, ни fallback облако не должны использоваться автоматически."
    return "BALANCED: primary chat локально при здоровом endpoint; при circuit breaker возможен короткий cloud fallback."


def emit_e2e_graduation_event(
    session_id: str,
    *,
    llm_model: str,
    llm_source: str,
    fallback_used: bool,
    course_id: str | None = None,
    sessions_dir: Path | None = None,
) -> None:
    """Append e2e_graduation event to session tape.

    Must be called at delight loop exit after all steps complete.
    Does NOT write raw answer text (privacy constraint).
    """
    from app.session_tape import append_event

    append_event(
        session_id,
        "e2e_graduation",
        {
            "llm_model": llm_model,
            "llm_source": llm_source,
            "fallback_used": fallback_used,
        },
        course_id=course_id,
        sessions_dir=sessions_dir,
    )
