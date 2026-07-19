"""B1 Checkpoint after each result — unit + contract + behaviour tests.

Verifies: instance-level dedupe (UUID), distinct buttons, on_finish callback,
plan_primary_block propagation, quiz content-hash key, stale reset,
micro-quiz + auto-quiz integration, ≤2 secondaries, single route surface,
dead code removal, return_view is dynamic.
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
        assert "render_checkpoint" in src

    def test_checkpoint_no_auto_start_pattern(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "tutor_pending_prompt" not in src

    def test_checkpoint_no_text_in_payload(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert '"question"' not in src
        assert '"answer"' not in src

    def test_dedupe_uses_stable_instance_uuid(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_emitted_checkpoint_instances" in src
        assert "_CHECKPOINT_INSTANCE_KEY" in src
        fn_body = src.split("def store_checkpoint_context")[1].split("\ndef ")[0]
        assert 'if not instance_id:' in fn_body
        assert "uuid.uuid4()" in fn_body

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

        secs = tuple(SmartStudySecondaryAction(f"a{i}", f"L{i}") for i in range(4))
        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=secs,
            decision_id="d1", phase="understand",
        )
        capped = _cap_secondaries(rec)
        assert len(capped.secondaries) == 2

        secs2 = tuple(SmartStudySecondaryAction(f"a{i}", f"L{i}") for i in range(1))
        rec2 = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=secs2,
            decision_id="d2", phase="understand",
        )
        capped2 = _cap_secondaries(rec2)
        assert len(capped2.secondaries) == 1


# ---------------------------------------------------------------------------
# checkpoint context + instance UUID
# ---------------------------------------------------------------------------

class TestCheckpointContext:
    def test_store_context_reuses_uuid_on_rerender(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(topic_hint="x")
        id1 = st.session_state.get("_checkpoint_instance_id")
        assert id1 is not None

        store_checkpoint_context(topic_hint="y")
        id2 = st.session_state.get("_checkpoint_instance_id")
        assert id1 == id2, "UUID must be stable across rerenders (not fresh each call)"

    def test_store_load_clear_full_cycle(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context, load_checkpoint_context, clear_checkpoint_context

        store_checkpoint_context(topic_hint="agent-harness", origin="tutor",
                                return_view="Mission Control", decision_id="dec-001",
                                phase="understand")
        ctx = load_checkpoint_context()
        assert ctx is not None
        assert ctx["topic_hint"] == "agent-harness"
        clear_checkpoint_context()
        assert load_checkpoint_context() is None


# ---------------------------------------------------------------------------
# checkpoint deduplication (instance UUID)
# ---------------------------------------------------------------------------

class TestCheckpointDedupe:
    def test_two_uuid_give_two_events(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.checkpoint import _emitted_checkpoint_instances, _emit_checkpoint_offered

        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=(),
            decision_id="dec-s", phase="understand",
        )
        _emitted_checkpoint_instances.clear()

        call_count = 0
        import app.session_tape as tape
        original = tape.append_event
        def counting(sid, evt, payload):
            nonlocal call_count
            call_count += 1
        tape.append_event = counting

        st.session_state["_checkpoint_instance_id"] = "inst-aaa"
        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 1

        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 1, "Same UUID re-emitted"

        st.session_state["_checkpoint_instance_id"] = "inst-bbb"
        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 2, "Different UUID blocked"

        tape.append_event = original


# ---------------------------------------------------------------------------
# session_tape.py — checkpoint_offered contract
# ---------------------------------------------------------------------------

class TestSessionTapeCheckpointEvent:
    def test_checkpoint_offered_is_registered(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS
        fields = EVENT_REQUIRED_FIELDS["checkpoint_offered"]
        assert "question" not in fields
        assert "answer" not in fields

    def test_checkpoint_offered_payload_strips_text(self) -> None:
        from app.session_tape import append_event, reset_session_started_cache_for_tests
        reset_session_started_cache_for_tests()
        try:
            append_event("test-cp-003", "checkpoint_offered", {
                "surface": "quiz", "primary_nav": "tutor_resume",
                "hint_kind": "safe_default", "decision_id": "dc3",
                "phase": "understand",
            })
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

    def test_auto_quiz_has_checkpoint(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        auto_fn = src.split("def render_unified_auto_quiz_card")[1].split("\ndef ")[0]
        assert "_render_micro_quiz_checkpoint" in auto_fn

    def test_tutor_has_fallback_buttons(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert "_render_fallback_buttons" in src

    def test_scoped_quiz_checkpoint_after_save(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        save_idx = src.index("quiz_hash")
        checkpoint_idx = src.index("_render_quiz_checkpoint_if_due")
        assert save_idx < checkpoint_idx

    def test_scoped_quiz_checkpoint_gated_on_saved(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert 'st.session_state.get(saved_key)' in src

    def test_scoped_quiz_uses_content_hash(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert "quiz_hash" in src
        assert "hashlib.md5" in src

    def test_flashcards_checkpoint_after_restart_button(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        restart_idx = src.index('"🔁 Начать снова"')
        checkpoint_idx = src.index("_render_flashcards_checkpoint")
        assert restart_idx < checkpoint_idx


# ---------------------------------------------------------------------------
# return_view is dynamic (reads current_view from session_state)
# ---------------------------------------------------------------------------

class TestReturnViewDynamic:
    def test_tutor_return_view_uses_breadcrumb(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn_body

    def test_quiz_return_view_reads_current_view(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_quiz_checkpoint_if_due")[1].split("\ndef ")[0]
        assert 'return_view=st.session_state.get("current_view"' in fn_body

    def test_micro_quiz_return_view_uses_breadcrumb(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn_body

    def test_flashcards_return_view_reads_current_view(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        assert 'return_view=st.session_state.get("current_view"' in fn_body


# ---------------------------------------------------------------------------
# No duplicate route surfaces (old SSR + auto-quiz buttons removed)
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

    def test_auto_quiz_no_local_buttons(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        auto_fn = src.split("def render_unified_auto_quiz_card")[1].split("\ndef ")[0]
        assert 'st.button("Вспомнил"' not in auto_fn
        assert 'st.button("Понял"' not in auto_fn
        assert 'st.button("Трудно"' not in auto_fn

    def test_dead_code_removed(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        assert "def _render_smart_study_after_failed_quiz" not in src


# ---------------------------------------------------------------------------
# Quiz content hash — state reset on new quiz
# ---------------------------------------------------------------------------

class TestQuizContentHash:
    def test_scoped_quiz_has_content_hash_reset(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert "_quiz_content_hash" in src
        assert "_reset_quiz_state_for_source" in src

    def test_reset_clears_results_and_answers(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _reset_quiz_state_for_source")[1].split("\ndef ")[0]
        assert "_result_" in fn_body
        assert "_scoped_" in fn_body
        assert "completion_metric_emitted" in fn_body


# ---------------------------------------------------------------------------
# Tutor breadcrumb for return_view
# ---------------------------------------------------------------------------

class TestTutorBreadcrumb:
    def test_tutor_uses_home_breadcrumb_origin(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn_body

    def test_micro_quiz_uses_home_breadcrumb_origin(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn_body = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn_body


# ---------------------------------------------------------------------------
# plan_primary_block propagation
# ---------------------------------------------------------------------------

class TestPlanPrimaryBlockPropagation:
    def test_tutor_not_hardcode_none(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn
        assert "plan_primary_block=None" not in fn

    def test_quiz_not_hardcode_none(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_quiz_checkpoint_if_due")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn
        assert "plan_primary_block=None" not in fn

    def test_flashcards_not_hardcode_none(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn
        assert "plan_primary_block=None" not in fn

    def test_micro_quiz_not_hardcode_none(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in fn
        assert "plan_primary_block=None" not in fn


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
        try:
            _validate_payload("checkpoint_offered", {
                "surface": "tutor", "primary_nav": "tutor_resume",
                "hint_kind": "safe_default", "decision_id": "d", "phase": "understand",
            })
        except Exception as exc:
            assert False, f"Rejected: {exc}"
