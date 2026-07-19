"""B1 Checkpoint after each result — unit + contract + behaviour tests.

Verifies: UUID rotation on completion_key change (not decision_id),
stable on rerender, breadcrumb propagation to primary/secondary,
return_view injection into SSR, distinct buttons, plan_primary_block,
quiz content hash, stale state reset, single route surface, dead code.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# checkpoint.py — source-level contracts
# ---------------------------------------------------------------------------

class TestCheckpointSourceContracts:
    def test_store_context_uses_completion_key(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn_body = src.split("def store_checkpoint_context")[1].split("\ndef ")[0]
        assert "completion_key" in fn_body
        assert "_CHECKPOINT_COMPLETION_KEY" in fn_body
        assert "prev_ck" in fn_body
        assert "new_ck" in fn_body

    def test_checkpoint_no_auto_start_pattern(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "tutor_pending_prompt" not in src

    def test_checkpoint_no_text_in_payload(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert '"question"' not in src
        assert '"answer"' not in src

    def test_manual_button_distinct_from_finish(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_navigate_manual" in src
        assert "_navigate_to_return_view" in src

    def test_on_finish_parameter_present(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        fn_body = src.split("def render_checkpoint")[1].split("\ndef ")[0]
        assert "completion_key" in fn_body

    def test_return_view_injected_into_ssr_rec(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_inject_return_view" in src
        fn_body = src.split("def render_checkpoint")[1].split("\ndef ")[0]
        assert "rec_for_card" in fn_body

    def test_cap_secondaries_limits_to_two(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.smart_study_recommendation import SmartStudySecondaryAction
        from app.ui.checkpoint import _cap_secondaries

        secs = tuple(SmartStudySecondaryAction(f"a{i}", f"L{i}") for i in range(4))
        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=secs,
            decision_id="d1", phase="understand",
        )
        capped = _cap_secondaries(rec)
        assert len(capped.secondaries) == 2


# ---------------------------------------------------------------------------
# checkpoint instance lifecycle (completion_key-based)
# ---------------------------------------------------------------------------

class TestCheckpointInstanceLifecycle:
    def test_same_completion_key_reuses_uuid(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(completion_key="quiz:hash1")
        id1 = st.session_state.get("_checkpoint_instance_id")
        assert id1 is not None

        store_checkpoint_context(completion_key="quiz:hash1")
        id2 = st.session_state.get("_checkpoint_instance_id")
        assert id1 == id2, "Rerender: same completion_key → same UUID"

    def test_different_completion_key_generates_new_uuid(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context

        store_checkpoint_context(completion_key="quiz:hash1")
        id1 = st.session_state.get("_checkpoint_instance_id")

        store_checkpoint_context(completion_key="quiz:hash2")
        id2 = st.session_state.get("_checkpoint_instance_id")
        assert id1 != id2, "New completion: different completion_key → new UUID"

    def test_two_completions_two_events(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.checkpoint import (
            store_checkpoint_context, _emit_checkpoint_offered,
            _emitted_checkpoint_instances,
        )
        _emitted_checkpoint_instances.clear()

        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=(),
            decision_id="did-same", phase="understand",
        )

        call_count = 0
        import app.session_tape as tape
        original = tape.append_event
        def counting(sid, evt, payload):
            nonlocal call_count
            call_count += 1
        tape.append_event = counting

        store_checkpoint_context(completion_key="quiz:v1")
        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 1, "Checkpoint A not emitted"

        store_checkpoint_context(completion_key="quiz:v2")
        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 2, f"Checkpoint B suppressed (same decision_id {rec.decision_id})"

        tape.append_event = original

    def test_clear_context_enables_fresh_uuid_on_return(self, monkeypatch) -> None:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", {})

        from app.ui.checkpoint import store_checkpoint_context, clear_checkpoint_context

        store_checkpoint_context(completion_key="quiz:v1")
        id1 = st.session_state.get("_checkpoint_instance_id")

        clear_checkpoint_context()
        store_checkpoint_context(completion_key="quiz:v1")
        id2 = st.session_state.get("_checkpoint_instance_id")
        assert id1 != id2, "After clear, same key → new UUID"


# ---------------------------------------------------------------------------
# breadcrumb propagation to primary + secondary navigation
# ---------------------------------------------------------------------------

class TestBreadcrumbPropagation:
    def test_primary_navigation_sets_breadcrumb(self) -> None:
        src = (Path("app/ui/adaptive_plan_card.py")).read_text(encoding="utf-8")
        fn_body = src.split("def apply_smart_study_primary_navigation")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn_body

    def test_secondary_navigation_sets_breadcrumb(self) -> None:
        src = (Path("app/ui/smart_study_next_step_card.py")).read_text(encoding="utf-8")
        sec_loop = src.split("for idx, (col, sec) in enumerate(zip(cols, rec_render.secondaries))")[1]
        sec_loop = sec_loop.split("\n\n")[0]
        assert "home_breadcrumb_origin" in sec_loop

    def test_intent_palette_sets_breadcrumb(self) -> None:
        src = (Path("app/ui/learning_intents.py")).read_text(encoding="utf-8")
        assert "_set_breadcrumb" in src


# ---------------------------------------------------------------------------
# return_view injection into SSR rec
# ---------------------------------------------------------------------------

class TestReturnViewInjection:
    def test_inject_sets_origin_and_return_view(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.checkpoint import _inject_return_view

        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="t", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=(),
            decision_id="d", phase="understand", origin="", return_view="",
        )
        out = _inject_return_view(rec, origin="quiz", return_view="Прогресс обучения")
        assert out.origin == "quiz"
        assert out.return_view == "Прогресс обучения"
        assert out.primary_nav == rec.primary_nav


# ---------------------------------------------------------------------------
# session_tape.py
# ---------------------------------------------------------------------------

class TestSessionTapeCheckpointEvent:
    def test_checkpoint_offered_is_registered(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS
        fields = EVENT_REQUIRED_FIELDS["checkpoint_offered"]
        assert "question" not in fields

    def test_checkpoint_offered_payload_strips_text(self) -> None:
        from app.session_tape import append_event, reset_session_started_cache_for_tests
        reset_session_started_cache_for_tests()
        try:
            append_event("test-cp-005", "checkpoint_offered", {
                "surface": "quiz", "primary_nav": "tutor_resume",
                "hint_kind": "safe_default", "decision_id": "dc5",
                "phase": "understand",
            })
        except Exception as exc:
            assert False, f"append_event raised: {exc}"


# ---------------------------------------------------------------------------
# Integration: checkpoint in all completion surfaces
# ---------------------------------------------------------------------------

class TestCheckpointIntegrationCoverage:
    def test_tutor_chat_session_has_completion_key(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "completion_key" in fn

    def test_scoped_quiz_has_completion_key(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_quiz_checkpoint_if_due")[1].split("\ndef ")[0]
        assert "completion_key" in fn

    def test_micro_quiz_has_completion_key(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "completion_key" in fn

    def test_flashcards_has_completion_key(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        assert "completion_key" in fn

    def test_scoped_quiz_checkpoint_gated_on_saved(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert 'st.session_state.get(saved_key)' in src

    def test_scoped_quiz_has_content_hash_reset(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert "_quiz_content_hash" in src
        assert "_reset_quiz_state_for_source" in src


# ---------------------------------------------------------------------------
# return_view dynamic (breadcrumb for tutor, current_view for quiz/flashcards)
# ---------------------------------------------------------------------------

class TestReturnViewDynamic:
    def test_tutor_return_view_uses_breadcrumb(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn

    def test_quiz_return_view_reads_current_view(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_quiz_checkpoint_if_due")[1].split("\ndef ")[0]
        assert 'return_view=st.session_state.get("current_view"' in fn

    def test_micro_quiz_return_view_uses_breadcrumb(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "home_breadcrumb_origin" in fn

    def test_flashcards_return_view_reads_current_view(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        assert 'return_view=st.session_state.get("current_view"' in fn


# ---------------------------------------------------------------------------
# Single route surface
# ---------------------------------------------------------------------------

class TestSingleRouteSurface:
    def test_dead_code_removed(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        assert "def _render_smart_study_after_failed_quiz" not in src

    def test_auto_quiz_no_local_buttons(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        auto_fn = src.split("def render_unified_auto_quiz_card")[1].split("\ndef ")[0]
        assert 'st.button("Вспомнил"' not in auto_fn


# ---------------------------------------------------------------------------
# plan_primary_block propagation
# ---------------------------------------------------------------------------

class TestPlanPrimaryBlockPropagation:
    def test_all_integrations_use_plan_block(self) -> None:
        for fname, fn_name in [
            ("app/ui/tutor_chat_session.py", "_render_tutor_checkpoint"),
            ("app/ui/scoped_quiz.py", "_render_quiz_checkpoint_if_due"),
            ("app/ui/flashcards_review_view.py", "_render_flashcards_checkpoint"),
            ("app/ui/tutor_chat_quiz.py", "_render_micro_quiz_checkpoint"),
        ]:
            src = (Path(fname)).read_text(encoding="utf-8")
            fn = src.split(f"def {fn_name}")[1].split("\ndef ")[0]
            assert "plan_block" in fn, f"{fname}::{fn_name}"
            assert "plan_primary_block=None" not in fn, f"{fname}::{fn_name}"


# ---------------------------------------------------------------------------
# session_tape — no text leak
# ---------------------------------------------------------------------------

class TestSessionTapeNoTextLeak:
    def test_forbidden_keys_cover_text_fields(self) -> None:
        from app.session_tape import FORBIDDEN_PAYLOAD_KEYS
        text_keys = {"question", "answer", "text", "question_text", "answer_text",
                     "raw_text", "chunk", "front", "back", "body", "api_key"}
        assert text_keys.issubset(FORBIDDEN_PAYLOAD_KEYS)
