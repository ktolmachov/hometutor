"""Опрос статуса переиндексации для вкладки Q&A (P5c split)."""

from __future__ import annotations

import streamlit as st

from app.ui_client import fetch_json


def poll_reindex_status_for_query_tab() -> None:
    if not st.session_state.get("poll_reindex_status"):
        return
    try:
        st_ix = fetch_json("GET", "/reindex/status", timeout=10)
        ix_stat = str(st_ix.get("status") or "")
        if ix_stat in ("completed", "failed"):
            st.session_state["poll_reindex_status"] = False
            if ix_stat == "completed":
                summ = st_ix.get("ingest_run_summary")
                if isinstance(summ, dict) and summ.get("human_ru"):
                    st.success(str(summ["human_ru"]))
            elif ix_stat == "failed":
                st.warning(f"Индексация остановилась с ошибкой: {st_ix.get('error')}")
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
