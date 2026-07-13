"""
HTTP-клиент для Streamlit UI: пул соединений (requests.Session), кэш для лёгких GET.
"""
from __future__ import annotations

import json
from typing import Any, Generator

import requests
import streamlit as st

from app.config import get_settings

# Реже дергать /ui/bootstrap при rerun Streamlit (тяжёлый get_topics_catalog на сервере).
_UI_BOOTSTRAP_CACHE_TTL_SEC = 300


def _api_base_url() -> str:
    return get_settings().ui_api_base_url.rstrip("/")


@st.cache_resource
def _http_session() -> requests.Session:
    s = requests.Session()
    s.headers.setdefault("User-Agent", "home-rag-ui/1.0")
    return s


def _auth_headers(extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(extra_headers or {})
    api_key = (get_settings().home_rag_api_key or "").strip()
    if api_key and "X-API-Key" not in headers:
        headers["X-API-Key"] = api_key
    access_token = str(st.session_state.get("access_token") or "").strip()
    if access_token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def fetch_json(method: str, path: str, *, timeout: int = 30, **kwargs: Any) -> Any:
    """JSON-запрос к локальному API; path с ведущим ``/``."""
    base = _api_base_url()
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    kwargs["headers"] = _auth_headers(kwargs.get("headers"))
    response = _http_session().request(method, url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response.json()


def post_json_no_raise(path: str, json_body: dict, *, timeout: int = 15) -> requests.Response:
    """POST без ``raise_for_status`` — для эндпойнтов, где вызывающий код сам разбирает статусы

    (например /auth/login|register: 401/409/422 — это ожидаемые ответы, не транспортные ошибки).
    """
    base = _api_base_url()
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    return _http_session().post(url, json=json_body, headers=_auth_headers(), timeout=timeout)


def post_knowledge_workflow(
    action: str,
    knowledge_product_trace: dict | None = None,
    payload: dict | None = None,
) -> None:
    """Fire-and-forget метрики knowledge workflow (локальный API)."""
    try:
        body: dict = {"action": action, "knowledge_product_trace": knowledge_product_trace or {}}
        if payload:
            body["payload"] = payload
        _http_session().post(
            f"{_api_base_url()}/metrics/knowledge-workflow",
            json=body,
            headers=_auth_headers(),
            timeout=3,
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return


@st.cache_data(ttl=12, show_spinner=False)
def _cached_index_stats(api_base: str) -> dict[str, Any]:
    r = _http_session().get(f"{api_base}/index/stats", headers=_auth_headers(), timeout=20)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_kb_overview(api_base: str) -> dict[str, Any]:
    r = _http_session().get(f"{api_base}/kb/overview", headers=_auth_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=_UI_BOOTSTRAP_CACHE_TTL_SEC, show_spinner="Загрузка базы знаний…")
def _cached_ui_bootstrap(api_base: str) -> dict[str, Any]:
    """Один запрос: index_stats + kb_overview + topics (меньше латентности главной)."""
    r = _http_session().get(f"{api_base}/ui/bootstrap", headers=_auth_headers(), timeout=45)
    r.raise_for_status()
    return r.json()


def load_index_stats() -> dict[str, Any] | None:
    try:
        return _cached_index_stats(_api_base_url())
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None


def load_kb_overview() -> dict[str, Any] | None:
    try:
        return _cached_kb_overview(_api_base_url())
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None


def load_ui_bootstrap() -> dict[str, Any] | None:
    try:
        return _cached_ui_bootstrap(_api_base_url())
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None


def stream_ssr_explain(
    ctx: dict[str, Any],
    *,
    hint_kind: str,
    primary_label_ru: str,
    why_now_ru: str,
    primary_nav: str,
    route_pedagogy_ru: str = "",
    ml_audit_ru: str = "",
    has_secondaries: bool = False,
    evidence_ledger: list[str] | None = None,
) -> Generator[str, None, None]:
    """Stream SSR explanation tokens from POST /ssr/explain (SSE).

    Yields decoded string tokens. On any error yields nothing; the caller
    is responsible for falling back to ``why_now_ru``.
    """
    payload: dict[str, Any] = {
        "ctx": ctx,
        "hint_kind": hint_kind,
        "primary_label_ru": primary_label_ru,
        "why_now_ru": why_now_ru,
        "primary_nav": primary_nav,
        "route_pedagogy_ru": route_pedagogy_ru,
        "ml_audit_ru": ml_audit_ru,
        "has_secondaries": has_secondaries,
        "evidence_ledger": evidence_ledger,
    }
    try:
        url = f"{_api_base_url()}/ssr/explain"
        resp = _http_session().post(
            url,
            json=payload,
            headers=_auth_headers({"Accept": "text/event-stream"}),
            stream=True,
            timeout=(5, 2),  # (connect, read): 2s idle cap so Streamlit never freezes
        )
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            yield json.loads(data)
    except Exception:  # noqa: BLE001
        return


def clear_ui_api_caches() -> None:
    """Сбросить кэш лёгких GET (после переиндексации и т.п.)."""
    _cached_index_stats.clear()
    _cached_kb_overview.clear()
    _cached_ui_bootstrap.clear()
