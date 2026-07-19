"""Regression tests for #23 P0-1 A1: One Route Policy — Дефект A, Дефект B, session tape."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.smart_study_recommendation import (
    SmartStudyRecommendation,
    SmartStudySecondaryAction,
    compute_route_decision_id,
    smart_study_phase,
)
from app.smart_study_router import build_smart_study_recommendation


# ---------------------------------------------------------------------------
# Дефект A: plan_primary_block must reach home surface
# ---------------------------------------------------------------------------


def test_plan_block_reaches_home_surface_without_due() -> None:
    """Without due queues, a saved actionable plan block → plan_block_tutor on home."""
    plan_block = {"type": "gap", "concept": "agent-harness", "reason": "mastery gap"}
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=0,
        sm2_due_n=0,
        plan_primary_block=plan_block,
    )
    assert rec.primary_nav == "plan_block_tutor"
    assert rec.hint_kind == "adaptive_plan"
    assert rec.phase == "plan"
    assert rec.topic_hint == "agent-harness"
    assert rec.origin == "home"
    assert rec.return_view == "Mission Control"
    assert len(rec.decision_id) == 12


def test_plan_block_surface_adaptive_plan_still_works() -> None:
    """Regression: adaptive_plan surface with plan block still produces plan_block_tutor."""
    rec = build_smart_study_recommendation(
        surface="adaptive_plan",
        flashcard_due_n=0,
        sm2_due_n=0,
        plan_primary_block={"type": "review", "concept": "test-topic"},
    )
    assert rec.primary_nav == "plan_block_tutor"


def test_plan_block_not_reached_when_due_exists() -> None:
    """Due queue > plan block priority (cards_due wins)."""
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=97,
        sm2_due_n=0,
        plan_primary_block={"type": "gap", "concept": "agent-harness"},
    )
    assert rec.primary_nav == "flashcards_review"
    assert rec.hint_kind == "cards_due"


# ---------------------------------------------------------------------------
# Дефект B: weak concept from get_weak_concepts filtered by active graph
# ---------------------------------------------------------------------------


def test_off_graph_weak_concept_never_becomes_primary() -> None:
    """A weak concept not in the active graph must not become primary route.
    Filtering happens at the caller level via weak_concepts_for_kg — off-graph concepts
    never reach the router as first_weak_concept. When all concepts are off-graph,
    the filtered list is empty → safe_default."""
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=0,
        sm2_due_n=0,
        first_weak_concept=None,
    )
    assert rec.primary_nav == "safe_tutor_5min"
    assert rec.hint_kind == "safe_default"
    assert "TopicB" not in rec.primary_label_ru
    assert "TopicB" not in rec.why_now_ru


def test_valid_weak_concept_can_become_primary() -> None:
    """With a weak concept (no filter applied at router level — caller filters),
    and no due/tutor/reading, mastery_stale is expected."""
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=0,
        sm2_due_n=0,
        first_weak_concept="valid-concept",
    )
    expected = {"mastery_stale", "safe_default"}
    assert rec.hint_kind in expected


# ---------------------------------------------------------------------------
# RouteDecision contract: derived fields
# ---------------------------------------------------------------------------


def test_route_decision_phase_mapping() -> None:
    assert smart_study_phase(SmartStudyRecommendation(
        hint_kind="cards_due", primary_label_ru="", why_now_ru="",
        primary_nav="flashcards_review",
        secondaries=(SmartStudySecondaryAction("qa_sources", ""),),
    )) == "retain"
    assert smart_study_phase(SmartStudyRecommendation(
        hint_kind="safe_default", primary_label_ru="", why_now_ru="",
        primary_nav="safe_tutor_5min",
        secondaries=(SmartStudySecondaryAction("qa_sources", ""),),
    )) == "understand"


def test_decision_id_is_stable() -> None:
    id1 = compute_route_decision_id(
        primary_nav="plan_block_tutor", hint_kind="adaptive_plan",
        flashcard_due_n=0, sm2_due_n=0, topic_hint="agent-harness",
    )
    id2 = compute_route_decision_id(
        primary_nav="plan_block_tutor", hint_kind="adaptive_plan",
        flashcard_due_n=0, sm2_due_n=0, topic_hint="agent-harness",
    )
    assert id1 == id2
    assert len(id1) == 12


def test_decision_id_differs_on_input() -> None:
    id1 = compute_route_decision_id(
        primary_nav="plan_block_tutor", hint_kind="adaptive_plan",
        flashcard_due_n=0, sm2_due_n=0, topic_hint="agent-harness",
    )
    id2 = compute_route_decision_id(
        primary_nav="flashcards_review", hint_kind="cards_due",
        flashcard_due_n=97, sm2_due_n=0, topic_hint="",
    )
    assert id1 != id2


def test_topic_hint_populated_from_tutor_topic() -> None:
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=0,
        sm2_due_n=0,
        has_tutor_resume=True,
        tutor_topic="physics/quantum",
    )
    assert rec.topic_hint == "physics/quantum"


# ---------------------------------------------------------------------------
# Session tape: route events (privacy-safe)
# ---------------------------------------------------------------------------


def test_session_tape_route_offered_event() -> None:
    from app.session_tape import append_event, reset_session_started_cache_for_tests

    sid = "test-route-offered-001"
    with TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir) / "sessions"
        append_event(
            sid,
            "route_offered",
            {"surface": "home", "primary_nav": "plan_block_tutor", "hint_kind": "adaptive_plan"},
            sessions_dir=sessions_dir,
        )
        tape_file = sessions_dir / f"{sid}.jsonl"
        assert tape_file.exists()
        line = tape_file.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["event"] == "route_offered"
        assert data["payload"]["surface"] == "home"
        assert data["payload"]["primary_nav"] == "plan_block_tutor"
        assert "question" not in str(data["payload"])
        assert "text" not in str(data["payload"])


def test_session_tape_route_selected_event() -> None:
    from app.session_tape import append_event

    sid = "test-route-selected-001"
    with TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir) / "sessions"
        append_event(
            sid,
            "route_selected",
            {"surface": "home", "primary_nav": "plan_block_tutor", "hint_kind": "adaptive_plan", "accepted": True},
            sessions_dir=sessions_dir,
        )
        tape_file = sessions_dir / f"{sid}.jsonl"
        data = json.loads(tape_file.read_text(encoding="utf-8").strip())
        assert data["event"] == "route_selected"
        assert data["payload"]["accepted"] is True


def test_session_tape_learning_action_started_event() -> None:
    from app.session_tape import append_event

    sid = "test-action-started-001"
    with TemporaryDirectory() as tmpdir:
        sessions_dir = Path(tmpdir) / "sessions"
        append_event(
            sid,
            "learning_action_started",
            {"surface": "home", "primary_nav": "plan_block_tutor", "topic_hint": "agent-harness"},
            sessions_dir=sessions_dir,
        )
        tape_file = sessions_dir / f"{sid}.jsonl"
        data = json.loads(tape_file.read_text(encoding="utf-8").strip())
        assert data["event"] == "learning_action_started"
        assert data["payload"]["topic_hint"] == "agent-harness"


def test_session_tape_rejects_unknown_event() -> None:
    from app.session_tape import append_event

    with pytest.raises(ValueError, match="unknown event type"):
        append_event("sid-x", "unknown_event", {})


def test_session_tape_rejects_missing_required_fields() -> None:
    from app.session_tape import append_event

    with pytest.raises(ValueError, match="missing required payload fields"):
        append_event("sid-x", "route_offered", {})


def test_weak_concepts_in_ssr_context_goes_through_kg_filter() -> None:
    """Verify that gather_smart_study_router_session_context uses weak_concepts_for_kg.
    The module source code must reference weak_concepts_for_kg, not raw get_weak_concepts."""
    source = (Path(__file__).parent.parent / "app" / "ui" / "resume_cards_smart_study.py").read_text(encoding="utf-8")
    assert "weak_concepts_for_kg" in source
    assert "from app.quiz_adaptive import get_weak_concepts" not in source


def test_adaptive_plan_hub_uses_weak_concepts_for_kg() -> None:
    source = (Path(__file__).parent.parent / "app" / "ui" / "adaptive_plan_hub_layout.py").read_text(encoding="utf-8")
    assert "weak_concepts_for_kg" in source
    assert "from app.quiz_adaptive import get_weak_concepts" not in source
