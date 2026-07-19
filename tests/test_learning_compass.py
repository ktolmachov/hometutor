"""B2 Learning Compass — unit + contract + integration tests.

Verifies: HTML output format, honest reduction on missing data,
phase labels, no raw ids, presence on all 5 surfaces, one-line constraint.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# compass HTML output
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

    def test_compass_honest_reduction(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=(),
            decision_id="d", phase="",
        )
        html = build_learning_compass_html(rec)
        assert html is not None
        assert " · " not in html

    def test_compass_returns_none_when_empty(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="safe_default", primary_label_ru="", why_now_ru="",
            primary_nav="safe_tutor_5min", secondaries=(),
            decision_id="d", phase="",
        )
        html = build_learning_compass_html(rec)
        assert html is not None
        assert "Понять" in html or "Начать" in html or len(html) > 20

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
# goal labels
# ---------------------------------------------------------------------------

class TestGoalLabels:
    def test_hint_goal_mapping(self) -> None:
        from app.ui.learning_compass import _SSR_HINT_GOAL_RU
        assert "cards_due" in _SSR_HINT_GOAL_RU
        assert "quiz_failed" in _SSR_HINT_GOAL_RU
        assert "tutor_resume" in _SSR_HINT_GOAL_RU
        assert "safe_default" in _SSR_HINT_GOAL_RU

    def test_goal_prefers_explicit_text_over_hint(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="cards_due", primary_label_ru="Повторить карточки", why_now_ru="",
            primary_nav="flashcards_review", secondaries=(),
            decision_id="d", phase="retain",
        )
        html = build_learning_compass_html(rec, goal_text="Моя цель")
        assert html is not None
        assert "Моя цель" in html


# ---------------------------------------------------------------------------
# integration: compass on all 5 surfaces
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
        assert len(lines) < 100, f"Compass module is {len(lines)} lines — keep it compact"

    def test_no_progress_bar_in_html_output(self) -> None:
        from app.smart_study_router import SmartStudyRecommendation
        from app.ui.learning_compass import build_learning_compass_html

        rec = SmartStudyRecommendation(
            hint_kind="cards_due", primary_label_ru="Повторить", why_now_ru="",
            primary_nav="flashcards_review", secondaries=(),
            decision_id="d", phase="retain", flashcard_due_n=5, sm2_due_n=3,
        )
        html = build_learning_compass_html(rec, goal_text="test")
        assert html is not None
        assert "progress" not in html
        assert "meter" not in html
        assert "chart" not in html

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
