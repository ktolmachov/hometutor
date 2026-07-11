"""System readiness preflight card for Streamlit."""

from __future__ import annotations

from typing import Any

import requests
import streamlit as st

from app.config import get_settings
from app.ui_client import clear_ui_api_caches, fetch_json


def _short_error(value: object) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    if "Traceback" in text:
        text = text.split("Traceback", 1)[0].strip()
    return text[:180] or "неизвестная ошибка"


@st.cache_data(ttl=45, show_spinner=False)
def _cached_health_deep(api_base: str) -> dict | None:
    _ = api_base
    try:
        return fetch_json("GET", "/health/deep", timeout=8)
    except requests.HTTPError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None
        url = response.url if response is not None else f"{api_base}/health/deep"
        return {
            "status": "api_error",
            "components": {
                "api": {
                    "status": "http_error",
                    "status_code": status_code,
                    "url": url,
                    "error": str(exc),
                }
            },
        }
    except Exception:  # noqa: BLE001 - preflight must degrade without breaking UI.
        return None


def preflight_rows(payload: dict | None) -> list[tuple[str, str, str]]:
    settings = get_settings()
    if payload is None:
        return [("API", "❌", "API недоступен — запустите main.py (см. quickstart.md).")]

    components = payload.get("components") if isinstance(payload.get("components"), dict) else {}
    rows: list[tuple[str, str, str]] = []

    index = components.get("index") if isinstance(components.get("index"), dict) else {}
    index_status = str(index.get("status") or "").strip().lower()
    if index_status == "ok":
        rows.append(("Материалы", "✅", f"Материалы: {int(index.get('documents_count') or 0)} документов"))
    elif index_status in {"empty", "missing"}:
        rows.append(("Материалы", "⚠️", "Материалов нет — добавьте ниже."))
    elif index_status == "error":
        rows.append(("Материалы", "❌", f"Индекс недоступен: {_short_error(index.get('error'))}"))
    else:
        rows.append(("Материалы", "⚠️", "Статус индекса пока неизвестен."))

    llm = components.get("llm") if isinstance(components.get("llm"), dict) else {}
    llm_status = str(llm.get("status") or "").strip().lower()
    if llm_status == "ok":
        latency = llm.get("latency_ms")
        rows.append(("Модель", "✅", f"Модель отвечает ({latency} мс)" if latency is not None else "Модель отвечает"))
    elif llm_status in {"timeout", "error"}:
        rows.append(
            (
                "Модель",
                "⚠️",
                "Запустите LM Studio или совместимый сервер и загрузите модель "
                f"{settings.llm_model}; адрес: {settings.llm_api_base}",
            )
        )
    else:
        rows.append(("Модель", "⚠️", "Статус модели пока неизвестен."))

    api = components.get("api") if isinstance(components.get("api"), dict) else {}
    api_status = str(api.get("status") or "").strip().lower()
    if api_status == "ok":
        rows.append(("API", "✅", "API отвечает"))
    elif api_status == "http_error":
        status_code = api.get("status_code")
        url = str(api.get("url") or settings.ui_api_base_url).strip()
        if status_code == 404:
            hint = (
                f"API отвечает 404 на {url}. На порту {settings.ui_api_base_url} запущен "
                "не HomeTutor API или старая версия без /health/deep; перезапустите FastAPI из этого репозитория."
            )
        else:
            hint = f"API вернул HTTP {status_code or '?'} на {url}: {_short_error(api.get('error'))}"
        rows.append(("API", "❌", hint))
    else:
        rows.append(("API", "⚠️", "API отвечает нестабильно"))
    return rows


def _overall_from_payload(payload: dict | None) -> str:
    if payload is None:
        return "api_down"
    return "ok" if str(payload.get("status") or "") == "ok" else "degraded"


def render_preflight_card(*, quiet_ok: bool = False) -> str:
    settings = get_settings()
    payload = _cached_health_deep(settings.ui_api_base_url.rstrip("/"))
    overall = _overall_from_payload(payload)
    if not st.session_state.get("_preflight_status_tracked"):
        try:
            from app.ui_events import track_event

            track_event("preflight_status", {"overall": overall})
        except Exception:  # noqa: BLE001
            pass
        st.session_state["_preflight_status_tracked"] = True

    if overall == "ok":
        if not quiet_ok:
            st.caption("Система готова: материалы · модель · API")
        return overall

    rows = preflight_rows(payload)
    lines = [f"{icon} **{label}:** {hint}" for label, icon, hint in rows]
    st.warning("\n\n".join(lines))
    if st.button("Проверить снова", key="preflight_check_again", type="secondary"):
        _cached_health_deep.clear()
        clear_ui_api_caches()
        st.session_state.pop("_preflight_status_tracked", None)
        st.rerun()
    return overall
