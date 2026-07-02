from app.ui.navigation_visibility import hidden_nav_views_for_level, visible_nav_views_for_level


def test_level_1_shows_only_beginner_nav_by_default() -> None:
    visible = visible_nav_views_for_level("1", {})

    assert visible == [
        "Mission Control",
        "Быстрый ответ",
        "Найти материалы",
        "Объяснить файл",
    ]
    assert "Метрики" in hidden_nav_views_for_level("1", {})


def test_hidden_current_view_is_kept_for_deep_link() -> None:
    visible = visible_nav_views_for_level("1", {}, current_view="Метрики")

    assert visible[-1] == "Метрики"


def test_override_can_enable_single_hidden_view() -> None:
    visible = visible_nav_views_for_level("1", {"view:metrics": True})

    assert "Метрики" in visible
