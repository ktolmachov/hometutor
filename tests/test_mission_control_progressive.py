"""Progressive disclosure: cold user sees fewer tiles on Mission Control."""
from app.ui.mission_control import (
    _COLD_USER_TILE_IDS,
    _has_indexed_materials,
    _is_cold_user,
    _tile_definitions,
    _tile_rows_for_grid,
    build_context_row_segments,
)
from app.smart_study_router import build_smart_study_recommendation, smart_study_due_total


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


def test_full_mission_control_does_not_duplicate_knowledge_graph_tile() -> None:
    tiles = {tile.tile_id: tile for tile in _tile_definitions(due_count=0)}

    assert "knowledge_graph" not in tiles


def test_tile_rows_keep_all_tiles() -> None:
    tiles = _tile_definitions(due_count=0)
    rows = _tile_rows_for_grid(tiles)
    flattened = tuple(tile for row in rows for tile in row)

    assert flattened == tiles
    assert [len(row) for row in rows] == [4, 4]


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


def test_smart_study_due_total_is_sum_of_two_explicit_queues() -> None:
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=3,
        sm2_due_n=2,
    )

    assert rec.flashcard_due_n == 3
    assert rec.sm2_due_n == 2
    assert smart_study_due_total(rec) == 5


def test_context_row_segments_combine_course_and_xp() -> None:
    segments = build_context_row_segments(
        scope={"title": "Курс: ИИ", "folder_rel": "ai-agents"},
        snapshot={
            "daily_streak": 4,
            "level_title": "Исследователь",
            "level": 2,
            "total_xp": 1200,
            "xp_in_level": 200,
            "xp_for_level_span": 1000,
        },
    )
    assert len(segments) == 2
    assert "Курс: ИИ" in segments[0]
    assert "Стрик 4" in segments[1]
    assert "Исследователь" in segments[1]
    assert "XP 1200 (200/1000)" in segments[1]


def test_context_row_segments_degrade_when_missing() -> None:
    assert build_context_row_segments(scope=None, snapshot=None) == []
    # active course present, gamification missing → only the course segment
    only_course = build_context_row_segments(scope={"folder_rel": "ai-agents"}, snapshot=None)
    assert len(only_course) == 1
    assert "ai-agents" in only_course[0]
    # no course, gamification present → only the xp/streak segment
    only_xp = build_context_row_segments(scope=None, snapshot={"daily_streak": 1})
    assert len(only_xp) == 1
    assert "Стрик 1" in only_xp[0]


def test_non_cold_hero_cards_at_most_two() -> None:
    """A2 DoD: at most two resume cards above «Ещё режимы» for non-cold users."""
    from app.ui.mission_control import _NON_COLD_HERO_CARDS

    assert len(_NON_COLD_HERO_CARDS) <= 2


def test_non_cold_hero_cards_are_kg_and_living_konspekt() -> None:
    """Pin which cards render above the fold so a future card can't sneak in silently."""
    from app.ui.mission_control import (
        _NON_COLD_HERO_CARDS,
        render_kg_mission_card,
        render_living_konspekt_mission_card,
    )

    assert set(_NON_COLD_HERO_CARDS) == {
        render_kg_mission_card,
        render_living_konspekt_mission_card,
    }
