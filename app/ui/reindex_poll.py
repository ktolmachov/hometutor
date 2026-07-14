"""Shared reindex status poller for Streamlit surfaces."""

from __future__ import annotations

import time

import streamlit as st

from app.ui_client import clear_ui_api_caches, fetch_json


_PHASE_LABELS_RU = {
    "building": "Готовлю индекс",
    "failed": "Ошибка индексации",
    "idle": "Ожидание",
}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _running_progress(payload: dict) -> tuple[float | None, str]:
    unique_total = _as_int(payload.get("ingest_unique_total"))
    unique_processed = _as_int(payload.get("ingest_unique_processed"))
    total = unique_total or _as_int(payload.get("total_files"))
    processed = unique_processed or _as_int(payload.get("processed_files"))
    phase = str(payload.get("lifecycle_phase") or "").strip()
    current = str(payload.get("current_file") or "").strip()

    label = _PHASE_LABELS_RU.get(phase, "Индексирую материалы")
    if total > 0:
        ratio = min(1.0, max(0.0, processed / float(total)))
        text = f"{label}: {processed}/{total}"
    else:
        ratio = None
        text = f"{label}: запуск"
    if current:
        text = f"{text} · {current}"
    return ratio, text


def _refresh_soon(delay_sec: float = 1.0) -> None:
    time.sleep(delay_sec)
    st.rerun()


def poll_reindex_status() -> None:
    message = st.session_state.pop("_reindex_success_message", None)
    if message:
        st.success(message)
    if not st.session_state.get("poll_reindex_status"):
        return
    try:
        payload = fetch_json("GET", "/reindex/status", timeout=10)
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).debug("reindex status poll failed: %s", exc)
        return
    status = str(payload.get("status") or "")
    if status == "completed":
        st.session_state["poll_reindex_status"] = False
        summary = payload.get("ingest_run_summary")
        if isinstance(summary, dict) and summary.get("human_ru"):
            st.session_state["_reindex_success_message"] = str(summary["human_ru"])
        clear_ui_api_caches()
        st.rerun()
    elif status == "failed":
        st.session_state["poll_reindex_status"] = False
        st.warning(f"Индексация остановилась с ошибкой: {payload.get('error')}")
    elif status == "running":
        ratio, text = _running_progress(payload)
        if ratio is None:
            st.info(text)
        else:
            st.progress(ratio, text=text)
        _refresh_soon()
    else:
        st.info("Запускаю индексацию материалов…")
        _refresh_soon()
