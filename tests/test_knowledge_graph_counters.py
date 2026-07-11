"""B1 (wave-trust-signals): unified Knowledge Graph counters — single source of truth.

Mission Control (``render_kg_mission_card``) and the Knowledge Graph screen
(``build_kg_payload`` → ``dashboards_graph`` caption) must report identical counters
for the same graph version. ``compute_kg_counters`` is the shared helper; these tests
pin its semantics (lesson boundary, recomputed frontier vs the stale raw ``frontier``
bundle flag, avg_mastery denominator) and guarantee parity with
``build_kg_payload["stats"]`` so the two screens can never drift apart again.
"""

from __future__ import annotations

import inspect

from app.ui.knowledge_graph_d3 import build_kg_payload, compute_kg_counters


class TestComputeKgCounters:
    def test_lesson_nodes_excluded_from_concepts_case_insensitive(self):
        concepts = {
            "a": {"label": "A"},
            "b": {"label": "B"},
            "lec1": {"label": "Lecture 1", "level": "lesson"},
            "lec2": {"label": "Lecture 2", "level": "Lesson"},  # case-insensitive match
        }
        counters = compute_kg_counters(concepts)

        assert counters["total"] == 4
        assert counters["total_concepts"] == 2
        assert counters["total_lessons"] == 2

    def test_frontier_recomputed_ignores_stale_raw_flag(self):
        # 'b' carries a stale raw ``frontier`` flag, but its prerequisite 'a' is not
        # mastered → recomputed frontier must be False. 'a' has no prereqs and zero
        # mastery → it is the only frontier node.
        concepts = {
            "a": {},
            "b": {"prerequisites": ["a"], "frontier": True},
        }
        counters = compute_kg_counters(concepts)

        assert counters["frontier"] == 1
        assert counters["total_concepts"] == 2

    def test_raw_frontier_flag_false_but_ready_node_is_still_frontier(self):
        concepts = {"a": {"frontier": False}}  # stale raw flag says "no"

        counters = compute_kg_counters(concepts)

        # no prereqs, mastery 0, not learned → recomputed frontier True despite the flag
        assert counters["frontier"] == 1

    def test_frontier_respects_prerequisite_mastery(self):
        concepts = {
            "a": {},
            "b": {"prerequisites": ["a"]},
        }
        mastery_vector = {"a": 0.9}  # 'a' mastered (>=80%) → 'b' prereqs ready

        counters = compute_kg_counters(concepts, mastery_vector=mastery_vector)

        assert counters["frontier"] == 1  # only 'b' ('a' is learned)
        assert counters["learned"] == 1  # 'a' mastery >= 80 → learned

    def test_avg_mastery_denominator_is_all_nodes_and_learned_is_100(self):
        concepts = {
            "a": {},
            "c": {"learned": True},
            "lec": {"level": "lesson"},
        }
        counters = compute_kg_counters(concepts)

        # mastery: a=0, c=100 (learned), lec=0 → 100 / 3 = 33.3
        assert counters["total"] == 3
        assert counters["avg_mastery"] == round(100 / 3, 1)
        assert counters["learned"] == 1

    def test_empty_concepts(self):
        counters = compute_kg_counters({})

        assert counters["total"] == 0
        assert counters["total_concepts"] == 0
        assert counters["total_lessons"] == 0
        assert counters["frontier"] == 0
        assert counters["avg_mastery"] == 0.0
        assert counters["clusters"] == 0


class TestCountersParityWithPayload:
    def test_compute_kg_counters_equals_build_kg_payload_stats(self):
        concepts = {
            "a": {"label": "A"},
            "b": {"label": "B", "prerequisites": ["a"], "frontier": True, "learned": False},
            "lec": {"label": "Lec", "level": "lesson"},
        }
        mastery_vector = {"a": 0.5}
        relations = [
            {"source_concept_id": "a", "target_concept_id": "b", "relation_type": "related"},
        ]

        payload = build_kg_payload(
            concepts,
            mastery_vector=mastery_vector,
            learned_set=["b"],
            doc_index={},
            typed_relations=relations,
        )
        counters = compute_kg_counters(
            concepts,
            mastery_vector=mastery_vector,
            learned_set=["b"],
            typed_relations=relations,
        )

        # The graph-screen stats and the Mission Control counters share one code path.
        assert payload["stats"] == counters

    def test_payload_stats_carry_concept_and_lesson_totals(self):
        payload = build_kg_payload(
            {"x": {"label": "X"}, "lec": {"label": "Lec", "level": "lesson"}},
        )

        stats = payload["stats"]
        assert stats["total"] == 2
        assert stats["total_concepts"] == 1
        assert stats["total_lessons"] == 1


class TestMissionControlUsesSharedHelper:
    def test_render_kg_mission_card_calls_compute_kg_counters_not_local_math(self):
        from app.ui.mission_control import render_kg_mission_card

        source = inspect.getsource(render_kg_mission_card)

        assert "compute_kg_counters" in source
        # the old divergent formulas must be gone (regression guard for B1)
        assert "total - lessons" not in source
        assert 'd.get("frontier")' not in source
