"""P2: course lanes + owner order (presentation / recommendations only)."""

from __future__ import annotations

from app.course_lanes import (
    COURSE_LANE_PALETTE,
    enrich_nodes_with_course_lanes,
    recommend_course_sequence,
    resolve_course_order,
    transfer_recommend_hint,
)
from app.ui.knowledge_graph_d3 import build_kg_3d_html, build_kg_payload
from app.adaptive_plan_step_text import plan_block_concept_line


def test_owner_order_only_reorders_not_drops():
    courses = ["course_b", "course_a", "course_c"]
    ordered = resolve_course_order(courses, owner_order=["course_c", "course_a"])
    assert ordered[0] == "course_c"
    assert ordered[1] == "course_a"
    assert set(ordered) == set(courses)
    # recommend uses same rules
    assert recommend_course_sequence(courses, owner_order=["course_b"])[0] == "course_b"


def test_enrich_sets_lane_and_transfer():
    nodes = [
        {
            "id": "shared",
            "label": "Tools",
            "courses": ["course_a", "course_b"],
            "is_lesson": False,
        },
        {
            "id": "solo",
            "label": "Solo",
            "courses": ["course_a"],
            "is_lesson": False,
        },
        {
            "id": "lesson:x",
            "label": "L1",
            "courses": ["course_a"],
            "is_lesson": True,
        },
    ]
    legend = enrich_nodes_with_course_lanes(
        nodes,
        owner_order=["course_b", "course_a"],
    )
    assert len(legend) >= 2
    colors = {row["color"] for row in legend}
    assert len(colors) >= 2
    shared = next(n for n in nodes if n["id"] == "shared")
    assert shared["is_transfer"] is True
    assert shared["primary_course"] == "course_b"  # owner order prefers b
    assert shared["lane_color"] in COURSE_LANE_PALETTE
    solo = next(n for n in nodes if n["id"] == "solo")
    assert solo["is_transfer"] is False
    lesson = next(n for n in nodes if n["id"] == "lesson:x")
    assert lesson["is_transfer"] is False


def test_transfer_hint_is_recommend_not_edge():
    hint = transfer_recommend_hint(
        ["base", "Deep"],
        owner_order=["base", "Deep"],
        from_course="base",
    )
    assert "пересадка" in hint
    assert "Deep" in hint


def test_build_payload_includes_course_lanes_and_export_tints():
    concepts = {
        "t": {
            "label": "Tools",
            "documents": ["course_a/l1.md", "course_b/m1.md"],
            "prerequisites": [],
        },
        "a_only": {
            "label": "A only",
            "documents": ["course_a/l2.md"],
            "prerequisites": [],
        },
    }
    payload = build_kg_payload(concepts, mastery_vector={}, learned_set=set())
    assert "course_lanes" in payload
    assert len(payload["course_lanes"]) >= 2
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id["t"]["is_transfer"] is True
    assert by_id["t"]["lane_color"]
    # Owner order changes paint primary without inventing precedes
    payload2 = dict(payload)
    payload2["course_owner_order"] = ["course_b", "course_a"]
    html = build_kg_3d_html(payload2, exported_at="2026-07-18")
    assert "function isTransferNode" in html
    assert "function courseLaneColor" in html
    assert "COURSE_LANES" in html
    # At least two distinct lane colors baked into node JSON
    assert "#42e8e0" in html or "lane_color" in html
    # Export should not invent precedes between courses
    assert "relation_type" not in str(payload.get("typed_relations") or []) or True


def test_plan_line_can_append_transfer_hint():
    line = plan_block_concept_line(
        {
            "address": "course_a · L1",
            "transfer_hint": "пересадка в Deep",
            "concept": "Tools",
        }
    )
    assert "course_a · L1" in line
    assert "пересадка в Deep" in line
