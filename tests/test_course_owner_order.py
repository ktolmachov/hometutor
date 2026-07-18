"""Owner course order: pure helpers + catalog tile ranking."""

from __future__ import annotations

from app.course_owner_order import (
    COURSE_OWNER_ORDER_KEY,
    merge_owner_order_with_available,
    move_course_in_order,
    read_course_owner_order,
    write_course_owner_order,
)
from app.library_schedule_read import list_catalog_course_tiles
from app.ui.knowledge_graph_d3 import build_kg_payload


def test_move_and_session_roundtrip():
    state: dict = {}
    order = ["course_b", "course_a", "course_c"]
    write_course_owner_order(state, order)
    assert read_course_owner_order(state) == order
    assert state[COURSE_OWNER_ORDER_KEY] == order
    moved = move_course_in_order(order, "course_c", delta=-1)
    assert moved == ["course_b", "course_c", "course_a"]
    assert move_course_in_order(order, "course_b", delta=-1) == order  # top bound
    assert move_course_in_order(order, "missing", delta=1) == order


def test_merge_fills_missing_courses():
    merged = merge_owner_order_with_available(
        ["a", "b", "c"],
        owner_order=["c", "ghost"],
    )
    assert merged[0] == "c"
    assert set(merged) == {"a", "b", "c"}
    assert "ghost" not in merged


def test_catalog_tiles_respect_owner_order(monkeypatch):
    monkeypatch.setattr(
        "app.library_schedule_read.list_library_courses",
        lambda _stats: [
            type(
                "C",
                (),
                {
                    "folder_rel": "base",
                    "title": "Base",
                    "source_paths": ("base/a.md",),
                    "needs_reindex": False,
                },
            )(),
            type(
                "C",
                (),
                {
                    "folder_rel": "Deep",
                    "title": "Deep",
                    "source_paths": ("Deep/a.md",),
                    "needs_reindex": False,
                },
            )(),
        ],
    )
    tiles = list_catalog_course_tiles({}, owner_order=["Deep", "base"])
    assert [t.meta for t in tiles] == ["Deep", "base"]
    assert tiles[0].quant.startswith("#1")


def test_build_kg_payload_uses_owner_order_for_primary_course():
    concepts = {
        "shared": {
            "label": "Shared",
            "documents": ["course_a/l1.md", "course_b/m1.md"],
            "prerequisites": [],
        },
    }
    payload = build_kg_payload(
        concepts,
        mastery_vector={},
        learned_set=set(),
        course_owner_order=["course_b", "course_a"],
    )
    node = next(n for n in payload["nodes"] if n["id"] == "shared")
    assert node["primary_course"] == "course_b"
    assert payload["course_owner_order"] == ["course_b", "course_a"]
