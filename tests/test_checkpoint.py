"""B1 Checkpoint after each result — unit + contract tests.

Verifies: deduplication, distinct buttons, fallback, plan_primary_block,
quiz-save gate, micro-quiz integration, session-tape privacy safety.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# checkpoint.py — source-level contracts (pure Python, no Streamlit)
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
        assert '"text"' not in src

    def test_checkpoint_returns_no_new_view(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "PENDING_CURRENT_VIEW_KEY" not in src.split("def store_checkpoint_context")[0]

    def test_checkpoint_has_dedupe_set(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_emitted_checkpoint_ids" in src
        assert "dedupe_key" in src

    def test_manual_button_distinct_from_finish(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_navigate_manual" in src
        assert "_navigate_to_return_view" in src
        manual_calls = src.count("_navigate_manual()")
        return_calls = src.count("_navigate_to_return_view(return_view)")
        assert manual_calls >= 1
        assert return_calls >= 1


# ---------------------------------------------------------------------------
# checkpoint context helpers (pure session_state mocking)
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
# checkpoint deduplication
# ---------------------------------------------------------------------------

class TestCheckpointDedupe:
    def test_emitted_set_is_module_level(self) -> None:
        from app.ui.checkpoint import _emitted_checkpoint_ids
        assert isinstance(_emitted_checkpoint_ids, set)

    def test_emit_checkpoint_offered_respects_dedupe(self, monkeypatch) -> None:
        """Second call with same (sid, decision_id) must not emit twice."""
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})

        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.checkpoint import _emitted_checkpoint_ids, _emit_checkpoint_offered

        rec = SmartStudyRecommendation(
            hint_kind="safe_default",
            primary_label_ru="test",
            why_now_ru="",
            primary_nav="safe_tutor_5min",
            secondaries=(),
            decision_id="dec-dedup",
            phase="understand",
        )

        _emitted_checkpoint_ids.clear()

        call_count = 0
        original_append = None
        try:
            from app import session_tape
            original_append = session_tape.append_event
        except Exception:
            pass

        def counting_append(sid, evt, payload):
            nonlocal call_count
            call_count += 1

        import app.session_tape as tape
        tape.append_event = counting_append

        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 1, f"Expected 1 emission, got {call_count}"

        _emit_checkpoint_offered(rec, "quiz")
        assert call_count == 1, f"Dedupe failed: second call also emitted (total {call_count})"

        if original_append:
            tape.append_event = original_append

    def test_emit_skips_when_no_session_id(self, monkeypatch) -> None:
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {"_session_tape_id": ""})

        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.checkpoint import _emitted_checkpoint_ids, _emit_checkpoint_offered

        rec = SmartStudyRecommendation(
            hint_kind="safe_default",
            primary_label_ru="test",
            why_now_ru="",
            primary_nav="safe_tutor_5min",
            secondaries=(),
            decision_id="dec-no-sid",
            phase="understand",
        )

        _emitted_checkpoint_ids.clear()
        _emit_checkpoint_offered(rec, "quiz")


# ---------------------------------------------------------------------------
# session_tape.py — checkpoint_offered contract
# ---------------------------------------------------------------------------

class TestSessionTapeCheckpointEvent:
    def test_checkpoint_offered_is_registered(self) -> None:
        from app.session_tape import EVENT_REQUIRED_FIELDS

        assert "checkpoint_offered" in EVENT_REQUIRED_FIELDS
        fields = EVENT_REQUIRED_FIELDS["checkpoint_offered"]
        assert "surface" in fields
        assert "primary_nav" in fields
        assert "hint_kind" in fields
        assert "decision_id" in fields
        assert "phase" in fields
        assert "question" not in fields
        assert "answer" not in fields
        assert "text" not in fields

    def test_checkpoint_offered_payload_strips_text(self) -> None:
        from app.session_tape import append_event, FORBIDDEN_PAYLOAD_KEYS, reset_session_started_cache_for_tests

        assert "question" in FORBIDDEN_PAYLOAD_KEYS
        assert "text" in FORBIDDEN_PAYLOAD_KEYS
        assert "answer" in FORBIDDEN_PAYLOAD_KEYS
        reset_session_started_cache_for_tests()
        try:
            append_event(
                "test-checkpoint-001",
                "checkpoint_offered",
                {
                    "surface": "quiz",
                    "primary_nav": "tutor_resume",
                    "hint_kind": "safe_default",
                    "decision_id": "dec-check-1",
                    "phase": "understand",
                },
            )
        except Exception as exc:
            assert False, f"append_event raised: {exc}"


# ---------------------------------------------------------------------------
# Integration coverage: checkpoint presence in completion surfaces
# ---------------------------------------------------------------------------

class TestCheckpointIntegrationCoverage:
    def test_tutor_chat_session_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert "_render_tutor_checkpoint" in src
        assert "render_checkpoint(" in src

    def test_scoped_quiz_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert "_render_quiz_checkpoint_if_due" in src

    def test_flashcards_review_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        assert "_render_flashcards_checkpoint" in src

    def test_tutor_chat_quiz_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        assert "_render_micro_quiz_checkpoint" in src

    def test_tutor_e11_fallback_uses_unified_checkpoint(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert "render_checkpoint(" in src

    def test_tutor_has_fallback_buttons(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert "_render_fallback_buttons" in src
        assert '"Продолжить 1 шаг"' in src
        assert '"Готово на сегодня"' in src

    def test_scoped_quiz_checkpoint_after_save(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        save_idx = src.index("quiz_saved")
        checkpoint_idx = src.index("_render_quiz_checkpoint_if_due")
        assert save_idx < checkpoint_idx

    def test_scoped_quiz_checkpoint_gated_on_saved(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert 'st.session_state.get(saved_key)' in src

    def test_flashcards_checkpoint_after_restart_button(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        restart_idx = src.index('"🔁 Начать снова"')
        checkpoint_idx = src.index("_render_flashcards_checkpoint")
        assert restart_idx < checkpoint_idx


# ---------------------------------------------------------------------------
# plan_primary_block propagation
# ---------------------------------------------------------------------------

class TestPlanPrimaryBlockPropagation:
    def test_tutor_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        chkpt_fn = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in chkpt_fn
        assert "plan_primary_block=None" not in chkpt_fn

    def test_quiz_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        chkpt_fn = src.split("def _render_quiz_checkpoint_if_due")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in chkpt_fn
        assert "plan_primary_block=None" not in chkpt_fn

    def test_flashcards_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        chkpt_fn = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in chkpt_fn
        assert "plan_primary_block=None" not in chkpt_fn

    def test_micro_quiz_checkpoint_not_hardcode_none_plan(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        chkpt_fn = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "_get_saved_plan_primary_block" in chkpt_fn
        assert "plan_primary_block=None" not in chkpt_fn


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
