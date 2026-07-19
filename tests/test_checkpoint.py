"""B1 Checkpoint after each result — unit + contract tests.

No Streamlit AppTest required; session_state mocking is enough for the pure
context helpers and session-tape contract.
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
        # Smoke: append_event with checkpoint payload must not raise
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

    def test_scoped_quiz_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        assert "_render_quiz_checkpoint_if_due" in src

    def test_flashcards_review_has_checkpoint_call(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        assert "_render_flashcards_checkpoint" in src

    def test_tutor_e11_fallback_uses_checkpoint_not_inline_buttons(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        assert 'st.button("Продолжить 1 шаг"' not in src
        assert 'st.button("Готово на сегодня"' not in src

    def test_scoped_quiz_checkpoint_after_completion_panel(self) -> None:
        src = (Path("app/ui/scoped_quiz.py")).read_text(encoding="utf-8")
        feedback_idx = src.index("completion_clicked = render_stable_feedback_block")
        checkpoint_idx = src.index("_render_quiz_checkpoint_if_due")
        assert feedback_idx < checkpoint_idx

    def test_flashcards_checkpoint_after_restart_button(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        restart_idx = src.index('"🔁 Начать снова"')
        checkpoint_idx = src.index("_render_flashcards_checkpoint")
        assert restart_idx < checkpoint_idx


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
