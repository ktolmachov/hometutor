"""B3 Safe autopilot — unit + contract + integration tests.

Verifies: enable/pause/resume/finish lifecycle, budget decrement per step,
dedup by decision_id (refresh-safe), session-tape privacy-safe payload,
checkpoint integration (status indicator, activation widget).
"""

from __future__ import annotations

from pathlib import Path


# ── source-level contracts ──────────────────────────────────────────────────

class TestAutopilotSourceContracts:
    def test_autopilot_module_exists(self) -> None:
        src = (Path("app/ui/autopilot.py")).read_text(encoding="utf-8")
        assert "def enable_autopilot" in src
        assert "def pause_autopilot" in src
        assert "def resume_autopilot" in src
        assert "def finish_autopilot" in src
        assert "def step_completed" in src
        assert "def is_autopilot_active" in src
        assert "def is_autopilot_paused" in src
        assert "def budget_remaining_min" in src

    def test_budget_options_are_5_15_25(self) -> None:
        from app.ui.autopilot import _BUDGET_OPTIONS
        assert sorted(_BUDGET_OPTIONS) == [5, 15, 25]

    def test_step_cost_is_5_min(self) -> None:
        from app.ui.autopilot import _STEP_COST_MIN
        assert _STEP_COST_MIN == 5

    def test_no_background_worker(self) -> None:
        src = (Path("app/ui/autopilot.py")).read_text(encoding="utf-8")
        assert "Thread" not in src
        assert "threading" not in src
        assert "asyncio" not in src
        assert "scheduler" not in src

    def test_no_new_persistence(self) -> None:
        src = (Path("app/ui/autopilot.py")).read_text(encoding="utf-8")
        assert "sqlite" not in src
        assert ".db" not in src
        assert "user_state" not in src
        assert "json.dump" not in src

    def test_checkpoint_has_autopilot_hooks(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_render_autopilot_status" in src
        assert "_render_autopilot_activation" in src
        assert "_autopilot_budget_min_for_compass" in src
        assert "app.ui.autopilot" in src

    def test_checkpoint_store_context_calls_step_completed(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn = src.split("def store_checkpoint_context")[1].split("\ndef ")[0]
        assert "step_completed" in fn
        assert "is_new_checkpoint" in fn
        assert "prev_ck_existed" in fn
        assert "is_autopilot_active" in fn

    def test_checkpoint_actions_handle_autopilot_states(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_render_autopilot_actions" in src
        assert "_render_default_checkpoint_actions" in src
        assert "_chkpt_pause" in src
        assert "_chkpt_resume" in src
        assert "_chkpt_done" in src

    def test_no_auto_start_in_autopilot(self) -> None:
        src = (Path("app/ui/autopilot.py")).read_text(encoding="utf-8")
        assert "tutor_pending_prompt" not in src
        assert "auto_start" not in src
        assert "auto_run" not in src

    def test_autopilot_activation_passes_surface(self) -> None:
        """P2 regression: activation buttons pass entry_surface=surface."""
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_autopilot_activation")[1].split("\ndef ")[0]
        assert "entry_surface=surface" in fn

    def test_render_checkpoint_passes_surface_to_activation(self) -> None:
        """P2 regression: render_checkpoint passes surface kwarg to activation."""
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn = src.split("def render_checkpoint")[1].split("\ndef ")[0]
        assert "_render_autopilot_activation(key_prefix=key_prefix, surface=surface)" in fn


# ── autopilot lifecycle ─────────────────────────────────────────────────────

class TestAutopilotLifecycle:
    def test_enable_sets_state(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import enable_autopilot, is_autopilot_active, is_autopilot_paused

        enable_autopilot(15)
        assert is_autopilot_active()
        assert not is_autopilot_paused()
        assert st.session_state["_autopilot_budget_total_min"] == 15
        assert st.session_state["_autopilot_budget_remaining_min"] == 15
        assert st.session_state["_autopilot_steps_completed"] == 0

    def test_enable_rejects_invalid_budget(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import enable_autopilot
        try:
            enable_autopilot(10)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_pause_and_resume(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import enable_autopilot, pause_autopilot, resume_autopilot, is_autopilot_paused

        enable_autopilot(15)
        assert not is_autopilot_paused()

        pause_autopilot()
        assert is_autopilot_paused()

        resume_autopilot()
        assert not is_autopilot_paused()

    def test_pause_noop_when_inactive(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import pause_autopilot, is_autopilot_paused

        pause_autopilot()
        assert not is_autopilot_paused()

    def test_finish_clears_state(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import enable_autopilot, finish_autopilot, is_autopilot_active

        enable_autopilot(5)
        assert is_autopilot_active()

        finish_autopilot("user_finished")
        assert not is_autopilot_active()
        assert "_autopilot_enabled" not in st.session_state or not st.session_state.get("_autopilot_enabled")

    def test_step_completed_decrements_budget(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed, budget_remaining_min

        enable_autopilot(15)
        assert budget_remaining_min() == 15

        step_completed("did-1", completion_key="ck-1")
        assert budget_remaining_min() == 10

        step_completed("did-2", completion_key="ck-2")
        assert budget_remaining_min() == 5

    def test_step_completed_dedup_by_completion_key(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed

        enable_autopilot(15)
        step_completed("did-1", completion_key="ck-same")  # 15 -> 10
        step_completed("did-1", completion_key="ck-same")  # same ck, must not decrement
        assert st.session_state["_autopilot_budget_remaining_min"] == 10
        assert st.session_state["_autopilot_steps_completed"] == 1

    def test_step_completed_different_decision_same_completion_key(self, monkeypatch) -> None:
        """P1 regression: same completion_key with different decision_id — still deduped."""
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed

        enable_autopilot(15)
        step_completed("did-A", completion_key="ck-same")
        step_completed("did-B", completion_key="ck-same")
        assert st.session_state["_autopilot_budget_remaining_min"] == 10
        assert st.session_state["_autopilot_steps_completed"] == 1

    def test_step_completed_different_completion_same_decision_two_steps(self, monkeypatch) -> None:
        """P1 regression: same decision_id with different completion_keys — two steps."""
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed

        enable_autopilot(15)
        step_completed("did-same", completion_key="ck-A")
        step_completed("did-same", completion_key="ck-B")
        assert st.session_state["_autopilot_budget_remaining_min"] == 5
        assert st.session_state["_autopilot_steps_completed"] == 2

    def test_step_completed_noop_on_pause(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, pause_autopilot, step_completed

        enable_autopilot(15)
        pause_autopilot()
        step_completed("did-1", completion_key="ck-1")
        assert st.session_state["_autopilot_budget_remaining_min"] == 15
        assert st.session_state["_autopilot_steps_completed"] == 0

    def test_step_completed_noop_when_inactive(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import step_completed

        step_completed("did-1", completion_key="ck-1")
        assert "_autopilot_steps_completed" not in st.session_state

    def test_budget_exhausted_triggers_autofinish(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed, is_autopilot_active

        enable_autopilot(5)
        assert is_autopilot_active()

        step_completed("did-1", completion_key="ck-1")  # 5 -> 0
        assert not is_autopilot_active(), "Budget exhausted must auto-finish"
        assert "_autopilot_enabled" not in st.session_state or not st.session_state.get("_autopilot_enabled")

    def test_budget_remaining_min_returns_none_when_inactive(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import budget_remaining_min

        assert budget_remaining_min() is None

    def test_get_autopilot_state_returns_snapshot(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, get_autopilot_state

        enable_autopilot(25, entry_surface="Чат с тьютором")
        state = get_autopilot_state()
        assert state["enabled"] is True
        assert state["paused"] is False
        assert state["budget_total_min"] == 25
        assert state["budget_remaining_min"] == 25
        assert state["steps_completed"] == 0
        assert state["last_completion_key"] == ""
        assert state["entry_surface"] == "Чат с тьютором"


# ── session tape events ─────────────────────────────────────────────────────

class TestAutopilotSessionTape:
    def test_autopilot_events_registered(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS
        assert "autopilot_started" in EVENT_REQUIRED_FIELDS
        assert "autopilot_step" in EVENT_REQUIRED_FIELDS
        assert "autopilot_paused" in EVENT_REQUIRED_FIELDS
        assert "autopilot_resumed" in EVENT_REQUIRED_FIELDS
        assert "autopilot_finished" in EVENT_REQUIRED_FIELDS

    def test_autopilot_started_required_fields(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS
        fields = EVENT_REQUIRED_FIELDS["autopilot_started"]
        assert "budget_min" in fields
        assert "surface" in fields

    def test_autopilot_step_required_fields(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS
        fields = EVENT_REQUIRED_FIELDS["autopilot_step"]
        assert "decision_id" in fields
        assert "budget_remaining_min" in fields
        assert "latency_ms" in fields
        assert "surface" in fields

    def test_autopilot_payload_no_text_fields(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS
        text_keys = {"question", "answer", "text", "question_text", "answer_text",
                     "raw_text", "chunk", "front", "back", "body", "api_key"}
        for event_type in ["autopilot_started", "autopilot_step", "autopilot_paused",
                           "autopilot_resumed", "autopilot_finished"]:
            fields = EVENT_REQUIRED_FIELDS[event_type]
            for tk in text_keys:
                assert tk not in fields, f"{event_type} must not include {tk}"

    def test_autopilot_started_emitted_on_enable(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        events = []
        import app.session_tape as tape
        original = tape.append_event
        def capture(sid, evt, payload):
            events.append((evt, payload))
        tape.append_event = capture

        from app.ui.autopilot import enable_autopilot, finish_autopilot
        enable_autopilot(15)

        started = [e for e in events if e[0] == "autopilot_started"]
        assert len(started) == 1
        assert started[0][1]["budget_min"] == 15

        finish_autopilot("test_cleanup")
        tape.append_event = original

    def test_autopilot_step_emitted_on_completion(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        events = []
        import app.session_tape as tape
        original = tape.append_event
        def capture(sid, evt, payload):
            events.append((evt, payload))
        tape.append_event = capture

        from app.ui.autopilot import enable_autopilot, step_completed
        enable_autopilot(15)
        events.clear()

        step_completed("did-test", step_latency_ms=1234, completion_key="ck-test")
        steps = [e for e in events if e[0] == "autopilot_step"]
        assert len(steps) == 1
        assert steps[0][1]["decision_id"] == "did-test"
        assert steps[0][1]["budget_remaining_min"] == 10
        assert steps[0][1]["latency_ms"] == 1234

        tape.append_event = original

    def test_autopilot_finished_emitted(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        events = []
        import app.session_tape as tape
        original = tape.append_event
        def capture(sid, evt, payload):
            events.append((evt, payload))
        tape.append_event = capture

        from app.ui.autopilot import enable_autopilot, finish_autopilot
        enable_autopilot(5)
        events.clear()

        finish_autopilot("user_finished")
        finished = [e for e in events if e[0] == "autopilot_finished"]
        assert len(finished) == 1
        assert finished[0][1]["reason"] == "user_finished"
        assert finished[0][1]["steps_completed"] == 0

        tape.append_event = original

    def test_autopilot_paused_emitted(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        events = []
        import app.session_tape as tape
        original = tape.append_event
        def capture(sid, evt, payload):
            events.append((evt, payload))
        tape.append_event = capture

        from app.ui.autopilot import enable_autopilot, pause_autopilot
        enable_autopilot(15)
        events.clear()

        pause_autopilot()
        paused = [e for e in events if e[0] == "autopilot_paused"]
        assert len(paused) == 1
        assert paused[0][1]["reason"] == "user_paused"

        tape.append_event = original


# ── autopilot no re-execute on refresh ──────────────────────────────────────

class TestAutopilotNoReExecute:
    def test_same_completion_key_no_second_step(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed

        enable_autopilot(25)
        step_completed("did-rerender", completion_key="ck-rerender")  # 25 -> 20
        step_completed("did-rerender", completion_key="ck-rerender")  # same ck, no decrement
        assert st.session_state["_autopilot_steps_completed"] == 1
        assert st.session_state["_autopilot_budget_remaining_min"] == 20

    def test_empty_completion_key_no_dedup(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed

        enable_autopilot(15)
        step_completed("did-1", completion_key="")  # empty ck — tracked (no dedup)
        step_completed("did-1", completion_key="")  # same empty ck — also tracked
        assert st.session_state["_autopilot_steps_completed"] == 2

    def test_different_completion_keys_separate_steps(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        from app.ui.autopilot import enable_autopilot, step_completed

        enable_autopilot(15)
        step_completed("did-a", completion_key="ck-a")
        step_completed("did-b", completion_key="ck-b")
        assert st.session_state["_autopilot_steps_completed"] == 2
        assert st.session_state["_autopilot_budget_remaining_min"] == 5


# ── checkpoint integration ──────────────────────────────────────────────────

class TestAutopilotCheckpointIntegration:
    def test_store_context_calls_step_completed_on_new_completion(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.ui.autopilot import enable_autopilot
        enable_autopilot(15)

        step_calls = []
        from app.ui.autopilot import step_completed as original_sc
        def capture_sc(did="", *, step_latency_ms=0, completion_key=""):
            step_calls.append((did, completion_key))
        import app.ui.autopilot as ap
        ap.step_completed = capture_sc

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(completion_key="quiz:first", decision_id="did-first")
        assert len(step_calls) == 0, "First checkpoint (prev_ck=None) must not trigger step_completed"

        store_checkpoint_context(completion_key="quiz:second", decision_id="did-second")
        assert len(step_calls) == 1, "New completion_key must trigger step_completed"
        assert step_calls[0][0] == "did-second"
        assert step_calls[0][1] == "quiz:second"

        ap.step_completed = original_sc

    def test_store_context_no_step_on_rerender(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.ui.autopilot import enable_autopilot
        enable_autopilot(15)

        step_calls = []
        import app.ui.autopilot as ap
        original_sc = ap.step_completed
        ap.step_completed = lambda *args, **kw: step_calls.append(kw.get("completion_key", ""))

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(completion_key="quiz:first", decision_id="did-first")
        store_checkpoint_context(completion_key="quiz:second", decision_id="did-second")
        assert len(step_calls) == 1

        store_checkpoint_context(completion_key="quiz:second", decision_id="did-second")
        assert len(step_calls) == 1, "Rerender must not trigger step_completed"

        ap.step_completed = original_sc

    def test_store_context_no_step_when_autopilot_inactive(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})

        step_calls = []
        import app.ui.autopilot as ap
        original_sc = ap.step_completed
        ap.step_completed = lambda *args, **kw: step_calls.append(1)

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(completion_key="quiz:first", decision_id="did-first")
        store_checkpoint_context(completion_key="quiz:second", decision_id="did-second")
        assert len(step_calls) == 0, "No autopilot → no step_completed calls"

        ap.step_completed = original_sc

    def test_completion_key_none_transition_detects_new_step(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.ui.autopilot import enable_autopilot
        enable_autopilot(25)

        step_calls = []
        import app.ui.autopilot as ap
        original_sc = ap.step_completed
        ap.step_completed = lambda *args, **kw: step_calls.append(kw.get("completion_key", ""))

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(completion_key=None, decision_id="did-none")
        assert len(step_calls) == 0

        store_checkpoint_context(completion_key="quiz:real", decision_id="did-real")
        assert len(step_calls) == 1

        ap.step_completed = original_sc


# ── compass budget wiring ────────────────────────────────────────────────────

class TestAutopilotCompassBudget:
    def test_autopilot_budget_passed_to_compass(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn = src.split("def render_checkpoint")[1].split("\ndef ")[0]
        assert "time_budget_min=_autopilot_budget" in fn
        assert "_autopilot_budget_min_for_compass" in fn

    def test_budget_min_none_when_inactive(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.checkpoint import _autopilot_budget_min_for_compass
        assert _autopilot_budget_min_for_compass() is None

    def test_budget_min_none_when_paused(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import enable_autopilot, pause_autopilot
        enable_autopilot(15)
        pause_autopilot()
        from app.ui.checkpoint import _autopilot_budget_min_for_compass
        assert _autopilot_budget_min_for_compass() is None

    def test_budget_min_active_returns_value(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})
        from app.ui.autopilot import enable_autopilot
        enable_autopilot(25)
        from app.ui.checkpoint import _autopilot_budget_min_for_compass
        assert _autopilot_budget_min_for_compass() == 25


# ── DoD invariants ──────────────────────────────────────────────────────────

class TestAutopilotDoDInvariants:
    def test_one_primary_on_checkpoint(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn = src.split("def render_checkpoint")[1].split("\ndef ")[0]
        assert "_cap_secondaries" in fn

    def test_cap_secondaries_limits_to_two(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.smart_study_recommendation import SmartStudySecondaryAction
        from app.ui.checkpoint import _cap_secondaries

        secs = tuple(SmartStudySecondaryAction(f"a{i}", f"L{i}") for i in range(5))
        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=secs,
            decision_id="d1", phase="understand",
        )
        capped = _cap_secondaries(rec)
        assert len(capped.secondaries) == 2

    def test_write_actions_confirm_only(self) -> None:
        src = (Path("app/ui/autopilot.py")).read_text(encoding="utf-8")
        assert "save_quiz_result" not in src
        assert "save_flashcard" not in src
        assert "save_card" not in src

    def test_no_auto_quiz_start(self) -> None:
        src = (Path("app/ui/autopilot.py")).read_text(encoding="utf-8")
        assert "quiz_pending" not in src

    def test_autopilot_payload_privacy_safe(self) -> None:
        from app.session_tape import FORBIDDEN_PAYLOAD_KEYS
        text_keys = {"question", "answer", "text", "chunk", "front", "back", "body"}
        assert text_keys.issubset(FORBIDDEN_PAYLOAD_KEYS)
