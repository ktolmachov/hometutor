"""Small UI-state helpers for the Knowledge Graph dashboard."""

from __future__ import annotations

from typing import Any

import streamlit as st


def _workbench_state_rows(state: Any | None = None) -> list[dict]:
    from app import workbench_service

    source = st.session_state if state is None else state
    return workbench_service.normalize_runtime_rows(
        list(source.get(workbench_service.WORKBENCH_SECTIONS_KEY) or [])
    )


def _workbench_collected_concept_ids(state: Any | None = None) -> list[str]:
    """Concept ids that already have at least one section in the workbench basket."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in _workbench_state_rows(state):
        cid = str(row.get("concept") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    return ids


def _prime_kg_3d_action_focus(
    target: Any,
    *,
    action: str,
    concept_id: str,
    event_id: str,
    label: str,
) -> None:
    from app.ui.knowledge_graph_d3 import KG_3D_ACTION_KEY

    target[KG_3D_ACTION_KEY] = {
        "action": action,
        "concept_id": concept_id,
        "event_id": event_id,
    }
    target["kg_selected_concept"] = concept_id
    target["kg_action_concept"] = concept_id
    target["interactive_quiz_focus_concept"] = concept_id
    target["current_topic"] = label
