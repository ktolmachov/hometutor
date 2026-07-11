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

from app.ui.knowledge_graph_d3 import (
    build_kg_payload,
    collect_kg_learned_set,
    compute_kg_counters,
)


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

    def test_total_nodes_equals_concepts_plus_lessons(self):
        concepts = {
            "a": {"label": "A"},
            "b": {"label": "B", "level": "intermediate"},
            "lesson:lec-1": {"label": "Lec 1", "level": "lesson"},
            "c": {"label": "C"},
        }
        counters = compute_kg_counters(concepts)

        assert counters["total_nodes"] == counters["total"] == 4
        assert counters["total_concepts"] == 3
        assert counters["total_lessons"] == 1
        assert counters["total_nodes"] == counters["total_concepts"] + counters["total_lessons"]

    def test_lesson_anchor_id_prefix_counted_as_lesson_without_level(self):
        # Legacy/edge bundle: node carries the curriculum-anchor ``lesson:`` prefix but
        # no ``level`` field. It must still be classified as a lesson (matching
        # ``dashboards_graph._is_lesson_concept``), never leaking into ``total_concepts``.
        concepts = {
            "real_concept": {"label": "Real"},
            "lesson:legacy-lec": {"label": "Legacy Lec"},  # prefix only, no level
        }
        counters = compute_kg_counters(concepts)

        assert counters["total_nodes"] == 2
        assert counters["total_concepts"] == 1
        assert counters["total_lessons"] == 1

    def test_lesson_nodes_do_not_count_as_ready_to_learn(self):
        concepts = {
            "a": {"label": "A"},
            "lesson:lec-1": {"label": "Lec 1", "level": "lesson"},
        }
        counters = compute_kg_counters(concepts)

        assert counters["total_concepts"] == 1
        assert counters["total_lessons"] == 1
        assert counters["frontier"] == 1

    def test_lesson_nodes_do_not_count_as_learned_concepts(self):
        concepts = {
            "a": {"label": "A", "learned": True},
            "lesson:lec-1": {"label": "Lec 1", "level": "lesson", "learned": True},
        }
        counters = compute_kg_counters(concepts)

        assert counters["total_concepts"] == 1
        assert counters["total_lessons"] == 1
        assert counters["learned"] == 1


class TestCollectLearnedSet:
    def test_combines_session_learned_and_bundle_flags(self, monkeypatch):
        import streamlit

        monkeypatch.setattr(streamlit, "session_state", {"tutor_learned_concepts": ["sess_a"]})
        concepts = {
            "sess_a": {},
            "bundle_learned": {"learned": True},
            "plain": {},
        }

        learned = collect_kg_learned_set(concepts)

        assert learned == {"sess_a", "bundle_learned"}

    def test_missing_session_key_is_safe(self, monkeypatch):
        import streamlit

        monkeypatch.setattr(streamlit, "session_state", {})
        concepts = {"a": {"learned": True}}

        assert collect_kg_learned_set(concepts) == {"a"}

    def test_session_learned_concept_drives_counters_consistently(self, monkeypatch):
        """Audit B1: a concept learned only in-session must raise avg_mastery / learned and
        drop frontier identically on both screens, because both pass collect_kg_learned_set."""
        import streamlit

        monkeypatch.setattr(streamlit, "session_state", {"tutor_learned_concepts": ["sess"]})
        concepts = {"sess": {}}

        without = compute_kg_counters(concepts)  # the old Mission Control path (no learned_set)
        with_learned = compute_kg_counters(
            concepts, learned_set=collect_kg_learned_set(concepts)
        )

        assert without["learned"] == 0 and without["avg_mastery"] == 0.0
        assert without["frontier"] == 1  # unlearned, no prereqs → was frontier
        assert with_learned["learned"] == 1 and with_learned["avg_mastery"] == 100.0
        assert with_learned["frontier"] == 0  # learned → no longer frontier


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

    def test_render_kg_mission_card_passes_learned_set_to_counters(self):
        """Audit B1: Mission Control must build and pass the same learned_set the KG tab uses."""
        from app.ui.mission_control import render_kg_mission_card

        source = inspect.getsource(render_kg_mission_card)

        assert "collect_kg_learned_set" in source
        assert "learned_set=" in source


