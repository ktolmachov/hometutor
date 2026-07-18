"""W6 global navigation destinations and page titles."""

from __future__ import annotations

from app.ui.constants import ALL_VIEWS, HOME_VIEW
from app.ui.global_navigation import (
    DEST_HOME,
    DEST_LEARN,
    DEST_LIBRARY,
    DEST_MEMORY,
    DEST_MORE,
    PRIMARY_DESTINATION_ORDER,
    default_leaf_for_destination,
    destination_for_view,
    page_title_for_view,
    request_navigate,
    validate_navigation_contract,
    visible_leaves_for_destination,
)


def test_all_views_mapped_exactly_once() -> None:
    validate_navigation_contract()
    for view in ALL_VIEWS:
        assert destination_for_view(view) in {
            DEST_HOME,
            DEST_LEARN,
            DEST_MEMORY,
            DEST_LIBRARY,
            DEST_MORE,
        }


def test_primary_destinations_are_four() -> None:
    assert PRIMARY_DESTINATION_ORDER == (DEST_HOME, DEST_LEARN, DEST_MEMORY, DEST_LIBRARY)
    assert DEST_MORE not in PRIMARY_DESTINATION_ORDER


def test_destination_defaults() -> None:
    visible = list(ALL_VIEWS)
    assert default_leaf_for_destination(DEST_HOME, visible) == HOME_VIEW
    assert default_leaf_for_destination(DEST_LEARN, visible) == "Чат с тьютором"
    assert default_leaf_for_destination(DEST_MEMORY, visible) == "Knowledge Graph"
    assert default_leaf_for_destination(DEST_LIBRARY, visible) == "Библиотека"


def test_visible_leaves_respect_visibility() -> None:
    # Study-level-ish: no metrics, no course.
    visible = [
        HOME_VIEW,
        "Чат с тьютором",
        "Интерактивный Quiz",
        "Flashcards",
        "Knowledge Graph",
        "Библиотека",
    ]
    assert visible_leaves_for_destination(DEST_LEARN, visible) == [
        "Чат с тьютором",
        "Интерактивный Quiz",
    ]
    assert "Курс" not in visible_leaves_for_destination(DEST_LEARN, visible)
    assert default_leaf_for_destination(DEST_MORE, visible) is None


def test_page_titles_are_russian_parent_leaf() -> None:
    assert page_title_for_view(HOME_VIEW) == "Главная"
    assert "Учиться" in page_title_for_view("Интерактивный Quiz")
    assert "Память" in page_title_for_view("Flashcards")
    assert "Библиотека" in page_title_for_view("Библиотека") or page_title_for_view("Библиотека") == "Библиотека"


def test_request_navigate_writes_pending_only() -> None:
    state: dict = {"current_view": HOME_VIEW}
    request_navigate("Flashcards", state=state)
    assert state["_pending_current_view"] == "Flashcards"
    assert state["current_view"] == HOME_VIEW
