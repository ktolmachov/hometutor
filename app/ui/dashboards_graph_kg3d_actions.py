"""KG 3D-hall action handlers extracted from dashboards_graph (size budget).

W5a ask handoff and related helpers live here so the main dashboard module
does not grow past the architecture peak-file ceiling.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.knowledge_graph_d3 import KG_3D_ACTION_RESULT_KEY, mark_kg_3d_event


def _kg_3d_tutor_context(
    knowledge_graph: Any,
    concept_id: str,
    label: str,
) -> tuple[dict, float, list[str], int, bool]:
    """Best-effort concept context for tutor prompt (no domain write)."""
    info: dict = {}
    mastery_pct = 0.0
    prereqs: list[str] = []
    related_docs_count = 0
    is_frontier = False
    mastery_01: dict = {}
    if knowledge_graph is None:
        info = {"level": "—", "description": ""}
        if label:
            info["description"] = f"Концепт «{label}» из 3D-зала Мнемополиса."
        return info, mastery_pct, prereqs, related_docs_count, is_frontier

    try:
        concepts = knowledge_graph.get_concepts() or {}
        raw = concepts.get(concept_id) if isinstance(concepts, dict) else None
        info = raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - best-effort graph context
        info = {}
    try:
        from app.knowledge_service import get_mastery_vector

        mastery_01 = get_mastery_vector() or {}
        raw_m = mastery_01.get(concept_id)
        if raw_m is not None:
            mastery_pct = float(raw_m)
            if mastery_pct <= 1.0:
                mastery_pct *= 100.0
    except Exception:  # noqa: BLE001
        mastery_pct = 0.0
        mastery_01 = {}
    try:
        prereqs = list(knowledge_graph.get_prerequisites(concept_id) or [])[:8]
    except Exception:  # noqa: BLE001
        prereqs = []
    try:
        related_docs_count = len(list(knowledge_graph.get_related_documents(concept_id) or []))
    except Exception:  # noqa: BLE001
        related_docs_count = 0
    # Same frontier heuristic as 2D concept panel (KG has no is_frontier()).
    try:
        is_frontier = bool(info.get("frontier")) or (
            mastery_pct < 80.0
            and all(float(mastery_01.get(p, 0.0) or 0.0) >= 0.8 for p in prereqs)
        )
    except Exception:  # noqa: BLE001
        is_frontier = False

    if not info:
        info = {"level": "—", "description": ""}
    if not str(info.get("description") or "").strip() and label:
        info = {**info, "description": f"Концепт «{label}» из 3D-зала Мнемополиса."}
    return info, mastery_pct, prereqs, related_docs_count, is_frontier


def run_kg_3d_ask_action(
    *,
    target: Any,
    knowledge_graph: Any,
    concept_id: str,
    event_id: str,
    label: str,
    state: Any,
    build_tutor_prompt,
) -> None:
    """W5a: interior/panel «Спросить об этом» → «Чат с тьютором» (nav only).

    Uses ``build_tutor_prompt`` + ``tutor_pending_prompt``. No domain write;
    no inline LLM in the hall (C1 handoff only).
    """
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    info, mastery_pct, prereqs, related_docs_count, is_frontier = _kg_3d_tutor_context(
        knowledge_graph, concept_id, label
    )
    prompt = build_tutor_prompt(
        concept_id,
        info=info,
        mastery_pct=mastery_pct,
        prereqs=[str(p) for p in prereqs if str(p).strip()],
        related_docs_count=int(related_docs_count or 0),
        is_frontier=bool(is_frontier),
        mode="explain",
    )
    target["tutor_pending_prompt"] = prompt
    target["tutor_pending_session_id"] = target.get("tutor_session_id")
    target["tutor_cta_action"] = f"KG3D:{concept_id}:explain"
    target["current_topic"] = label or concept_id
    target["kg_selected_concept"] = concept_id
    target["kg_action_concept"] = concept_id
    target[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
    mark_kg_3d_event(target, event_id, "succeeded")
    target.pop(KG_3D_ACTION_RESULT_KEY, None)
    if state is None:
        st.toast(f"💬 Спросить о **{label or concept_id}** → Тьютор", icon="🎓")
        st.rerun()
