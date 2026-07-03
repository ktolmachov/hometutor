"""Shared reindex status poller for Streamlit surfaces."""

from __future__ import annotations

import streamlit as st

from app.ui_client import clear_ui_api_caches, fetch_json


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
        st.info("Идёт индексация материалов…")
