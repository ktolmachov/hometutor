"""Progressive disclosure: cold user sees fewer tiles on Mission Control."""
from app.ui.mission_control import (
    _COLD_USER_TILE_IDS,
    _has_indexed_materials,
    _is_cold_user,
    _tile_definitions,
)


def test_cold_user_tile_ids_are_subset_of_all_tiles() -> None:
    all_ids = {t.tile_id for t in _tile_definitions(due_count=0)}
    assert _COLD_USER_TILE_IDS <= all_ids, (
        f"Cold-user tiles reference unknown ids: {_COLD_USER_TILE_IDS - all_ids}"
    )


def test_cold_user_sees_exactly_three_tiles() -> None:
    assert len(_COLD_USER_TILE_IDS) == 3
    assert "quick_question" in _COLD_USER_TILE_IDS
    assert "tutor" in _COLD_USER_TILE_IDS
    assert "quiz" in _COLD_USER_TILE_IDS


def test_has_indexed_materials_recognises_each_shape() -> None:
    assert _has_indexed_materials({"status": "ok"}) is True
    assert _has_indexed_materials({"nodes_count": 12}) is True
    assert _has_indexed_materials({"files": ["a.md"]}) is True
    # Empty / not-ready index is not "materials".
    assert _has_indexed_materials({"status": "empty"}) is False
    assert _has_indexed_materials({"nodes_count": 0, "files": []}) is False
    assert _has_indexed_materials({}) is False
    assert _has_indexed_materials(None) is False


def test_indexed_base_without_activity_is_not_cold() -> None:
    # Regression: a fresh user (no due cards) WITH an indexed knowledge base
    # must keep the full Mission Control, not the 3-tile cold view. The index
    # check short-circuits before any history/deck I/O.
    assert _is_cold_user(0, {"status": "ok"}) is False
    assert _is_cold_user(None, {"nodes_count": 5}) is False


def test_due_cards_alone_keep_user_warm() -> None:
    assert _is_cold_user(3, None) is False