class TestSharedLessonDetection:
    """B1: the "is this node a lesson?" rule must be one definition everywhere."""

    def test_canonical_helper_lives_in_data_layer(self):
        from app.knowledge_graph import is_lesson_node

        assert is_lesson_node("lesson:x", {}) is True
        assert is_lesson_node("c", {"level": "Lesson"}) is True
        assert is_lesson_node("c", {}) is False

    def test_dashboards_graph_is_lesson_concept_is_the_shared_helper(self):
        from app.knowledge_graph import is_lesson_node
        from app.ui import dashboards_graph
        from app.ui.knowledge_graph_d3 import _is_lesson_node

        # The UI helpers are the very same callable as the data-layer canonical
        # definition, not independent reimplementations that can drift (B1).
        assert _is_lesson_node is is_lesson_node
        assert dashboards_graph._is_lesson_concept is is_lesson_node

    def test_counter_matches_audit_helper_on_prefix_only_node(self):
        from app.ui.dashboards_graph import _is_lesson_concept

        concepts = {
            "lesson:lec": {"label": "Lec"},  # prefix only, no level
            "plain": {"label": "Plain"},
        }
        counters = compute_kg_counters(concepts)

        for cid, data in concepts.items():
            assert _is_lesson_concept(cid, data) == (cid == "lesson:lec")
        # the counter agrees with the shared helper: 1 lesson, 1 concept
        assert counters["total_lessons"] == 1
        assert counters["total_concepts"] == 1


class TestProgressStatsExcludesLessons:
    """B1 audit (P2): ``get_progress_stats`` must count concepts without lessons so the
    progress UI's "концептов / Покрытие графа" metric agrees with Mission Control and the
    Knowledge Graph screen, instead of diluting coverage with curriculum-anchor lessons."""

    @staticmethod
    def _reader(concepts):
        from pathlib import Path

        from app.knowledge_graph import JsonKnowledgeGraph

        kg = JsonKnowledgeGraph(path=Path("/nonexistent-for-test"))
        kg._data = {"concepts": dict(concepts), "documents": {}, "edges": {}}
        return kg

    def test_total_concepts_excludes_lessons(self):
        concepts = {
            "a": {"level": "beginner", "learned": True},
            "b": {"level": "intermediate"},
            "lesson:lec-1": {"level": "lesson"},
            "lesson:lec-2": {"level": "lesson", "learned": True},
        }
        stats = self._reader(concepts).get_progress_stats()

        assert stats["total_concepts"] == 2
        assert stats["total_lessons"] == 2
        assert stats["learned"] == 1  # only concept 'a'; lesson 'lec-2' is not a concept

    def test_mastery_percent_is_concept_coverage_not_diluted_by_lessons(self):
        # 1 of 2 concepts learned -> 50%, even though lessons inflate the node count.
        concepts = {
            "a": {"level": "beginner", "learned": True},
            "b": {"level": "advanced"},
            "lesson:lec": {"level": "lesson"},
        }
        stats = self._reader(concepts).get_progress_stats()

        assert stats["total_concepts"] == 2
        assert stats["learned"] == 1
        assert stats["mastery_percent"] == 50.0

    def test_lesson_anchor_prefix_excluded_without_level(self):
        # prefix-only lesson node (no level) must not leak into concepts (legacy bundle)
        concepts = {
            "real": {"level": "beginner"},
            "lesson:legacy": {},
        }
        stats = self._reader(concepts).get_progress_stats()

        assert stats["total_concepts"] == 1
        assert stats["total_lessons"] == 1

    def test_level_distribution_skips_lessons(self):
        # lessons used to fall into 'intermediate' via the level fallback; now excluded
        concepts = {
            "a": {"level": "beginner"},
            "lesson:lec": {"level": "lesson"},
        }
        stats = self._reader(concepts).get_progress_stats()

        assert stats["level_distribution"] == {"beginner": 1, "intermediate": 0, "advanced": 0}


class TestMissionControlCounterFallback:
    """B1 audit (P1): a failure in one input layer must never render synthetic zeros over
    a still-rendered graph preview. typed_relations failures degrade gracefully; only a
    counter-helper failure shows an honest "счётчики недоступны"."""

    def test_no_synthetic_zero_fallback_in_card(self):
        from app.ui.mission_control import render_kg_mission_card

        source = inspect.getsource(render_kg_mission_card)

        # the old combined try/except that zeroed all counters must be gone
        assert '"total_concepts": 0' not in source
        # typed_relations failure degrades to an empty list instead of zeroing counters
        assert "typed_relations = []" in source
        # an honest neutral placeholder replaces synthetic zeros on counter failure
        assert "Счётчики недоступны" in source
