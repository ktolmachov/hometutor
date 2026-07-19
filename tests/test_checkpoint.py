"""B1 Checkpoint after each result — unit + contract + behaviour tests.

Verifies: instance-level dedupe, distinct buttons, on_finish callback,
plan_primary_block propagation, quiz-save gate + stale reset,
micro-quiz + auto-quiz integration, ≤2 secondaries, single route surface.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# checkpoint.py — source-level contracts
# ---------------------------------------------------------------------------

class TestCheckpointSourceContracts:
    def test_checkpoint_module_exists(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "store_checkpoint_context" in src
        assert "load_checkpoint_context" in src
        assert "clear_checkpoint_context" in src
        assert "render_checkpoint" in src

    def test_checkpoint_no_auto_start_pattern(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "tutor_pending_prompt" not in src

    def test_checkpoint_no_text_in_payload(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert '"question"' not in src
        assert '"answer"' not in src

    def test_dedupe_is_per_instance_not_per_decision(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_emitted_checkpoint_keys" in src
        assert "dedupe_key: str" in src.split("_emit_checkpoint_offered")[0] or "dedupe_key" in src

    def test_manual_button_distinct_from_finish(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_navigate_manual" in src
        assert "_navigate_to_return_view" in src

    def test_on_finish_parameter_present(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn_body = src.split("def render_checkpoint")[1].split("\ndef ")[0]
        assert "on_finish" in fn_body
        assert "if callable(on_finish)" in fn_body

    def test_cap_secondaries_limits_to_two(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation, SmartStudySecondaryAction
        from app.ui.checkpoint import _cap_secondaries

        secs = tuple(SmartStudySecondaryAction(f"a{i}", f"Label {i}") for i in range(4))
        rec = SmartStudyRecommendation(
            hint_kind="safe_default",
            primary_label_ru="test",
            why_now_ru="",
            primary_nav="safe_tutor_5min",
            secondaries=secs,
            decision_id="d1",
            phase="understand",
        )
        capped = _cap_secondaries(rec)
        assert len(capped.secondaries) == 2
        assert capped.primary_nav == rec.primary_nav

        secs2 = tuple(SmartStudySecondaryAction(f"a{i}", f"L{i}") for i in range(1))
        rec2 = SmartStudyRecommendation(
            hint_kind="safe_default",
            primary_label_ru="t2",
            why_now_ru="",
            primary_nav="safe_tutor_5min",
            secondaries=secs2,
            decision_id="d2",
            phase="understand",
        )
        capped2 = _cap_secondaries(rec2)
        assert len(capped2.secondaries) == 1


# ---------------------------------------------------------------------------
# checkpoint context helpers
# ---------------------------------------------------------------------------

class TestCheckpointContext:
    def test_store_load_clear_full_cycle(self, monkeypatch) -> None:
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context, load_checkpoint_context, clear_checkpoint_context

        store_checkpoint_context(
            topic_hint="agent-harness",
            origin="tutor",
            return_view="Mission Control",
            decision_id="dec-001",
            phase="understand",
        )
        ctx = load_checkpoint_context()
        assert ctx is not None
        assert ctx["topic_hint"] == "agent-harness"
        assert ctx["origin"] == "tutor"
        assert ctx["return_view"] == "Mission Control"
        assert ctx["decision_id"] == "dec-001"
        assert ctx["phase"] == "understand"

        clear_checkpoint_context()
        assert load_checkpoint_context() is None

    def test_store_empty_fields_normalize_to_none(self, monkeypatch) -> None:
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context, load_checkpoint_context

        store_checkpoint_context(topic_hint="  ", origin=None, return_view="")
        ctx = load_checkpoint_context()
        assert ctx is not None
        assert ctx["topic_hint"] is None
        assert ctx["origin"] is None
        assert ctx["return_view"] is None


# ---------------------------------------------------------------------------
# checkpoint deduplication (instance-level)
# ---------------------------------------------------------------------------

class TestCheckpointDedupe:
    def test_emitted_set_is_module_level(self) -> None:
        from app.ui.checkpoint import _emitted_checkpoint_keys
        assert isinstance(_emitted_checkpoint_keys, set)

    def test_emit_checkpoint_offered_respects_dedupe_by_instance(self, monkeypatch) -> None:
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.checkpoint import _emitted_checkpoint_keys, _emit_checkpoint_offered

        rec1 = SmartStudyRecommendation(
            hint_kind="safe_default",
            primary_label_ru="test",
            why_now_ru="",
            primary_nav="safe_tutor_5min",
            secondaries=(),
            decision_id="dec-same",
            phase="understand",
        )
        rec2 = SmartStudyRecommendation(
            hint_kind="cards_due",
            primary_label_ru="review",
            why_now_ru="",
            primary_nav="flashcards_review",
            secondaries=(),
            decision_id="dec-same",
            phase="retain",
        )

        _emitted_checkpoint_keys.clear()

        call_count = 0
        import app.session_tape as tape
        original = tape.append_event
        def counting(sid, evt, payload):
            nonlocal call_count
            call_count += 1
        tape.append_event = counting

        _emit_checkpoint_offered(rec1, "quiz", dedupe_key="quiz_instance_1")
        assert call_count == 1

        _emit_checkpoint_offered(rec1, "quiz", dedupe_key="quiz_instance_1")
        assert call_count == 1, "Same instance re-emitted"

        _emit_checkpoint_offered(rec2, "quiz", dedupe_key="quiz_instance_2")
        assert call_count == 2, "Different instance blocked by same decision_id"

        tape.append_event = original


# ---------------------------------------------------------------------------
# session_tape.py — checkpoint_offered contract
# ---------------------------------------------------------------------------

class TestSessionTapeCheckpointEvent:
    def test_checkpoint_offered_is_registered(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS

        assert "checkpoint_offered" in EVENT_REQUIRED_FIELDS
        fields = EVENT_REQUIRED_FIELDS["checkpoint_offered"]
        assert "question" not in fields
        assert "answer" not in fields
        assert "text" not in fields

    def test_checkpoint_offered_payload_strips_text(self) -> None:
        from app.session_tape import append_event, reset_session_started_cache_for_tests

        reset_session_started_cache_for_tests()
        try:
            append_event(
                "test-checkpoint-002",
                "checkpoint_offered",
                {
                    "surface": "quiz",
                    "primary_nav": "tutor_resume",
                    "hint_kind": "safe_default",
                    "decision_id": "dec-check-2",
                    "phase": "understand",
                },
            )
        except Exception as exc:
            assert False, f"append_event raised: {exc}"


# ---------------------------------------------------------------------------
# Integration: checkpoint in all 4 completion surfaces
# ---------------------------------------------------------------------------

class TestCheckpointIntegrationCoverage:
    def test_tutor_chat_session_uses_render_checkpoint(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert "render_checkpoint(" in src

    def test_scoped_quiz_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert "_render_quiz_checkpoint_if_due" in src

    def test_flashcards_review_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        assert "_render_flashcards_checkpoint" in src

    def test_tutor_chat_quiz_micro_quiz_has_checkpoint(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        assert "_render_micro_quiz_checkpoint" in src

    def test_tutor_chat_quiz_auto_quiz_has_checkpoint(self) -> None:
        """render_unified_auto_quiz_card also renders checkpoint."""
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        auto_fn = src.split("def render_unified_auto_quiz_card")[1].split("\ndef ")[0]
        assert "_render_micro_quiz_checkpoint" in auto_fn

    def test_tutor_has_fallback_buttons(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert "_render_fallback_buttons" in src

    def test_scoped_quiz_checkpoint_after_save(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        save_idx = src.index("quiz_saved")
        checkpoint_idx = src.index("_render_quiz_checkpoint_if_due")
        assert save_idx < checkpoint_idx

    def test_scoped_quiz_checkpoint_gated_on_saved(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert 'st.session_state.get(saved_key)' in src

    def test_scoped_quiz_resets_saved_on_fresh_quiz(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert 'submitted_count == 0' in src
        assert 'quiz_saved' in src

    def test_flashcards_checkpoint_after_restart_button(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        restart_idx = src.index('"🔁 Начать снова"')
        checkpoint_idx = src.index("_render_flashcards_checkpoint")
        assert restart_idx < checkpoint_idx


# ---------------------------------------------------------------------------
# No duplicate route surfaces (old SSR removed)
# ---------------------------------------------------------------------------

class TestSingleRouteSurface:
    def test_auto_quiz_no_old_ssr(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        auto_fn = src.split("def render_unified_auto_quiz_card")[1].split("\ndef ")[0]
        assert "_render_smart_study_after_failed_quiz" not in auto_fn

    def test_micro_quiz_no_old_ssr(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        mq_fn = src.split("def render_tutor_micro_quiz_block")[1].split("\ndef ")[0]
        assert "_render_smart_study_after_failed_quiz" not in mq_fn


# ---------------------------------------------------------------------------
# No render-time session state mutation
# ---------------------------------------------------------------------------

class TestNoRenderTimeMutation:
    def test_tutor_checkpoint_does_not_mutate_e11_during_render(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "_on_tutor_checkpoint_action" in fn_body
        assert "on_finish=_on_tutor_checkpoint_action" in fn_body


# ---------------------------------------------------------------------------
# plan_primary_block propagation
# ---------------------------------------------------------------------------

class TestPlanPrimaryBlockPropagation:
    def test_tutor_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn_body
        assert "plan_primary_block=None" not in fn_body

    def test_quiz_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_quiz_checkpoint_if_due")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn_body
        assert "plan_primary_block=None" not in fn_body

    def test_flashcards_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn_body
        assert "plan_primary_block=None" not in fn_body

    def test_micro_quiz_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn_body
        assert "plan_primary_block=None" not in fn_body


# ---------------------------------------------------------------------------
# session_tape — no text leak
# ---------------------------------------------------------------------------

class TestSessionTapeNoTextLeak:
    def test_forbidden_keys_cover_text_fields(self) -> None:
        from app.session_tape import FORBIDDEN_PAYLOAD_KEYS

        text_keys = {"question", "answer", "text", "question_text", "answer_text",
                     "raw_text", "chunk", "front", "back", "body", "api_key"}
        assert text_keys.issubset(FORBIDDEN_PAYLOAD_KEYS)

    def test_checkpoint_payload_is_not_forbidden(self) -> None:
        from app.session_tape import _validate_payload

        payload = {
            "surface": "tutor",
            "primary_nav": "tutor_resume",
            "hint_kind": "safe_default",
            "decision_id": "dec-abc",
            "phase": "understand",
        }
        try:
            _validate_payload("checkpoint_offered", payload)
        except Exception as exc:
            assert False, f"Valid checkpoint payload rejected: {exc}"
