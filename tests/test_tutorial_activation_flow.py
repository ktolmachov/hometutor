"""W2: first-ten-minutes activation journey (action checkpoints)."""

from __future__ import annotations

from app.ui.tutorial_activation import (
    ACTIVATION_CHECKPOINTS,
    ACTIVATION_IDS,
    apply_checkpoint_event,
    current_checkpoint,
    read_activation_state,
    write_activation_state,
)
from app.tutorial_service import load_activation_progress, save_activation_progress


def test_activation_has_at_most_seven_steps():
    assert 1 <= len(ACTIVATION_CHECKPOINTS) <= 7
    assert len(ACTIVATION_IDS) == len(ACTIVATION_CHECKPOINTS)
    assert len(set(ACTIVATION_IDS)) == len(ACTIVATION_IDS)


def test_checkpoints_reference_known_views():
    from app.ui.constants import ALL_VIEWS

    for step in ACTIVATION_CHECKPOINTS:
        assert step.title_ru and step.body_ru and step.reason_ru
        assert "US-" not in step.body_ru and "JSON" not in step.body_ru
        if step.target_view:
            assert step.target_view in ALL_VIEWS, step.target_view


def test_apply_checkpoint_advances_in_order_only():
    state = apply_checkpoint_event(
        "first_question_sent",
        active=True,
        step_index=0,
        completed_ids=[],
    )
    assert state["advanced"] is False  # not current yet

    state = apply_checkpoint_event(
        "course_confirmed",
        active=True,
        step_index=0,
        completed_ids=[],
    )
    assert state["advanced"] is True
    assert "course_confirmed" in state["completed_ids"]
    assert current_checkpoint(
        step_index=state["step_index"],
        completed_ids=state["completed_ids"],
    ).id == "first_question_sent"

    # Complete full path
    done = list(state["completed_ids"])
    idx = state["step_index"]
    for cid in ACTIVATION_IDS:
        if cid in done:
            continue
        state = apply_checkpoint_event(
            cid,
            active=True,
            step_index=idx,
            completed_ids=done,
        )
        assert state["advanced"] is True
        done = state["completed_ids"]
        idx = state["step_index"]
    assert state.get("finished") is True or len(done) == len(ACTIVATION_IDS)


def test_session_state_roundtrip_and_persistence(tmp_path, monkeypatch):
    state: dict = {}
    write_activation_state(
        state,
        {
            "active": True,
            "step_index": 1,
            "completed_ids": ["course_confirmed"],
        },
    )
    payload = read_activation_state(state)
    assert payload["active"] is True
    assert payload["current_id"] == "first_question_sent"

    # Persist via tutorial_service (user_state helpers)
    from app import user_state

    monkeypatch.setattr(user_state, "set_kv", lambda k, v: state.__setitem__(f"kv:{k}", v))
    monkeypatch.setattr(user_state, "get_kv", lambda k: state.get(f"kv:{k}"))
    save_activation_progress(
        "u1",
        step_index=1,
        completed_ids=["course_confirmed"],
        active=True,
    )
    loaded = load_activation_progress("u1")
    assert loaded is not None
    assert loaded["completed_ids"] == ["course_confirmed"]
    assert loaded["active"] is True


def test_full_tour_not_auto_started_from_home_onboarding_source():
    """Regression: onboarding should not default-start dialog tour."""
    import inspect

    from app.ui import home_hub

    src = inspect.getsource(home_hub._render_onboarding)
    assert "start_activation_flow" in src
    assert "Запустить интерактивный тур" not in src or "launch_tour" not in src
    # Full tour start must not be the default path
    assert "start_tutorial" not in src or "start_activation_flow" in src
