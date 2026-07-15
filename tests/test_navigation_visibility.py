from app.ui.navigation_visibility import hidden_nav_views_for_level, visible_nav_views_for_level


def test_study_level_shows_learning_loop_nav_by_default() -> None:
    visible = visible_nav_views_for_level("study", {})

    assert visible == [
        "Mission Control",
        "Быстрый ответ",
        "Чат с тьютором",
        "Интерактивный Quiz",
        "Flashcards",
        "Прогресс обучения",
        "Темы",
        "Найти материалы",
        "Объяснить файл",
    ]
    assert "Метрики" in hidden_nav_views_for_level("study", {})
    assert "Курс" in hidden_nav_views_for_level("study", {})


def test_legacy_level_1_matches_study_level() -> None:
    """Old stored KV values ("1".."5", "all") must still resolve sensibly."""
    assert visible_nav_views_for_level("1", {}) == visible_nav_views_for_level("study", {})


def test_hidden_current_view_is_kept_for_deep_link() -> None:
    visible = visible_nav_views_for_level("study", {}, current_view="Метрики")

    assert visible[-1] == "Метрики"


def test_override_can_enable_single_hidden_view() -> None:
    visible = visible_nav_views_for_level("study", {"view:metrics": True})

    assert "Метрики" in visible
