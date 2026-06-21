"""Sync debug.latency_budget from API responses into Streamlit session_state."""

from __future__ import annotations

from typing import Any

import streamlit as st


def _apply_latency_budget_event(budget: dict[str, Any]) -> None:
    st.session_state["latency_budget_last_event"] = dict(budget)
    if budget.get("event") == "surface_breached_soft":
        st.session_state["latency_budget_soft_breach_active"] = True


def sync_latency_budget_from_debug(debug: dict[str, Any] | None) -> None:
    """Write ``latency_budget_last_event``; set soft breach flag on ``surface_breached_soft``."""
    if not isinstance(debug, dict):
        return
    budget = debug.get("latency_budget")
    if not isinstance(budget, dict):
        return
    _apply_latency_budget_event(budget)


def sync_latency_budget_from_payload(payload: dict[str, Any] | None) -> None:
    """Sync top-level ``latency_budget`` from quiz service returns into session_state."""
    if not isinstance(payload, dict):
        return
    budget = payload.get("latency_budget")
    if not isinstance(budget, dict):
        return
    _apply_latency_budget_event(budget)
