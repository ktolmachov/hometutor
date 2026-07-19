"""Targeted tests for analytics_service: empty-state behaviour and data honesty.

Verifies that ``build_forgetting_curve_points`` does not return synthetic
data when the SM-2 table is empty, and that ``get_advanced_analytics``
correctly reports ``total_quiz_results`` / ``scoped_quiz_results`` /
``has_quiz_data``.
"""

from __future__ import annotations

from app.analytics_service import build_forgetting_curve_points, get_advanced_analytics


class TestForgettingCurveNoSynthetic:
    def test_empty_sm2_returns_empty_list(self) -> None:
        points = build_forgetting_curve_points()
        assert points == [], (
            "build_forgetting_curve_points must return [] when spaced_repetition "
            "table is empty — no synthetic decay curve"
        )


class TestAdvancedAnalyticsEmpty:
    def test_has_quiz_data_false_when_empty(self) -> None:
        data = get_advanced_analytics()
        assert data["has_quiz_data"] is False
        assert data["forgetting_curve"] == []

    def test_total_and_scoped_zero_when_empty(self) -> None:
        data = get_advanced_analytics()
        assert data["total_quiz_results"] == 0
        assert data["scoped_quiz_results"] == 0

    def test_quiz_attempts_today_zero_when_empty(self) -> None:
        data = get_advanced_analytics()
        assert data["quiz_attempts_today"] == 0

    def test_gamification_still_present_on_empty_quiz(self) -> None:
        data = get_advanced_analytics()
        assert "gamification" in data
        assert isinstance(data["gamification"], dict)

    def test_heatmap_empty_when_no_data(self) -> None:
        data = get_advanced_analytics()
        hm = data["heatmap"]
        assert hm["z"] == []
        assert hm["x"] == []
        assert hm["y"] == []


class TestAdvancedAnalyticsGhostRows:
    """When quiz_results has rows, total_quiz_results reflects raw count
    and scoped_quiz_results reflects KG-filtered count."""

    def test_counts_reflect_seeded_data(self) -> None:
        import sqlite3

        from app.user_state_db import _resolve_state_db_path

        db_path = _resolve_state_db_path()
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO quiz_results (concept, level, score, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("concept_a", "beginner", 0.75, "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO quiz_results (concept, level, score, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("concept_a", "intermediate", 0.60, "2026-01-02T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()

        data = get_advanced_analytics()
        assert data["total_quiz_results"] == 2, (
            "total_quiz_results must reflect raw COUNT(*) from quiz_results"
        )
        assert data["scoped_quiz_results"] == 2, (
            "scoped_quiz_results must match total in absence of KG filter "
            "(empty active KG → no filtering)"
        )
        assert data["has_quiz_data"] is True, (
            "has_quiz_data must be True when scoped rows > 0"
        )
