"""Streamlit banner: visibility for local SSR LLM endpoint health.

Consumes the ``llm_local`` field added to ``/ui/bootstrap``. Renders nothing
when the endpoint is healthy or the probe was skipped (cloud provider). Two
visible states:

- ``reachable=False`` → warning: endpoint not reachable; SSR will fall back to
  the deterministic template explanation.
- ``reachable=True`` and ``model_loaded=False`` → info: endpoint up, but the
  configured model id is not loaded; SSR LLM calls will fail with a 4xx until
  the right model is loaded in LM Studio.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

_BANNER_KEY = "_llm_local_banner_dismissed"
_BUDGET_BANNER_KEY = "latency_budget_banner_dismissed"
_BUDGET_SURFACES = frozenset({"mission_load", "query", "tutor_turn", "quiz_gen", "quiz_submit"})


def _build_status(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return ``{kind, headline, detail, base_url, model}`` or ``None`` if no banner needed."""
    if not isinstance(payload, dict):
        return None
    if payload.get("skipped"):
        return None
    base_url = payload.get("base_url") or "—"
    model = payload.get("model") or "—"
    if payload.get("reachable") is False:
        error = str(payload.get("error") or "unknown error")
        return {
            "kind": "warning",
            "headline": "Локальная LLM недоступна — SSR работает в template-режиме",
            "detail": (
                f"Endpoint **{base_url}** не отвечает (`{error}`). "
                "Карточка «Почему сейчас» формируется по шаблону, без персонализации. "
                "Чтобы включить LLM-режим: запустите LM Studio (или совместимый сервер) "
                f"и убедитесь, что в нём загружена модель **{model}**."
            ),
            "base_url": base_url,
            "model": model,
        }
    if payload.get("reachable") and payload.get("model_loaded") is False:
        return {
            "kind": "info",
            "headline": "Локальный LLM-endpoint доступен, но нужная модель не загружена",
            "detail": (
                f"На **{base_url}** не нашлась модель **{model}**. "
                "Загрузите её в LM Studio либо поправьте `SSR_LLM_MODEL` в `.env`."
            ),
            "base_url": base_url,
            "model": model,
        }
    return None


def render_llm_local_banner(bootstrap_payload: dict[str, Any] | None) -> None:
    """Render the banner once per Streamlit run; safe to call when payload is missing."""
    try:
        if bootstrap_payload is None:
            return
        status = _build_status(bootstrap_payload.get("llm_local") if isinstance(bootstrap_payload, dict) else None)
        if status is None:
            return
        # Per-session dismiss: user can hide the banner; will reappear on next browser session.
        if st.session_state.get(_BANNER_KEY):
            return
        renderer = st.warning if status["kind"] == "warning" else st.info
        renderer(f"**{status['headline']}**\n\n{status['detail']}")
        with st.expander("Подробности диагностики local LLM", expanded=False):
            st.code(
                f"base_url: {status['base_url']}\nmodel:    {status['model']}\n",
                language="text",
            )
            if st.button("Скрыть до следующего запуска", key="_llm_local_banner_dismiss"):
                st.session_state[_BANNER_KEY] = True
                st.rerun()
    except Exception as exc:  # noqa: BLE001 - UI must survive banner errors.
        st.caption(f"(не удалось отрисовать баннер local LLM: {type(exc).__name__}: {exc})")


def _latency_budget_banner_detail(last_event: dict[str, Any]) -> str | None:
    surface = last_event.get("surface")
    actual_ms = last_event.get("actual_ms")
    target_ms = last_event.get("target_ms")
    if surface == "query":
        return (
            f"Ответ занял больше ожидаемого ({actual_ms} ms при бюджете {target_ms} ms). "
            "Используется упрощённый режим генерации."
        )
    if surface == "tutor_turn":
        return (
            f"Шаг тьютора занял больше ожидаемого ({actual_ms} ms при бюджете {target_ms} ms). "
            "Используется упрощённый режим."
        )
    if surface == "mission_load":
        return (
            f"Загрузка первого обзора заняла больше ожидаемого ({actual_ms} ms при бюджете {target_ms} ms). "
            "Показан сохранённый или упрощённый режим."
        )
    if surface == "quiz_gen":
        return (
            f"Генерация мини-проверки заняла больше ожидаемого ({actual_ms} ms при бюджете {target_ms} ms). "
            "Используется упрощённый режим."
        )
    if surface == "quiz_submit":
        return (
            f"Проверка ответа заняла больше ожидаемого ({actual_ms} ms при бюджете {target_ms} ms). "
            "Обратная связь показана в упрощённом режиме."
        )
    return None


def should_show_latency_budget_banner(session_state: dict[str, Any]) -> bool:
    if session_state.get("latency_budget_soft_breach_active") is not True:
        return False
    if session_state.get(_BUDGET_BANNER_KEY):
        return False
    last_event = session_state.get("latency_budget_last_event")
    if not isinstance(last_event, dict):
        return False
    if last_event.get("surface") not in _BUDGET_SURFACES:
        return False
    return last_event.get("event") == "surface_breached_soft"


def render_latency_budget_banner() -> None:
    """Render soft-breach budget banner when session flags allow (post-response only)."""
    try:
        if not should_show_latency_budget_banner(st.session_state):
            return
        last_event = st.session_state.get("latency_budget_last_event") or {}
        detail = _latency_budget_banner_detail(last_event)
        if detail is None:
            return
        st.markdown(
            '<div data-testid="latency-budget-soft-breach-banner" aria-live="polite">',
            unsafe_allow_html=True,
        )
        st.info(f"**fast fallback active**\n\n{detail}")
        if st.button("Скрыть до следующего запуска", key="latency_budget_banner_dismiss"):
            st.session_state[_BUDGET_BANNER_KEY] = True
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    except Exception as exc:  # noqa: BLE001 - UI must survive banner errors.
        st.caption(f"(не удалось отрисовать баннер latency budget: {type(exc).__name__}: {exc})")
