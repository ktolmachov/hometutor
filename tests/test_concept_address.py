"""P1: concept address helper + multi-course badge + day_route addresses."""

from __future__ import annotations

from app.concept_address import (
    build_part_of_lesson_index,
    day_route_addresses,
    multi_course_badge_label,
    resolve_concept_address,
    top_folder_from_path,
)
from app.ui.knowledge_graph_d3 import build_kg_payload
from app.adaptive_plan_step_text import plan_block_concept_line


def test_top_folder_and_badge():
    assert top_folder_from_path("course_a/lesson-1.md") == "course_a"
    assert top_folder_from_path("lone.md") == ""
    assert multi_course_badge_label(["a"]) is None
    assert multi_course_badge_label(["a", "b"]) == "в 2 курсах"
    assert multi_course_badge_label(["b", "a", "a"]) == "в 2 курсах"


def test_resolve_address_via_part_of_lesson():
    concepts = {
        "tools": {
            "label": "Tools",
            "documents": ["course_a/lesson-1.md", "course_b/module-1.md"],
        },
        "lesson:course-a-lesson-1": {
            "label": "Lesson 1 Intro",
            "level": "lesson",
            "course": "course_a",
            "documents": ["course_a/lesson-1.md", "course_a/lesson-1.txt"],
        },
        "lesson:course-b-module-1": {
            "label": "Module 1 Deep",
            "level": "lesson",
            "course": "course_b",
            "documents": ["course_b/module-1.md"],
        },
    }
    rels = [
        {
            "source_concept_id": "tools",
            "target_concept_id": "lesson:course-a-lesson-1",
            "relation_type": "part_of",
        },
        {
            "source_concept_id": "tools",
            "target_concept_id": "lesson:course-b-module-1",
            "relation_type": "part_of",
        },
    ]
    index = build_part_of_lesson_index(concepts, rels)
    assert len(index["tools"]) == 2
    addr = resolve_concept_address(
        "tools",
        concept=concepts["tools"],
        courses=["course_a", "course_b"],
        lessons=index["tools"],
    )
    assert " · " in addr
    assert addr.split(" · ", 1)[0] in {"course_a", "course_b"}
    assert multi_course_badge_label(["course_a", "course_b"]) == "в 2 курсах"


def test_resolve_address_fallback_primary_doc():
    addr = resolve_concept_address(
        "orphan",
        concept={
            "label": "Orphan",
            "documents": ["ИИ Агенты/урок_2.md"],
        },
    )
    assert addr == "ИИ Агенты · урок 2"


def test_lesson_node_address():
    addr = resolve_concept_address(
        "lesson:course-a-l1",
        concept={
            "label": "Урок 1",
            "level": "lesson",
            "course": "course_a",
            "documents": ["course_a/l1.md"],
        },
        is_lesson=True,
    )
    assert addr == "course_a · Урок 1"


def test_attach_addresses_and_day_route_nonempty():
    concepts = {
        "frontier_a": {
            "label": "Frontier A",
            "level": "intermediate",
            "documents": ["course_a/lesson-1.md"],
            "prerequisites": [],
        },
        "due_b": {
            "label": "Due B",
            "level": "basic",
            "documents": ["course_b/m1.md", "course_a/shared.md"],
            "prerequisites": [],
        },
        "lesson:course-a-lesson-1": {
            "label": "L1",
            "level": "lesson",
            "course": "course_a",
            "documents": ["course_a/lesson-1.md"],
        },
    }
    rels = [
        {
            "source_concept_id": "frontier_a",
            "target_concept_id": "lesson:course-a-lesson-1",
            "relation_type": "part_of",
        }
    ]
    payload = build_kg_payload(
        concepts,
        mastery_vector={},
        learned_set=set(),
        due_reviews=[{"concept": "due_b"}],
        typed_relations=rels,
    )
    # Attach already happens inside build_kg_payload
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id["frontier_a"]["address"]
    assert " · " in by_id["frontier_a"]["address"]
    assert by_id["due_b"]["address"]
    badge = by_id["due_b"].get("courses_badge")
    assert badge == "в 2 курсах"

    route = payload.get("day_route") or []
    # day_route may be empty if nothing is frontier/due after filtering lessons;
    # force attach path for stops helper
    assert all(str(by_id[cid].get("address") or "").strip() for cid in route)

    # Synthetic day_route coverage: every node address non-empty (north star)
    for n in payload["nodes"]:
        if n.get("is_lesson"):
            continue
        assert str(n.get("address") or "").strip(), n

    rows = day_route_addresses(
        {
            "nodes": payload["nodes"],
            "day_route": [n["id"] for n in payload["nodes"] if not n.get("is_lesson")],
        }
    )
    assert rows
    assert all(r["address"] for r in rows)


def test_plan_block_prefers_address():
    assert plan_block_concept_line({"address": "Deep · Module 1", "concept": "x"}) == "Deep · Module 1"
    assert plan_block_concept_line({"concept": "Tools"}) == "Tools"
