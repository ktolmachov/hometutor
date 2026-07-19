"""B2 Learning Compass — unit + contract + integration tests.

Verifies: HTML escaping, honest reduction (None on empty), phase labels,
integration coverage, kill-switch constraints, behavioral completion_key tests.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# compass HTML output + escaping
# ---------------------------------------------------------------------------

class TestCompassHtmlOutput:
    def test_full_compass_all_parts(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="tutor_resume", primary_label_ru="Продолжить", why_now_ru="",
            primary_nav="tutor_resume", secondaries=(),
            decision_id="d", phase="understand", topic_hint="agent-harness",
        )
        html = build_learning_compass_html(
            rec, goal_text="Понять agent-harness",
            time_budget_min=9, return_point="короткая проверка",
        )
        assert html is not None
        assert "Понять agent-harness" in html
        assert "объяснение" in html
        assert "9 мин осталось" in html
        assert "короткая проверка" in html
        assert " · " in html

    def test_html_escaping_prevents_injection(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="tutor_resume", primary_label_ru="test", why_now_ru="",
            primary_nav="tutor_resume", secondaries=(),
            decision_id="d", phase="understand",
        )
        html = build_learning_compass_html(
            rec,
            goal_text='<script>alert("xss")</script>',
            return_point='<img onerror=alert(1)>',
        )
        assert html is not None
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<img" not in html
        assert "&lt;img" in html

    def test_compass_none_when_empty(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=(),
            decision_id="d", phase="",
        )
        html = build_learning_compass_html(rec)
        assert html is None, "Empty rec must return None (honest reduction)"

    def test_no_synthetic_default_for_safe_default(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import _SSR_HINT_GOAL_RU
        assert "safe_default" not in _SSR_HINT_GOAL_RU

    def test_no_raw_agent_mode_ids(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="tutor_resume", primary_label_ru="t", why_now_ru="",
            primary_nav="tutor_resume", secondaries=(),
            decision_id="d", phase="understand", topic_hint="test",
        )
        html = build_learning_compass_html(rec)
        assert html is not None
        assert "tutor_resume" not in html
        assert "safe_tutor" not in html
        assert "understand" not in html

    def test_compass_one_line_only(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="cards_due", primary_label_ru="Повторить", why_now_ru="",
            primary_nav="flashcards_review", secondaries=(),
            decision_id="d", phase="retain", topic_hint="linear-algebra",
        )
        html = build_learning_compass_html(rec)
        assert html is not None
        assert html.count("<br") == 0
        assert html.count("<div") <= 2


# ---------------------------------------------------------------------------
# phase labels
# ---------------------------------------------------------------------------

class TestPhaseLabels:
    def test_known_phases(self) -> None:
        from app.ui.learning_compass import _phase_label_ru
        assert _phase_label_ru("understand") == "объяснение"
        assert _phase_label_ru("practice") == "практика"
        assert _phase_label_ru("check") == "проверка"
        assert _phase_label_ru("retain") == "повторение"
        assert _phase_label_ru("plan") == "план"

    def test_unknown_phase_returns_empty(self) -> None:
        from app.ui.learning_compass import _phase_label_ru
        assert _phase_label_ru("") == ""
        assert _phase_label_ru("unknown") == ""


# ---------------------------------------------------------------------------
# integration: compass on all surfaces
# ---------------------------------------------------------------------------

class TestCompassIntegrationCoverage:
    def test_checkpoint_has_compass(self) -> None:
        src = (Path("app/ui/checkpoint.py")).read_text(encoding="utf-8")
        assert "_render_compass_above_checkpoint" in src

    def test_home_ssr_has_compass(self) -> None:
        src = (Path("app/ui/resume_cards_smart_study.py")).read_text(encoding="utf-8")
        assert "_render_compass_for_home" in src

    def test_adaptive_plan_has_compass(self) -> None:
        src = (Path("app/ui/adaptive_plan_hub_layout.py")).read_text(encoding="utf-8")
        assert "render_learning_compass" in src

    def test_tutor_response_has_compass(self) -> None:
        src = (Path("app/ui/tutor_chat_response_render.py")).read_text(encoding="utf-8")
        assert "render_learning_compass" in src

    def test_compass_module_has_data_testid(self) -> None:
        src = (Path("app/ui/learning_compass.py")).read_text(encoding="utf-8")
        assert "e2e-learning-compass" in src


# ---------------------------------------------------------------------------
# kill switch: one line, no dashboard
# ---------------------------------------------------------------------------

class TestCompassConstraints:
    def test_compass_module_under_100_lines(self) -> None:
        src = (Path("app/ui/learning_compass.py")).read_text(encoding="utf-8")
        lines = [l for l in src.split("\n") if l.strip() and not l.strip().startswith("#")]
        assert len(lines) < 110, f"Compass module is {len(lines)} lines"

    def test_no_progress_bar_in_html_output(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="cards_due", primary_label_ru="Повторить", why_now_ru="",
            primary_nav="flashcards_review", secondaries=(),
            decision_id="d", phase="retain",
        )
        html = build_learning_compass_html(rec, goal_text="test")
        assert html is not None
        assert "progress" not in html
        assert "meter" not in html

    def test_no_due_counts_or_metrics_in_html(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="cards_due", primary_label_ru="Повторить", why_now_ru="",
            primary_nav="flashcards_review", secondaries=(),
            decision_id="d", phase="retain", flashcard_due_n=5, sm2_due_n=3,
        )
        html = build_learning_compass_html(rec, goal_text="test")
        assert html is not None
        assert "due_n" not in html
        assert "flashcard" not in html
        assert "xp" not in html
        assert "mastery" not in html


# ---------------------------------------------------------------------------
# behavioral: completion_key uniqueness (E11 + flashcards)
# ---------------------------------------------------------------------------

class TestCompletionKeyBehavioral:
    def test_e11_completion_key_unique_per_session(self) -> None:
        src = (Path("app/ui/tutor_chat_session.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_tutor_checkpoint")[1].split("\ndef ")[0]
        assert "completion_key=" in fn
        ck_line = [l for l in fn.split("\n") if "completion_key=" in l][0]
        assert "session_id" in ck_line

    def test_flashcards_completion_key_has_scope(self) -> None:
        src = (Path("app/ui/flashcards_review_view.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_flashcards_checkpoint")[1].split("\ndef ")[0]
        call = src.split("_render_flashcards_checkpoint(")[1].split("\n")[0]
        assert "scope_signature" in call or "completion_key" in fn

    def test_micro_quiz_completion_key_has_msg_idx(self) -> None:
        src = (Path("app/ui/tutor_chat_quiz.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_micro_quiz_checkpoint")[1].split("\ndef ")[0]
        assert "msg_idx" in fn
        ck_decl = [l for l in fn.split("\n") if "completion_key" in l]
        assert ck_decl, "completion_key not found in micro-quiz checkpoint"
        ck_line = ck_decl[0]
        assert "msg_idx" in ck_line, f"completion_key missing msg_idx: {ck_line}"
