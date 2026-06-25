"""Progressive disclosure: cold user sees fewer tiles on Mission Control."""
from app.ui.mission_control import _COLD_USER_TILE_IDS, _tile_definitions


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
