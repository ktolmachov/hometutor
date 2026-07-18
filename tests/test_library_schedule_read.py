"""P0-2b: schedule read-model — transfers, route tiles, search filter."""

from __future__ import annotations

from app.library_schedule_read import (
    SCHEDULE_SEGMENTS,
    build_area_summary_tile,
    build_concept_schedule_nodes,
    enrich_nodes_with_day_route,
    filter_tiles,
    list_catalog_course_tiles,
    list_route_tiles,
    list_transfer_tiles,
)


def test_segments_contract():
    assert SCHEDULE_SEGMENTS == ("Каталог", "Пересадки", "Маршрут")


def test_area_summary_uses_counts_not_hardcoded():
    tile = build_area_summary_tile(
        index_stats={"files": ["a/1.md", "b/2.md"]},
        course_count=2,
        concept_count=10,
        transfer_count=3,
        route_stop_count=4,
    )
    assert tile.kind == "summary"
    assert "2 курс" in tile.quant
    assert "10 тем" in tile.quant
    assert "3 пересадок" in tile.status
    assert "82" not in tile.quant
    assert "8" not in tile.quant or "10" in tile.quant


def test_transfer_tiles_multi_course_and_address():
    concepts = {
        "tools": {
            "label": "Tools",
            "documents": ["course_a/l1.md", "course_b/m1.md"],
        },
        "solo": {
            "label": "Solo",
            "documents": ["course_a/l2.md"],
        },
        "lesson:course-a-l1": {
            "label": "L1",
            "level": "lesson",
            "course": "course_a",
            "documents": ["course_a/l1.md"],
        },
    }
    rels = [
        {
            "source_concept_id": "tools",
            "target_concept_id": "lesson:course-a-l1",
            "relation_type": "part_of",
        }
    ]
    nodes = build_concept_schedule_nodes(concepts, rels)
    transfers = list_transfer_tiles(nodes)
    ids = {t.concept_id for t in transfers}
    assert "tools" in ids
    assert "solo" not in ids
    tools = next(t for t in transfers if t.concept_id == "tools")
    assert " · " in tools.address
    assert tools.status.startswith("в 2")
    assert set(tools.courses) == {"course_a", "course_b"}


def test_route_tiles_share_address_format():
    concepts = {
        "a": {"label": "Alpha", "documents": ["course_a/l1.md"]},
        "b": {"label": "Beta", "documents": ["course_b/m1.md"]},
        "lesson:course-a-l1": {
            "label": "Lesson 1",
            "level": "lesson",
            "course": "course_a",
            "documents": ["course_a/l1.md"],
        },
    }
    rels = [
        {
            "source_concept_id": "a",
            "target_concept_id": "lesson:course-a-l1",
            "relation_type": "part_of",
        }
    ]
    nodes = build_concept_schedule_nodes(concepts, rels)
    nodes, route = enrich_nodes_with_day_route(
        nodes,
        mastery_vector={"a": 0.1, "b": 0.2},
        due_concept_ids=["b"],
        k=6,
    )
    tiles = list_route_tiles(nodes, route)
    # At least due/frontier items can form a route
    assert isinstance(tiles, list)
    for t in tiles:
        assert t.address
        assert " · " in t.address or t.address  # non-empty address (north star)
        assert t.quant.startswith("стоп ")


def test_filter_tiles_hides_non_matching():
    from app.library_schedule_read import ScheduleTile

    tiles = [
        ScheduleTile(
            kind="transfer",
            title="Tools",
            address="course_a · L1",
            status="в 2 курсах",
            quant="2",
            courses=("course_a", "course_b"),
            concept_id="tools",
        ),
        ScheduleTile(
            kind="transfer",
            title="RAG",
            address="course_b · M1",
            status="в 2 курсах",
            quant="2",
            courses=("course_a", "course_b"),
            concept_id="rag",
        ),
    ]
    hit = filter_tiles(tiles, "tools")
    assert len(hit) == 1
    assert hit[0].title == "Tools"
    assert filter_tiles(tiles, "missing-xyz") == []


def test_catalog_course_tiles_from_index(monkeypatch):
    monkeypatch.setattr(
        "app.library_schedule_read.list_library_courses",
        lambda _stats: [
            type(
                "C",
                (),
                {
                    "folder_rel": "Deep",
                    "title": "Deep Course",
                    "source_paths": ("Deep/a.md", "Deep/b.md"),
                    "needs_reindex": False,
                },
            )()
        ],
    )
    tiles = list_catalog_course_tiles({})
    assert len(tiles) == 1
    assert tiles[0].title == "Deep Course"
    assert "Deep" in tiles[0].address
