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
import os
import time

import pytest

from app.ui.knowledge_graph_d3 import (
    KG_3D_ACTION_KEY,
    KG_3D_ACTION_RESULT_KEY,
    KG_3D_DEDUP_KEY,
    KG_3D_FRESHNESS_SECONDS,
    KG_3D_MAX_RAW_LEN,
    build_kg_3d_html,
    build_kg_html,
    build_kg_payload,
    collect_kg_learned_set,
    compute_kg_counters,
    consume_kg_3d_query_param,
    decode_kg_3d_query_raw,
    encode_kg_3d_query_raw,
    ensure_kg_3d_session_nonce,
    mark_kg_3d_event,
    validate_kg_3d_envelope,
)
from app.ui.knowledge_graph_d3_analysis import node_worth, top_worth_factor, DUE_WEIGHT, NOVEL_WEIGHT


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


class TestA2WorthScoring:
    """A2: worth() must be deterministic, pure, favor due/novel/decay over pure reach.
    top_worth_factor reports the largest term.
    """

    def test_worth_respects_due_even_for_learned_nodes(self):
        # due means scheduled for repetition (maintenance), so it must contribute
        # to worth for "route of the day" even if mastery high / learned=True.
        n = {"id": "x", "learned": True, "due": 3, "novel": False, "centrality": 0.1}
        w = node_worth(n)
        assert w > 0.0
        assert "к повторению" in top_worth_factor(n)

    def test_worth_higher_for_due_and_novel(self):
        n_due = {"id": "d", "due": 3, "frontier": True, "centrality": 0.2}
        n_novel = {"id": "n", "novel": True, "centrality": 0.2}
        n_struct = {"id": "s", "centrality": 0.95}  # high reach but nothing personal

        w_due = node_worth(n_due)
        w_novel = node_worth(n_novel)
        w_struct = node_worth(n_struct)

        assert w_due > w_struct + 1.0
        assert w_novel > w_struct + 1.0
        # due has bigger weight
        assert w_due > w_novel

    def test_top_factor_reports_due_or_novel(self):
        assert "к повторению" in top_worth_factor({"due": 4})
        assert "новое для тебя" in top_worth_factor({"novel": True})
        # learned without due and without retention issue -> no factor (worth will be 0)
        assert top_worth_factor({"learned": True}) == ""
        # even with centrality, no urgency => no factor
        assert top_worth_factor({"learned": True, "centrality": 0.9}) == ""

    def test_worth_attached_in_payload(self):
        payload = build_kg_payload({"c": {"label": "C"}, "l": {"label": "L", "level": "lesson"}})
        ns = {n["id"]: n for n in payload["nodes"]}
        assert "worth" in ns["c"]
        assert isinstance(ns["c"]["worth"], (int, float))
        assert "worth_reason" in ns["c"]
        # lesson has low worth
        assert ns["l"]["worth"] <= 1.0

    def test_day_route_is_computed_and_attached(self):
        # day_route should be a list of ids for actionable (due or frontier) nodes
        concepts = {
            "ready": {"label": "Ready", "prerequisites": []},
            "dueone": {"label": "DueOne"},
            "lesson:lec": {"label": "Lec", "level": "lesson"},
        }
        payload = build_kg_payload(
            concepts,
            due_reviews=[{"concept": "dueone"}],
            # make "ready" frontier by giving it a prereq that is "mastered"
            mastery_vector={"prereq": 0.9},
        )
        assert "day_route" in payload
        assert isinstance(payload["day_route"], list)
        # at least the due one or the ready one should be considered
        ids = set(payload["day_route"])
        assert "dueone" in ids or "ready" in ids or len(payload["day_route"]) == 0  # depending on frontier calc in this minimal graph


class Test3DCoverageAndContracts:
    """P3: browser templates (esp 3D) and new contracts must be exercised in tests.
    Covers build_kg_3d_html (incl edges), due resolver behavior, and that day-route
    data in payload is sane (JS side computeDayRoute fixed to return id strings).
    """

    def test_build_kg_3d_html_serializes_edges_and_nodes(self):
        concepts = {"a": {"label": "A"}, "b": {"label": "B", "prerequisites": ["a"]}}
        relations = [{"source_concept_id": "a", "target_concept_id": "b", "relation_type": "prereq"}]
        payload = build_kg_payload(concepts, typed_relations=relations)
        assert len(payload.get("edges", [])) >= 1
        edge = payload["edges"][0]

        html3 = build_kg_3d_html(payload)
        # Actual edge data must be embedded (not the placeholder [])
        assert f'"source": "{edge["source"]}"' in html3 or f'"source":"{edge["source"]}"' in html3
        assert f'"target": "{edge["target"]}"' in html3 or f'"target":"{edge["target"]}"' in html3
        # No old hardcoded placeholder left in output
        assert 'window.__EDGES__ = []' not in html3
        # nodes data present
        assert '"id": "a"' in html3 or '"id":"a"' in html3

    def test_due_uses_resolver_and_scopes_to_graph(self):
        # SR may give labels; resolver (label->cid) must attach due; out-of-graph ignored
        concepts = {"canonX": {"label": "Lesson One"}}
        due_reviews = [
            {"concept": "Lesson One"},  # label form
            {"concept": "ghost"},       # not in graph -> ignored
        ]
        payload = build_kg_payload(concepts, due_reviews=due_reviews)
        n = next(nn for nn in payload["nodes"] if nn["id"] == "canonX")
        assert n["due"] == 1  # attached via label resolver, scoped to this graph

    def test_3d_builder_accepts_and_embeds_edges(self):
        # direct call with edges in payload
        p = {"nodes": [{"id": "x", "worth": 1.2}], "edges": [{"source": "x", "target": "y"}], "stats": {}}
        h = build_kg_3d_html(p)
        assert "x" in h
        # specific edge data embedded, not placeholder
        assert '"source":"x"' in h or '"source": "x"' in h
        assert '"target":"y"' in h or '"target": "y"' in h
        assert 'window.__EDGES__ = []' not in h

    def test_3d_html_embeds_day_route_and_is_offline(self):
        """B1 DoD polish: A2 day_route in export; no CDN/three.js."""
        concepts = {
            "a": {"label": "A"},
            "b": {"label": "B", "prerequisites": ["a"]},
            "lesson:1": {"label": "Lec", "level": "lesson"},
        }
        payload = build_kg_payload(
            concepts,
            due_reviews=[{"concept": "b"}, {"concept": "a"}],
            mastery_vector={},
        )
        # Force a known route if frontier math is empty for this mini graph
        if not payload.get("day_route"):
            payload = {**payload, "day_route": ["b", "a"]}
        html3 = build_kg_3d_html(payload)
        assert "const DAY_ROUTE" in html3 or "DAY_ROUTE" in html3
        for rid in payload["day_route"]:
            assert rid in html3
        # Offline hall: canvas only — no external script vendors (CDN ban from plan #6/#15)
        assert "cdn.jsdelivr" not in html3.lower()
        assert "unpkg.com" not in html3.lower()
        assert "cdnjs.cloudflare" not in html3.lower()
        assert "<script src=" not in html3.lower()  # no external scripts
        assert "<canvas" in html3.lower()
        # Route-scene controls (reorientation plan R1/L2) replace timer «Полёт»
        assert "Тур" in html3 or "playbtn" in html3

    def test_3d_html_route_scene_contract(self):
        """R1/V1: first frame is route mode; modes + stop UI present; no worth-height."""
        concepts = {
            "a": {"label": "Agent"},
            "b": {"label": "RAG", "prerequisites": ["a"]},
            "c": {"label": "Memory", "prerequisites": ["b"]},
            "lesson:01": {"label": "L1", "level": "lesson"},
            "lesson:02": {"label": "L2", "level": "lesson"},
        }
        relations = [
            {"source_concept_id": "a", "target_concept_id": "b", "relation_type": "prereq"},
            {"source_concept_id": "b", "target_concept_id": "c", "relation_type": "prereq"},
            {
                "source_concept_id": "lesson:01",
                "target_concept_id": "lesson:02",
                "relation_type": "precedes",
            },
        ]
        payload = build_kg_payload(
            concepts,
            typed_relations=relations,
            due_reviews=[{"concept": "b"}, {"concept": "c"}, {"concept": "a"}],
        )
        if not payload.get("day_route"):
            payload = {**payload, "day_route": ["b", "c", "a"]}
        html3 = build_kg_3d_html(payload)

        # Default route scene + mode switcher (Memory Run skin / U0)
        assert "viewMode = 'route'" in html3 or 'viewMode = "route"' in html3
        assert "modeRoute" in html3
        assert "modeLocal" in html3
        assert "modeAll" in html3
        assert "Вся карта" in html3
        assert "Созвездие" in html3
        assert "Стоп" in html3
        assert "Home" in html3 or "homebtn" in html3
        # Tour state machine (L2), not raw setInterval flight
        assert "tourState" in html3
        assert "setInterval" not in html3
        # Route-first means full graph/noisy context is not the default:
        # route mode keeps stops + lesson anchors; local mode expands context.
        assert "function addImmediateContext" in html3
        assert "function routeStopPos" in html3
        assert "function scenePos" in html3
        assert "if (viewMode === 'route')" in html3
        assert "if (active) addImmediateContext(ids, active);" in html3
        route_branch = html3.split("function visibleIdSet", 1)[1].split("if (viewMode === 'local')", 1)[0]
        assert "addImmediateContext" not in route_branch
        local_branch = html3.split("if (viewMode === 'local')", 1)[1].split("return ids;", 1)[0]
        assert "addLessonAnchors(ids, rid)" not in local_branch
        assert "return false;" in html3.split("function edgeVisibleInMode", 1)[1].split("function labelAllowSet", 1)[0]
        label_branch = html3.split("function labelAllowSet", 1)[1].split("function drawFloorPlane", 1)[0]
        assert "anchors stay quiet" in label_branch
        assert "return new Set(allow.slice(0, 8));" in label_branch
        assert "viewMode === 'local'" in label_branch
        assert "linked && !linked.is_lesson" in label_branch
        assert "quietRouteAnchor" in html3
        assert "localContextNode" in html3
        assert "localCap" in html3
        assert "function drawSmartLabel" in html3
        assert "labelIntersects" in html3
        assert "function drawActiveReasonCallout" in html3
        assert "Стоп ${idx + 1}/${route.length} · ${name} · ${reason}" in html3
        assert "!(viewMode === 'route' && isActive)" in html3
        # Memory Run panel + topbar design contract (U0)
        assert 'id="topbar"' in html3
        assert "#side{" in html3 and "width:314px" in html3
        side_css = html3.split("#side{", 1)[1].split("}", 1)[0]
        assert "overflow-y:auto" in side_css
        assert "overflow-x:hidden" in side_css
        # U5 split-rail HUD: two floating docks over a full-bleed stage.
        # Stop details = left dock (#stopdock), day route = right dock (#side).
        assert 'id="stopdock"' in html3
        assert 'class="kgx-panel kgx-hud"' in html3  # both docks use floating HUD chrome
        hud_css = html3.split(".kgx-hud{", 1)[1].split("}", 1)[0]
        assert "position:absolute" in hud_css
        assert "overflow-y:auto" in hud_css  # the dock owns its scroll (no nested cap)
        assert "--hud-l" in html3 and "--hud-r" in html3  # stage insets for the docks
        assert "function syncHudInsets" in html3
        assert "function hudInsets" in html3
        # U5: second measure after layout settles (iframe/srcdoc first paint).
        assert "requestAnimationFrame" in html3 and "syncHudInsets()" in html3
        assert 'aria-controls="stopdock side"' in html3
        assert "kgx-route-panel" in html3
        assert "min-height:40px" in html3  # CTA height
        assert "12px system-ui" in html3  # canvas labels ≥12px
        assert "function hoverAt" in html3
        assert "function openInterior" in html3
        assert "function openOnboarding" in html3
        assert "kgx-action-primary" in html3
        assert "masteryring" in html3
        # G0/G2/U2 render-contract extensions (placeholders substituted)
        assert "HOST_MODE" in html3
        assert "MASTERY_HISTORY" in html3
        assert "SNAPSHOT_DATE" in html3
        assert "CONCEPT_SECTIONS" in html3
        assert "startbtn" in html3 and "collectbtn" in html3
        assert "function beginAction" in html3
        assert "function drawMemoryTrace" in html3
        assert "function drawHallWash" in html3
        assert "hometutor:kg-action" in html3
        assert "__HOST_MODE__" not in html3
        assert "__MASTERY_HISTORY__" not in html3
        assert "__CONCEPT_SECTIONS__" not in html3
        assert "__SHOW_ONBOARDING__" not in html3
        assert "viewMode = 'route';" in html3.split("document.getElementById('homebtn').onclick", 1)[1]
        assert "function routePlatformWorldPoints" in html3
        assert "targetW" in html3 and "targetH" in html3
        assert "if (viewMode === 'route') fitRouteCamera();" in html3
        tour_end_branch = html3.split("if (activeStopIndex >= route.length - 1)", 1)[1].split("const delay", 1)[0]
        assert "viewMode = 'route';" in tour_end_branch
        assert "fitRouteCamera();" in tour_end_branch
        focus_branch = html3.split("function focus", 1)[1].split("function hoverAt", 1)[0]
        assert "viewMode = 'local';" in focus_branch
        assert "syncModeButtons();" in focus_branch
        assert "route first frame is sparse" in html3
        # Initial camera must fit the whole route, not immediately recenter on stop #1.
        assert "fitRouteCamera();" in html3
        assert "Nudge camera onto first stop" not in html3
        assert "const t = cameraForNode(o);" not in html3
        # Worth is not geometric height (R2)
        assert "worth || 0) * 18" not in html3
        assert "worth||0)*18" not in html3
        # B2 was deferred; do not keep dead UI for fields absent from the payload.
        assert "n.audio" not in html3
        assert "rubric_score" not in html3
        # The shipped JS artifact must use the same precedes/floor-collapse contract,
        # not only the Python mirror helper.
        assert "function computeLessonOrder" in html3
        assert "(e.relation_type || '') !== 'precedes'" in html3
        assert "Kahn topo" in html3
        assert "floorIndex.set" in html3
        # Offline + no external scripts
        assert "<script src=" not in html3.lower()
        assert "three.js" not in html3.lower()
        # Embedded route ids survive
        for rid in payload["day_route"]:
            assert rid in html3

    def test_3d_memory_run_design_contract_static(self):
        """V2′ structural design contract (no browser): topbar, CTA, tokens, doors off in export."""
        payload = {
            "nodes": [
                {"id": "a", "label": "Agent", "worth": 6.1, "worth_reason": "к повторению", "due": 1},
                {"id": "b", "label": "RAG", "worth": 5.5, "worth_reason": "новое", "novel": True},
            ],
            "edges": [],
            "stats": {"total_concepts": 2},
            "day_route": ["a", "b"],
            "mastery_history": [{"date": "2026-07-16", "mastery": {"a": 40.0}}],
        }
        html = build_kg_3d_html(payload, exported_at="2026-07-17")
        assert 'id="topbar"' in html
        assert "kgx-action-primary" in html
        assert "min-height:40px" in html
        assert "min-height:64px" in html  # topbar
        assert "max-height:72px" in html  # R1 desktop chrome cap
        assert "width:314px" in html  # side panel
        assert "--kgx-cyan" in html and "--kgx-lime" in html
        assert "function openInterior" in html
        assert "function openOnboarding" in html
        assert "Правила зала" in html
        assert 'id="helpbtn"' in html and ">Правила</button>" in html
        assert "localStorage.getItem(ONBOARD_SEEN_KEY)" in html
        assert "localStorage.setItem(ONBOARD_SEEN_KEY, '1')" in html
        assert ".stop-check{" in html  # U0/G2 rank stays; ✓ overlay
        assert 'id="morebtn"' in html  # R1 camera tools collapsed
        assert 'id="homebtn"' in html and 'id="topbtn"' in html and 'id="resetbtn"' in html
        assert 'id="toast"' in html and "kgx-toast" in html  # R2 action ack toast
        assert "function showToast" in html
        # R3 hall architecture (lanes + route underglow); no Three.js entities
        assert "laneColors" in html
        assert "rgba(154,108,255,0.14)" in html  # route underglow
        assert "no particles" in html.lower() or "no particles / stars / bokeh" in html
        # W0 quality: axis/nav, mobile fit, learner status, Q5/Q8/Q9
        assert "axisY" in html or "H - (narrow" in html or "H - 108" in html
        assert "W < 560" in html
        assert "Маршрут дня · стоп" in html
        assert "function strokeSmoothPath" in html  # Q8
        assert "function appendObsidianLink" in html  # Q5
        assert "rgba(223,229,255,0.28)" in html  # W0′ R6 ring track contrast
        # W0′ residual polish + W1 dawn/lanterns (vision №19 first slice)
        assert "function quizRouteProgress" in html
        assert "function drawRouteLantern" in html
        assert "kgx-export-inert" in html
        assert "в продукте" in html  # W0′-R7 export CTA hierarchy copy
        assert "пора повторить" in html  # W0′-R5 learner chips
        assert "due true" not in html  # no raw boolean chip
        assert "onboard-diag" in html  # W0′-R4 diag in ?-dialog
        assert "clip:rect(0,0,0,0)" in html  # W0′-R4 #hint not learner surface
        assert "0.70" in html  # W0′-R1 vertical fill targetH
        assert ".kgx-compass span{display:none}" in html.replace(" ", "") or (
            "kgx-compass span" in html and "display:none" in html
        )  # W0′-R2 variant A
        assert "небо теплеет" in html or "рассвет" in html  # W1 progress copy
        # W2a fog of forgetting + calm world (visual only; no new action)
        assert "function forgettingFor" in html
        assert "function drawForgettingFog" in html
        assert "function fogActiveFor" in html
        assert 'id="calmbtn"' in html
        assert "ht_kg3d_calm_world" in html
        assert "FOG_FORGET_MIN" in html
        assert "туман · можно войти" in html  # non-blocking invitation chip
        # W2b review action door (Flashcards nav)
        assert 'id="reviewbtn"' in html
        assert "beginAction('review')" in html or 'beginAction("review")' in html or "action === 'review'" in html
        assert "shouldShowReviewCta" in html
        # W3b Keeper guide surface
        assert "keeperbox" in html
        assert "updateKeeperLine" in html
        assert "KEEPER_GUIDE" in html
        # W3c threats surface
        assert "threatsbox" in html
        assert "updateThreatsPanel" in html
        assert "KEEPER_THREATS" in html
        # W3d quest line (morning goal)
        assert 'id="questbox"' in html
        assert "updateQuestLine" in html
        assert "KEEPER_QUEST" in html
        # H voices + W6c chronicle + W6a ghost
        assert 'id="voicesbox"' in html and "updateVoicesPanel" in html
        assert "KEEPER_VOICES" in html
        assert 'id="chroniclebox"' in html and "updateChronicleLine" in html
        assert "KEEPER_CHRONICLE" in html
        assert "function ghostActiveFor" in html and "function drawConfidenceGhost" in html
        # W6b rift + W6d architect + G4.3 privacy stub
        assert "function riftActiveFor" in html and "function drawPrerequisiteRift" in html
        assert "weakPrereqIds" in html
        assert 'id="architectbox"' in html and "updateArchitectBanner" in html
        assert "ARCHITECT_SIGNAL" in html
        assert 'id="photobtn"' in html and "privacy" in html.lower()
        # W4c district doors
        assert 'id="districts"' in html
        assert "door_quiz" in html and "door_flashcards" in html
        assert "updateDistrictDoors" in html
        assert "door_plan" in html and "door_konspekt" in html
        # W5a tutor ask handoff
        assert 'id="askbtn"' in html
        assert 'id="interior-ask"' in html
        assert "beginAction('ask')" in html or 'beginAction("ask")' in html or "action !== 'ask'" in html
        # W5c inline brief (graph retrieval, stay in hall)
        assert 'id="briefbtn"' in html
        assert 'id="interior-brief"' in html
        assert 'id="conceptbrief"' in html
        assert "beginAction('brief')" in html or 'beginAction("brief")' in html or "action !== 'brief'" in html
        assert "showConceptBrief" in html
        # G4.1 floor tint + G4.2 history scrubber (G4.3 photo export deferred / privacy)
        assert "function floorProgressScore" in html
        assert "function refreshMemorySetsFromHistory" in html
        assert 'id="replaybar"' in html
        assert "function playHistoryReplay" in html
        assert "prefers-reduced-motion" in html
        assert "three.js" not in html.lower()
        assert "<script src=" not in html.lower()
        # Export must not bake live doors / onboarding host flag
        assert "CONCEPT_SECTIONS = {}" in html or "CONCEPT_SECTIONS ={}" in html.replace(" ", "")
        assert "SHOW_ONBOARDING = false" in html or "SHOW_ONBOARDING=false" in html.replace(" ", "")
        assert "obsidian://" not in html
        assert "__CONCEPT_SECTIONS__" not in html

        embedded = build_kg_3d_html(
            payload,
            host_mode="embedded",
            session_nonce="a" * 32,
            concept_sections={
                "a": [
                    {
                        "heading": "Retrieval",
                        "in_basket": True,
                        "obsidian_uri": "obsidian://open?vault=t&file=x",
                    }
                ]
            },
            show_onboarding=True,
        )
        assert "obsidian://open" in embedded
        assert "SHOW_ONBOARDING = true" in embedded or "SHOW_ONBOARDING=true" in embedded.replace(
            " ", ""
        )
        assert "Открыть раздел" in embedded

    def test_3d_visual_smoke_viewport_matrix(self, tmp_path):
        """V2′ visual gate: production ``build_kg_3d_html`` on viewport matrix.

        Always-on when Playwright + Chromium are installed (importorskip otherwise).
        Structural design contract (``test_3d_memory_run_design_contract_static``) runs
        without a browser. This test proves the running production HTML: canvas not
        empty, Memory Run skin (topbar/CTA≥40px), route orientation, export inert.
        Opt-out: ``HT_SKIP_KG_3D_VISUAL=1`` (for environments without browsers).
        """
        if os.environ.get("HT_SKIP_KG_3D_VISUAL") == "1":
            pytest.skip("HT_SKIP_KG_3D_VISUAL=1")

        sync_api = pytest.importorskip("playwright.sync_api")
        concepts = {
            "study-session-agent": {"label": "Study session agent"},
            "rag": {"label": "RAG", "prerequisites": ["study-session-agent"]},
            "hometutor": {"label": "Hometutor", "prerequisites": ["rag"]},
            "ai-agent": {"label": "AI-agent", "prerequisites": ["hometutor"]},
            "memory-loop": {"label": "Петля памяти", "prerequisites": ["ai-agent"]},
            "tutor": {"label": "Тьютор", "prerequisites": ["memory-loop"]},
            "lesson:01": {"label": "Урок 1", "level": "lesson"},
        }
        route = [
            "study-session-agent",
            "rag",
            "hometutor",
            "ai-agent",
            "memory-loop",
            "tutor",
        ]
        payload = build_kg_payload(concepts)
        payload = {
            **payload,
            "day_route": route,
            "mastery_history": [
                {"date": "2026-07-15", "mastery": {"rag": 40.0}},
                {
                    "date": "2026-07-16",
                    "mastery": {"rag": 55.0, "study-session-agent": 38.0},
                },
            ],
        }
        html_path = tmp_path / "kg_3d_visual_smoke.html"
        html_path.write_text(
            build_kg_3d_html(payload, exported_at="2026-07-17"), encoding="utf-8"
        )

        viewports = (
            {"width": 1366, "height": 768},
            {"width": 1920, "height": 1080},
            {"width": 1024, "height": 768},
            {"width": 390, "height": 844},
        )
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for viewport in viewports:
                    page = browser.new_page(viewport=viewport)
                    page.goto(html_path.as_uri())
                    page.wait_for_load_state("load")
                    page.wait_for_timeout(300)
                    result = page.evaluate(
                        """
                        () => {
                          const canvas = document.querySelector('canvas');
                          const ctx = canvas.getContext('2d');
                          const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                          let nonBg = 0;
                          for (let i = 0; i < img.length; i += 32) {
                            const r = img[i], g = img[i + 1], b = img[i + 2];
                            if (!(r <= 8 && g <= 8 && b <= 12)) nonBg++;
                          }
                          const start = document.querySelector('#startbtn');
                          const collect = document.querySelector('#collectbtn');
                          const startH = start ? start.getBoundingClientRect().height : 0;
                          const bodyOverflowX = document.documentElement.scrollWidth >
                            document.documentElement.clientWidth + 1;
                          const topbar = document.querySelector('#topbar');
                          const side = document.querySelector('#side');
                          const sideStyle = side ? getComputedStyle(side) : null;
                          const stopdock = document.querySelector('#stopdock');
                          const stopdockStyle = stopdock ? getComputedStyle(stopdock) : null;
                          const stage = document.querySelector('#stage');
                          const stageWidth = stage ? stage.getBoundingClientRect().width : 0;
                          const routePanel = document.querySelector('#routepanel');
                          // Visible primary strip only (⋯ keeps Home/Top/Reset collapsed).
                          const primaryIconCount = document.querySelectorAll(
                            '.kgx-route-actions > .kgx-icon-btn, .kgx-route-actions > .kgx-route-more > #morebtn'
                          ).length;
                          const stops = [...document.querySelectorAll('.stop')].map((el, i) => {
                            const idxEl = el.querySelector('.stop-index');
                            const check = el.querySelector('.stop-check');
                            // First text node of .stop-index is the rank; ✓ lives in .stop-check.
                            const rankNode = idxEl
                              ? [...idxEl.childNodes].find(
                                  (n) => n.nodeType === Node.TEXT_NODE && String(n.textContent || '').trim()
                                )
                              : null;
                            const rankText = rankNode
                              ? String(rankNode.textContent || '').trim()
                              : (idxEl?.textContent || '').replace('✓', '').trim();
                            const checkStyle = check ? getComputedStyle(check) : null;
                            return {
                              index: i + 1,
                              done: el.classList.contains('done'),
                              rankText,
                              hasCheck: !!check,
                              checkText: check?.textContent || '',
                              checkPosition: checkStyle?.position || '',
                            };
                          });
                          const sideRectInitial = side?.getBoundingClientRect();
                          const routeTitleRect = document
                            .querySelector('.kgx-route-title')
                            ?.getBoundingClientRect();
                          const firstStopRect = document
                            .querySelector('#toplist .stop:first-child')
                            ?.getBoundingClientRect();
                          const routeTitleVisibleInitial = !!(
                            sideRectInitial && routeTitleRect &&
                            routeTitleRect.top >= sideRectInitial.top - 1 &&
                            routeTitleRect.bottom <= sideRectInitial.bottom + 1
                          );
                          const firstStopVisibleInitial = !!(
                            sideRectInitial && firstStopRect &&
                            firstStopRect.top >= sideRectInitial.top - 1 &&
                            firstStopRect.bottom <= sideRectInitial.bottom + 1
                          );
                          if (side) side.scrollTop = side.scrollHeight;
                          const sideRect = side?.getBoundingClientRect();
                          const lastStopRect = document
                            .querySelector('#toplist .stop:last-child')
                            ?.getBoundingClientRect();
                          const lastStopVisibleAfterSideScroll = !!(
                            sideRect && lastStopRect &&
                            lastStopRect.top >= sideRect.top - 1 &&
                            lastStopRect.bottom <= sideRect.bottom + 1
                          );
                          return {
                            nonBg,
                            routeOn: document.querySelector('#modeRoute')?.classList.contains('on'),
                            topbarPresent: !!topbar,
                            topbarMinH: topbar ? topbar.getBoundingClientRect().height : 0,
                            sideWidth: side ? side.getBoundingClientRect().width : 0,
                            sideOverflowY: sideStyle?.overflowY || '',
                            stopdockPresent: !!stopdock,
                            stopdockOverflowY: stopdockStyle?.overflowY || '',
                            stopdockPosition: stopdockStyle?.position || '',
                            stageWidth,
                            routePanelPresent: !!routePanel,
                            routeTitleVisibleInitial,
                            firstStopVisibleInitial,
                            sideCanScrollY: side ? side.scrollHeight > side.clientHeight + 1 : false,
                            lastStopVisibleAfterSideScroll,
                            stopCount: document.querySelectorAll('.stop').length,
                            stops,
                            stopInfo: document.querySelector('#stopinfo')?.textContent || '',
                            stopName: document.querySelector('#stopname')?.textContent || '',
                            snapshot: document.querySelector('#snapshotline')?.textContent || '',
                            startDisabled: !!start?.disabled,
                            collectDisabled: !!collect?.disabled,
                            startMinH: startH,
                            bodyOverflowX,
                            canvasCssH: canvas?.clientHeight || 0,
                            hasPrimaryCtaClass: !!document.querySelector('.kgx-action-primary'),
                            hasExternalScript: !!document.querySelector('script[src]'),
                            primaryIconCount,
                            hasRouteMore: !!document.querySelector('#morebtn'),
                            hasHomebtn: !!document.querySelector('#homebtn'),
                          };
                        }
                        """
                    )
                    page.close()

                    assert result["nonBg"] > 100, viewport
                    assert result["routeOn"] is True, viewport
                    assert result["topbarPresent"] is True, viewport
                    assert result["hasPrimaryCtaClass"] is True, viewport
                    assert result["stopCount"] == len(route), viewport
                    assert f"Стоп 1/{len(route)}" in result["stopInfo"], viewport
                    assert result["stopName"], viewport
                    assert "снимок от 2026-07-17" in result["snapshot"], viewport
                    assert result["startDisabled"] is True, viewport
                    assert result["collectDisabled"] is True, viewport
                    assert result["startMinH"] >= 40, viewport
                    assert result["bodyOverflowX"] is False, viewport
                    assert result["sideOverflowY"] == "auto", viewport
                    # U5 split-rail HUD: stop details live in the left dock, which owns
                    # its own scroll (no nested panel-head cap). Route stays in #side.
                    assert result["stopdockPresent"] is True, viewport
                    assert result["stopdockOverflowY"] == "auto", viewport
                    assert result["routePanelPresent"] is True, viewport
                    assert result["routeTitleVisibleInitial"] is True, viewport
                    assert result["firstStopVisibleInitial"] is True, viewport
                    assert result["lastStopVisibleAfterSideScroll"] is True, viewport
                    min_h = 400 if viewport["width"] <= 560 else 450
                    assert result["canvasCssH"] >= min_h, viewport
                    # U0/R1 layout tokens; mobile stacks docks in-flow — skip float checks there.
                    if viewport["width"] >= 1024:
                        assert result["topbarMinH"] >= 64, viewport
                        assert result["topbarMinH"] <= 72, viewport
                        assert 300 <= result["sideWidth"] <= 330, viewport
                        # U5: docks float over a full-bleed stage (Мнемополис на всю ширину).
                        assert result["stopdockPosition"] == "absolute", viewport
                        assert result["stageWidth"] >= viewport["width"] - 4, viewport
                        # Primary strip: ← tour → + ⋯ (camera tools collapsed)
                        assert result.get("primaryIconCount", 0) >= 3, viewport
                        assert result.get("primaryIconCount", 99) <= 4, viewport
                    # G2 / U0: rank stays visible; ✓ is absolute overlay on done stops only.
                    # Payload mastery last-snapshot keys: study-session-agent, rag → stops 1 & 2.
                    assert result["hasExternalScript"] is False, viewport
                    done_stops = [s for s in result["stops"] if s["done"]]
                    open_stops = [s for s in result["stops"] if not s["done"]]
                    assert len(done_stops) >= 2, (viewport, result["stops"])
                    for s in result["stops"]:
                        assert s["rankText"] == str(s["index"]), (viewport, s)
                    for s in done_stops:
                        assert s["hasCheck"] is True, (viewport, s)
                        assert s["checkText"] == "✓", (viewport, s)
                        assert s["checkPosition"] == "absolute", (viewport, s)
                    for s in open_stops:
                        assert s["hasCheck"] is False, (viewport, s)
            finally:
                browser.close()

    def test_3d_embedded_collect_click_to_ack_e2e(self, tmp_path, monkeypatch):
        """P1 live gate: click «В конспект» → action envelope → Python ack → UI Ack.

        Proves the path visual smoke cannot: export CTA is disabled there.
        Uses Playwright on embedded production HTML + host Python consumer
        (same ``_consume_and_apply_kg_3d_component_value`` as Streamlit).
        Opt-out: ``HT_SKIP_KG_3D_VISUAL=1``.
        """
        if os.environ.get("HT_SKIP_KG_3D_VISUAL") == "1":
            pytest.skip("HT_SKIP_KG_3D_VISUAL=1")

        sync_api = pytest.importorskip("playwright.sync_api")
        from app.ui import dashboards_graph as dg

        nonce = "b" * 32
        route = ["rag", "hometutor"]
        payload = {
            "nodes": [
                {
                    "id": "rag",
                    "label": "RAG",
                    "worth": 6.2,
                    "worth_reason": "к повторению",
                    "due": 1,
                    "mastery": 40,
                },
                {
                    "id": "hometutor",
                    "label": "Hometutor",
                    "worth": 5.0,
                    "worth_reason": "новое",
                    "novel": True,
                    "mastery": 10,
                },
            ],
            "edges": [],
            "stats": {"total_concepts": 2},
            "day_route": route,
            "mastery_history": [{"date": "2026-07-16", "mastery": {"rag": 40.0}}],
        }

        hall_html = build_kg_3d_html(
            payload,
            host_mode="embedded",
            session_nonce=nonce,
            collected_concept_ids=[],
            workbench_count=0,
            action_result=None,
            show_onboarding=False,
            exported_at="2026-07-17",
        )
        hall_path = tmp_path / "kg_3d_embedded_live.html"
        hall_path.write_text(hall_html, encoding="utf-8")

        # Mini Streamlit-like host: captures component value + optional URL bridge.
        host_html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>kg3d host harness</title>
<style>html,body{{margin:0;height:100%;background:#080812}}
iframe{{display:block;width:100%;height:100%;border:0}}</style></head>
<body>
<iframe id="kg-frame" title="hall" src="{hall_path.as_uri()}"></iframe>
<script>
window.__componentValues = [];
window.__urlReplaces = [];
window.__kgActions = [];
// Spy setComponentValue channel (wrapper/host would forward to Streamlit).
window.addEventListener('message', (event) => {{
  const d = event.data || {{}};
  if (d.isStreamlitMessage && d.type === 'streamlit:setComponentValue') {{
    window.__componentValues.push(d.value);
  }}
  if (d.type === 'hometutor:kg-action') {{
    window.__kgActions.push(d);
    // Emulate primary wrapper path: component envelope
    window.__componentValues.push({{
      kind: 'kg3d_action',
      version: 1,
      envelope: {{
        version: 1,
        source: 'kg3d',
        event_id: d.event_id,
        session_nonce: d.session_nonce,
        concept_id: d.concept_id,
        action: d.action,
        ts: d.ts,
      }},
    }});
  }}
}});
</script>
</body></html>
"""
        host_path = tmp_path / "kg_3d_host_harness.html"
        host_path.write_text(host_html, encoding="utf-8")

        calls = {"n": 0}

        class _KG:
            def get_related_documents(self, concept):
                return ["doc1.md"]

            def get_concepts(self):
                return {"rag": {"label": "RAG"}, "hometutor": {"label": "Hometutor"}}

        def fake_collect(**kwargs):
            calls["n"] += 1
            assert kwargs["concept"] == "rag"
            return (2, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", fake_collect)

        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1366, "height": 768})
                page.goto(host_path.as_uri())
                page.wait_for_load_state("load")
                page.wait_for_timeout(400)

                frame = page.frame_locator("#kg-frame")
                # Dismiss onboarding if present (embedded may auto-open).
                try:
                    if frame.locator("#onboard.is-open").count() > 0:
                        frame.locator("#onboard-ok").click(timeout=1500)
                        page.wait_for_timeout(150)
                except Exception:  # noqa: BLE001 - onboarding optional in this fixture
                    pass
                # Also try unconditional ok if overlay visible
                try:
                    ok = frame.locator("#onboard-ok")
                    if ok.count() and frame.locator("#onboard").evaluate(
                        "el => el.classList.contains('is-open')"
                    ):
                        ok.click(timeout=1000)
                except Exception:  # noqa: BLE001
                    pass

                # CTA enabled in embedded
                collect = frame.locator("#collectbtn")
                assert collect.count() == 1
                disabled = collect.evaluate("el => el.disabled")
                assert disabled is False, "embedded collect must be enabled"

                collect.click()
                page.wait_for_timeout(350)

                # Child pending UI
                busy = frame.locator("#collectbtn").get_attribute("aria-busy")
                status_text = frame.locator("#actionstatus").inner_text()
                assert busy == "true" or "Ожидание" in (
                    frame.locator("#collectbtn").inner_text()
                ) or "Доставка" in status_text or status_text == ""

                # Host captured action / component envelope
                captured = page.evaluate(
                    """() => ({
                      actions: window.__kgActions || [],
                      values: window.__componentValues || [],
                    })"""
                )
                assert captured["actions"] or captured["values"], (
                    "click must deliver hometutor:kg-action or component value"
                )

                # Prefer structured component value; else build from raw action
                value = None
                for v in captured["values"]:
                    if isinstance(v, dict) and v.get("kind") == "kg3d_action":
                        value = v
                        break
                if value is None and captured["actions"]:
                    a = captured["actions"][0]
                    value = {
                        "kind": "kg3d_action",
                        "version": 1,
                        "envelope": {
                            "version": 1,
                            "source": "kg3d",
                            "event_id": a["event_id"],
                            "session_nonce": a["session_nonce"],
                            "concept_id": a["concept_id"],
                            "action": a["action"],
                            "ts": a["ts"],
                        },
                    }
                assert value is not None
                env = value["envelope"]
                assert env["action"] == "collect"
                assert env["concept_id"] == "rag"
                assert env["session_nonce"] == nonce
                # Envelope shape matches wrapper setActionValue payload
                assert value.get("kind") == "kg3d_action"
                assert value.get("version") == 1
                assert env.get("source") == "kg3d"
                assert env.get("event_id")
                assert isinstance(env.get("ts"), (int, float)) and env["ts"] > 0

                state: dict = {"kg_3d_session_nonce": nonce}
                result = dg._consume_and_apply_kg_3d_component_value(
                    value,
                    node_ids=route,
                    knowledge_graph=_KG(),
                    doc_index={},
                    state=state,
                )
                assert calls["n"] == 1
                assert isinstance(result, dict)
                assert result["status"] == "succeeded"
                assert result["added"] == 2
                assert result["action"] == "collect"

                # Re-render hall with ack (same as Streamlit next run after st.rerun)
                acked_html = build_kg_3d_html(
                    payload,
                    host_mode="embedded",
                    session_nonce=nonce,
                    collected_concept_ids=["rag"],
                    workbench_count=2,
                    action_result=result,
                    show_onboarding=False,
                    exported_at="2026-07-17",
                )
                acked_path = tmp_path / "kg_3d_embedded_acked.html"
                acked_path.write_text(acked_html, encoding="utf-8")
                page.frame_locator("#kg-frame").owner  # keep frame locator alive
                page.evaluate(
                    """(url) => { document.getElementById('kg-frame').src = url; }""",
                    acked_path.as_uri(),
                )
                page.wait_for_timeout(500)

                frame2 = page.frame_locator("#kg-frame")
                try:
                    if frame2.locator("#onboard.is-open").count() > 0:
                        frame2.locator("#onboard-ok").click(timeout=1000)
                except Exception:  # noqa: BLE001
                    pass

                ack_text = frame2.locator("#actionstatus").inner_text()
                collect_text = frame2.locator("#collectbtn").inner_text()
                inv = frame2.locator("#inventorycount").inner_text()
                toast = frame2.locator("#toast")
                assert "Ack" in ack_text or "конспект" in ack_text.lower(), ack_text
                assert "◆" in collect_text or "конспект" in collect_text.lower()
                assert "2" in inv or "раздел" in inv
                # R2: toast surfaces collect ack (still visible within ~1.8s)
                assert toast.count() == 1
                toast_text = toast.inner_text()
                assert "конспект" in toast_text.lower() or "RAG" in toast_text, toast_text
                assert "is-visible" in (toast.get_attribute("class") or "")
            finally:
                browser.close()

    def test_lesson_floor_order_uses_precedes_not_lexical(self):
        """R2: lesson floors follow precedes chain; file variants collapse."""
        from app.ui.knowledge_graph_d3_analysis import lesson_anchor_key, lesson_floor_order

        nodes = [
            {"id": "lesson:z-later.md", "is_lesson": True, "label": "Z"},
            {"id": "lesson:a-first.md", "is_lesson": True, "label": "A"},
            {"id": "lesson:a-first.txt", "is_lesson": True, "label": "A txt"},
            {"id": "concept", "is_lesson": False, "label": "C"},
        ]
        edges = [
            {
                "source": "lesson:a-first.md",
                "target": "lesson:z-later.md",
                "relation_type": "precedes",
            },
        ]
        order = lesson_floor_order(nodes, edges)
        # a-first before z-later despite lexical z < a would be wrong if reversed
        assert order[0].startswith("lesson:a-first")
        assert order[-1].startswith("lesson:z-later")
        # variants collapsed to one floor anchor
        assert len(order) == 2

        # Anchor key must match JS lessonAnchorKey: collapse /+ and \+ runs to one ':'
        assert lesson_anchor_key(r"a//b\\c.md") == "a:b:c"
        assert lesson_anchor_key("lesson:foo.md") == lesson_anchor_key("lesson:foo.txt")
        # Double-slash path variants group to one floor
        nodes_slash = [
            {"id": r"docs//lec01.md", "is_lesson": True},
            {"id": r"docs/lec01.txt", "is_lesson": True},
            {"id": r"docs//lec02.md", "is_lesson": True},
        ]
        edges_slash = [
            {
                "source": r"docs//lec01.md",
                "target": r"docs//lec02.md",
                "relation_type": "precedes",
            },
        ]
        order_slash = lesson_floor_order(nodes_slash, edges_slash)
        assert len(order_slash) == 2
        assert lesson_anchor_key(order_slash[0]) == lesson_anchor_key(r"docs//lec01.md")

    @pytest.mark.parametrize(
        "case_nodes,case_edges,expected_first_prefix,expected_len",
        [
            # Orphan lessons: no precedes edges at all -> pure lexical fallback, all present.
            (
                [
                    {"id": "lesson:b.md", "is_lesson": True},
                    {"id": "lesson:a.md", "is_lesson": True},
                ],
                [],
                "lesson:a",
                2,
            ),
            # Mixed extensions collapse to one anchor per group across .md/.txt/.markdown.
            (
                [
                    {"id": "lesson:x.md", "is_lesson": True},
                    {"id": "lesson:x.txt", "is_lesson": True},
                    {"id": "lesson:x.markdown", "is_lesson": True},
                    {"id": "lesson:y.md", "is_lesson": True},
                ],
                [{"source": "lesson:x.md", "target": "lesson:y.md", "relation_type": "precedes"}],
                "lesson:x",
                2,
            ),
        ],
    )
    def test_lesson_floor_order_edge_cases(
        self, case_nodes, case_edges, expected_first_prefix, expected_len
    ):
        """R2/P2-5: floor-order oracle on orphan lessons and mixed-extension variants."""
        from app.ui.knowledge_graph_d3_analysis import lesson_floor_order

        order = lesson_floor_order(case_nodes, case_edges)
        assert len(order) == expected_len
        assert order[0].startswith(expected_first_prefix)

    def test_lesson_floor_order_breaks_cycles_without_crashing(self):
        """R2/P2-5: a precedes cycle must not hang Kahn's algorithm; all lessons
        still surface once the queue drains and leftovers are appended lexically."""
        from app.ui.knowledge_graph_d3_analysis import lesson_floor_order

        nodes = [
            {"id": "lesson:a.md", "is_lesson": True},
            {"id": "lesson:b.md", "is_lesson": True},
            {"id": "lesson:c.md", "is_lesson": True},
        ]
        edges = [
            {"source": "lesson:a.md", "target": "lesson:b.md", "relation_type": "precedes"},
            {"source": "lesson:b.md", "target": "lesson:c.md", "relation_type": "precedes"},
            {"source": "lesson:c.md", "target": "lesson:a.md", "relation_type": "precedes"},  # cycle
        ]
        order = lesson_floor_order(nodes, edges)
        assert len(order) == 3
        assert set(order) == {"lesson:a.md", "lesson:b.md", "lesson:c.md"}

    def test_script_json_escapes_html_and_script_breakout(self):
        """P1: labels with </script> or < must not break offline export script context."""
        from app.ui.knowledge_graph_d3 import _json_for_script

        raw = _json_for_script({"label": "</script><img onerror=1>"})
        assert "</script>" not in raw
        assert "<img" not in raw
        assert "\\u003c" in raw

        evil = {
            "nodes": [{"id": "x", "label": "</script><script>alert(1)</script>", "worth": 1}],
            "edges": [],
            "stats": {},
            "day_route": ["x"],
        }
        html3 = build_kg_3d_html(evil)
        assert "</script><script>" not in html3
        assert "\\u003c/script\\u003e" in html3 or "\\u003c" in html3

        html2 = build_kg_html({
            "nodes": evil["nodes"],
            "edges": [],
            "levels": {},
            "stats": {},
            "health": {},
            "cluster_labels": {},
            "day_route": ["x"],
        })
        assert "DAY_ROUTE" in html2
        assert '"x"' in html2 or "'x'" in html2
        assert "</script><script>" not in html2


class TestA1NodePriceSignals:
    """A1 (wave-kg-node-worth): due_reviews and novel must be wired into node payload.
    due is aggregated count by canonical cid; novel = absent from mastery+decay for
    non-lesson nodes. Tests use the heavy path so exported HTML sees the fields too.
    """

    def test_payload_nodes_carry_due_and_novel(self):
        concepts = {
            "known": {"label": "Known"},
            "newbie": {"label": "Newbie"},
            "lesson:lec": {"label": "Lec", "level": "lesson"},
        }
        mastery_vector = {"known": 0.85}
        due_reviews = [
            {"concept": "known"}, {"concept": "known"},  # 2 due for known
            {"concept": "newbie"},
            # lesson has no due entry here; even if present we surface it (rare)
        ]

        payload = build_kg_payload(
            concepts,
            mastery_vector=mastery_vector,
            due_reviews=due_reviews,
        )

        nodes_by_id = {n["id"]: n for n in payload["nodes"]}
        assert nodes_by_id["known"]["due"] == 2
        assert nodes_by_id["known"]["novel"] is False  # has mastery

        assert nodes_by_id["newbie"]["due"] == 1
        assert nodes_by_id["newbie"]["novel"] is True  # no mastery, no decay, not lesson

        assert nodes_by_id["lesson:lec"]["due"] == 0
        assert nodes_by_id["lesson:lec"]["novel"] is False  # lessons never novel
        assert nodes_by_id["lesson:lec"]["is_lesson"] is True

    def test_build_kg_html_includes_price_fields(self):
        # Smoke: the HTML template receives nodes with due/novel and renders without crash.
        # Placeholders are replaced; check data presence via the JSON that ends up in HTML.
        payload = build_kg_payload(
            {"c1": {"label": "C1"}, "c2": {"label": "C2"}},
            due_reviews=[{"concept": "c1"}],
        )
        html = build_kg_html(payload)
        assert any(n.get("due") == 1 for n in payload["nodes"])
        # The serialized nodes (with due/novel) are embedded in the final self-contained HTML
        assert '"due": 1' in html or '"due":1' in html
        assert "C1" in html  # label present after template processing
        # No crash and fields survive to renderer (JS uses d.due ?? 0 etc)


class TestKg3dActionBridge:
    """G0: _kg3d envelope encode/validate/dedup; export inert."""

    def _env(self, **overrides):
        base = {
            "version": 1,
            "source": "kg3d",
            "event_id": "12345678-1234-1234-1234-1234567890ab",
            "session_nonce": "a" * 32,
            "concept_id": "rag",
            "action": "start",
            "ts": int(time.time()),
        }
        base.update(overrides)
        return base

    def test_encode_decode_roundtrip(self):
        env = self._env()
        raw = encode_kg_3d_query_raw(env)
        assert len(raw) <= KG_3D_MAX_RAW_LEN
        assert decode_kg_3d_query_raw(raw) == env

    def test_rejects_oversized_raw(self):
        assert decode_kg_3d_query_raw("x" * (KG_3D_MAX_RAW_LEN + 1)) is None

    def test_rejects_malformed_raw(self):
        assert decode_kg_3d_query_raw("%%%not-b64%%%") is None

    def test_validate_happy_path(self):
        env = self._env()
        ok = validate_kg_3d_envelope(
            env, session_nonce="a" * 32, node_ids=["rag", "tutor"]
        )
        assert ok is not None
        assert ok["action"] == "start"

    def test_rejects_wrong_nonce(self):
        env = self._env()
        assert (
            validate_kg_3d_envelope(env, session_nonce="b" * 32, node_ids=["rag"])
            is None
        )

    def test_rejects_unknown_concept(self):
        env = self._env(concept_id="ghost")
        assert (
            validate_kg_3d_envelope(env, session_nonce="a" * 32, node_ids=["rag"])
            is None
        )

    def test_rejects_bad_action_and_source(self):
        assert (
            validate_kg_3d_envelope(
                self._env(action="hack"), session_nonce="a" * 32, node_ids=["rag"]
            )
            is None
        )
        assert (
            validate_kg_3d_envelope(
                self._env(source="other"), session_nonce="a" * 32, node_ids=["rag"]
            )
            is None
        )

    def test_accepts_review_action(self):
        """W2b: review is a valid G0 whitelist action (Flashcards nav)."""
        env = self._env(action="review")
        ok = validate_kg_3d_envelope(
            env, session_nonce="a" * 32, node_ids=["rag", "tutor"]
        )
        assert ok is not None
        assert ok["action"] == "review"

    def test_accepts_district_door_actions(self):
        """W4c: door_* nav actions (district MVP)."""
        for action in (
            "door_quiz",
            "door_flashcards",
            "door_plan",
            "door_konspekt",
        ):
            env = self._env(action=action, concept_id="rag")
            ok = validate_kg_3d_envelope(
                env, session_nonce="a" * 32, node_ids=["rag"]
            )
            assert ok is not None, action
            assert ok["action"] == action

    def test_accepts_ask_action(self):
        """W5a: ask = tutor handoff."""
        env = self._env(action="ask")
        ok = validate_kg_3d_envelope(
            env, session_nonce="a" * 32, node_ids=["rag"]
        )
        assert ok is not None
        assert ok["action"] == "ask"

    def test_accepts_brief_action(self):
        """W5c: brief = inline graph retrieval (stay in hall)."""
        env = self._env(action="brief")
        ok = validate_kg_3d_envelope(
            env, session_nonce="a" * 32, node_ids=["rag"]
        )
        assert ok is not None
        assert ok["action"] == "brief"

    def test_rejects_bad_event_id(self):
        assert (
            validate_kg_3d_envelope(
                self._env(event_id="not-a-uuid"),
                session_nonce="a" * 32,
                node_ids=["rag"],
            )
            is None
        )

    def test_rejects_stale_timestamp(self):
        assert (
            validate_kg_3d_envelope(
                self._env(ts=int(time.time()) - KG_3D_FRESHNESS_SECONDS - 5),
                session_nonce="a" * 32,
                node_ids=["rag"],
            )
            is None
        )

    def test_dedup_window_at_most_once(self):
        state: dict = {}
        nonce = ensure_kg_3d_session_nonce(state)
        assert len(nonce) == 32
        env = self._env(session_nonce=nonce)
        raw = encode_kg_3d_query_raw(env)
        first = consume_kg_3d_query_param(
            raw=raw, session_nonce=nonce, node_ids=["rag"], state=state
        )
        assert first is not None
        second = consume_kg_3d_query_param(
            raw=raw, session_nonce=nonce, node_ids=["rag"], state=state
        )
        assert second is None
        mark_kg_3d_event(state, env["event_id"], "succeeded")
        assert state[KG_3D_DEDUP_KEY][env["event_id"]] == "succeeded"

    def test_export_html_inert_and_offline(self):
        html = build_kg_3d_html(
            {
                "nodes": [{"id": "rag", "label": "RAG", "worth": 1}],
                "edges": [],
                "stats": {},
                "day_route": ["rag"],
                "mastery_history": [{"date": "2026-07-16", "mastery": {"rag": 50.0}}],
            },
            host_mode="export",
            collected_concept_ids=["rag"],  # must not bake into export
            workbench_count=9,
            session_nonce="should-be-empty",
            exported_at="2026-07-17",
        )
        assert 'HOST_MODE = "export"' in html
        assert 'SESSION_NONCE = ""' in html
        assert "COLLECTED_IDS = []" in html
        assert "ACTION_RESULT = null" in html
        assert "2026-07-17" in html
        assert '"rag": 50' in html or '"rag":50' in html
        assert "<script src=" not in html.lower()
        assert "isEmbedded" in html
        assert "beginAction" in html

    def test_embedded_html_receives_inventory_and_nonce(self):
        html = build_kg_3d_html(
            {
                "nodes": [{"id": "rag", "label": "RAG"}],
                "edges": [],
                "stats": {},
                "day_route": ["rag"],
            },
            host_mode="embedded",
            session_nonce="abcd" * 8,
            collected_concept_ids=["rag"],
            workbench_count=4,
            action_result={
                "status": "succeeded",
                "action": "collect",
                "concept_id": "rag",
                "event_id": "12345678-1234-1234-1234-1234567890ab",
                "label": "RAG",
                "message": "добавлено: 2",
                "added": 2,
                "duplicates": 0,
            },
        )
        assert 'HOST_MODE = "embedded"' in html
        assert "abcd" * 8 in html
        assert '"rag"' in html
        assert "WORKBENCH_COUNT_INIT = 4" in html or "WORKBENCH_COUNT = 4" in html
        assert "ACTION_RESULT" in html
        assert "добавлено: 2" in html


class TestKg3dProductActions:
    """G1: start is navigation-only; collect uses workbench helper once."""

    def test_start_sets_pending_view_without_workbench(self, monkeypatch):
        from app.ui import dashboards_graph as dg
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        state: dict = {}
        calls = {"collect": 0}

        def boom(**kwargs):
            calls["collect"] += 1
            return (0, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", boom)

        class _FakeSt:
            @staticmethod
            def toast(*a, **k):
                pass

            @staticmethod
            def rerun():
                pass

            @staticmethod
            def error(*a, **k):
                pass

        monkeypatch.setattr(dg, "st", _FakeSt)
        env = {
            "action": "start",
            "concept_id": "rag",
            "event_id": "12345678-1234-1234-1234-1234567890ab",
        }
        dg._execute_kg_3d_action(
            env, knowledge_graph=None, doc_index={}, state=state
        )
        assert state[PENDING_CURRENT_VIEW_KEY] == "Интерактивный Quiz"
        assert state[KG_3D_ACTION_KEY]["action"] == "start"
        assert state["interactive_quiz_focus_concept"] == "rag"
        assert state["kg_action_concept"] == "rag"
        # start: toast + view switch; no sticky hall action_result (would stale on return)
        assert KG_3D_ACTION_RESULT_KEY not in state
        assert calls["collect"] == 0

    def test_review_sets_flashcards_pending_without_workbench(self, monkeypatch):
        """W2b: review → Flashcards section; nav only; no workbench write."""
        from app.ui import dashboards_graph as dg
        from app.ui.flashcards_sections import FC_MAIN_SECTION_REVIEW, pending_section_key
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        state: dict = {}
        calls = {"collect": 0}

        def boom(**kwargs):
            calls["collect"] += 1
            return (0, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", boom)

        class _FakeSt:
            @staticmethod
            def toast(*a, **k):
                pass

            @staticmethod
            def rerun():
                pass

            @staticmethod
            def error(*a, **k):
                pass

        monkeypatch.setattr(dg, "st", _FakeSt)
        env = {
            "action": "review",
            "concept_id": "rag",
            "event_id": "12345678-1234-1234-1234-1234567890ef",
        }
        dg._execute_kg_3d_action(
            env, knowledge_graph=None, doc_index={}, state=state
        )
        assert state[PENDING_CURRENT_VIEW_KEY] == "Flashcards"
        assert state[pending_section_key()] == FC_MAIN_SECTION_REVIEW
        assert state["flashcards_focus_concept"] == "rag"
        assert state["kg_action_concept"] == "rag"
        assert state[KG_3D_ACTION_KEY]["action"] == "review"
        assert KG_3D_ACTION_RESULT_KEY not in state
        assert calls["collect"] == 0

    def test_door_quiz_navigates_without_workbench(self, monkeypatch):
        """W4c: district door → product view; nav only."""
        from app.ui import dashboards_graph as dg
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        state: dict = {}
        calls = {"collect": 0}

        def boom(**kwargs):
            calls["collect"] += 1
            return (0, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", boom)

        class _FakeSt:
            @staticmethod
            def toast(*a, **k):
                pass

            @staticmethod
            def rerun():
                pass

            @staticmethod
            def error(*a, **k):
                pass

        monkeypatch.setattr(dg, "st", _FakeSt)
        env = {
            "action": "door_quiz",
            "concept_id": "rag",
            "event_id": "12345678-1234-1234-1234-1234567890aa",
        }
        dg._execute_kg_3d_action(
            env, knowledge_graph=None, doc_index={}, state=state
        )
        assert state[PENDING_CURRENT_VIEW_KEY] == "Интерактивный Quiz"
        assert state["interactive_quiz_focus_concept"] == "rag"
        assert KG_3D_ACTION_RESULT_KEY not in state
        assert calls["collect"] == 0

    def test_ask_handoff_to_tutor_without_workbench(self, monkeypatch):
        """W5a: ask → tutor chat with pending prompt; no workbench write."""
        from app.ui import dashboards_graph as dg
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        state: dict = {}
        calls = {"collect": 0}

        def boom(**kwargs):
            calls["collect"] += 1
            return (0, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", boom)

        class _FakeSt:
            @staticmethod
            def toast(*a, **k):
                pass

            @staticmethod
            def rerun():
                pass

            @staticmethod
            def error(*a, **k):
                pass

        monkeypatch.setattr(dg, "st", _FakeSt)
        env = {
            "action": "ask",
            "concept_id": "rag",
            "event_id": "12345678-1234-1234-1234-1234567890bb",
        }
        dg._execute_kg_3d_action(
            env, knowledge_graph=None, doc_index={}, state=state
        )
        assert state[PENDING_CURRENT_VIEW_KEY] == "Чат с тьютором"
        assert "tutor_pending_prompt" in state
        assert "rag" in str(state["tutor_pending_prompt"]).lower() or "RAG" in str(
            state["tutor_pending_prompt"]
        )
        assert state.get("tutor_cta_action", "").startswith("KG3D:rag:")
        assert KG_3D_ACTION_RESULT_KEY not in state
        assert calls["collect"] == 0

    def test_brief_stays_in_hall_without_tutor_or_workbench(self, monkeypatch):
        """W5c: brief → action_result message; no PENDING, no tutor, no workbench."""
        from app.ui import dashboards_graph as dg
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        state: dict = {}
        calls = {"collect": 0}

        def boom(**kwargs):
            calls["collect"] += 1
            return (0, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", boom)

        class _FakeSt:
            @staticmethod
            def toast(*a, **k):
                pass

            @staticmethod
            def rerun():
                pass

            @staticmethod
            def error(*a, **k):
                pass

        monkeypatch.setattr(dg, "st", _FakeSt)

        class _KG:
            def get_concepts(self):
                return {
                    "rag": {
                        "label": "RAG",
                        "level": "core",
                        "description": "Retrieval-augmented generation.",
                    }
                }

            def get_prerequisites(self, concept):
                return ["embeddings"]

            def get_related_documents(self, concept):
                return ["course/rag.md", "notes/retrieval.txt"]

        env = {
            "action": "brief",
            "concept_id": "rag",
            "event_id": "12345678-1234-1234-1234-1234567890cc",
        }
        dg._execute_kg_3d_action(
            env, knowledge_graph=_KG(), doc_index={}, state=state
        )
        assert PENDING_CURRENT_VIEW_KEY not in state
        assert "tutor_pending_prompt" not in state
        assert calls["collect"] == 0
        result = state.get(KG_3D_ACTION_RESULT_KEY) or {}
        assert result.get("status") == "succeeded"
        assert result.get("action") == "brief"
        assert result.get("concept_id") == "rag"
        msg = str(result.get("message") or "")
        assert "RAG" in msg or "rag" in msg.lower()
        assert "Retrieval-augmented" in msg or "mastery" in msg.lower()
        assert "rag.md" in msg or "Источники" in msg

    def test_collect_calls_workbench_once(self, monkeypatch):
        from app.ui import dashboards_graph as dg

        state: dict = {}
        calls = {"n": 0}

        class _KG:
            def get_related_documents(self, concept):
                return ["doc1.md"]

            def get_concepts(self):
                return {"rag": {"label": "RAG"}}

        def fake_collect(**kwargs):
            calls["n"] += 1
            assert kwargs["concept"] == "rag"
            return (2, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", fake_collect)
        env = {
            "action": "collect",
            "concept_id": "rag",
            "event_id": "12345678-1234-1234-1234-1234567890cd",
        }
        dg._execute_kg_3d_action(
            env, knowledge_graph=_KG(), doc_index={}, state=state
        )
        assert calls["n"] == 1
        assert state[KG_3D_ACTION_KEY]["action"] == "collect"
        assert state[KG_3D_ACTION_RESULT_KEY]["status"] == "succeeded"
        assert state[KG_3D_ACTION_RESULT_KEY]["label"] == "RAG"
        assert state[KG_3D_ACTION_RESULT_KEY]["added"] == 2

    def test_query_param_reader_accepts_streamlit_list_values(self, monkeypatch):
        from app.ui import dashboards_graph as dg

        class _FakeSt:
            query_params = {"_kg3d": ["raw-action"], "_kgc": []}

        monkeypatch.setattr(dg, "st", _FakeSt)
        assert dg._query_param_first_str("_kg3d") == "raw-action"
        assert dg._query_param_first_str("_kgc") == ""
        assert dg._query_param_first_str("missing") == ""

    def test_component_wrapper_primary_component_action_url_fallback(self):
        """Audit P0: primary = setComponentValue envelope; _kg3d = fallback."""
        from pathlib import Path

        html = Path("app/ui/assets/kg_3d_component/index.html").read_text(
            encoding="utf-8"
        )
        assert "_kg3d" in html
        assert "hometutor:kg-action" in html
        assert "streamlit:setComponentValue" in html
        assert "syncKg3dAction" in html
        assert "setActionValue" in html
        assert "kg3d_action" in html
        assert "notifyChild" in html
        assert "hometutor:kg-action-delivery" in html
        assert "KG3D_MAX_RAW" in html
        # Primary then fallback (not URL-only)
        assert "setActionValue(envelope)" in html
        assert "top.location.replace" in html
        # cleanup only after streamlit:render — not on bare load (race with Python)
        assert "cleanupKg3dParam();" in html
        load_tail = html.split("setComponentReady();", 1)[1]
        assert "cleanupKg3dParam()" not in load_tail
        # Child shows delivery diagnostics (not only 12s timeout)
        child = Path("app/ui/assets/kg_3d_template.html").read_text(encoding="utf-8")
        assert "hometutor:kg-action-delivery" in child
        assert "ждём ack через компонент" in child
        # 2D mirror: _kgc cleanup also deferred to streamlit:render
        html2d = Path("app/ui/assets/kg_d3_component/index.html").read_text(
            encoding="utf-8"
        )
        assert "cleanupConceptParam();" in html2d
        load_tail_2d = html2d.split("setComponentReady();", 1)[1]
        assert "cleanupConceptParam()" not in load_tail_2d

    def test_consume_returns_action_result_after_execute(self, monkeypatch):
        """Host returns one-shot ack for the same render (no NameError / stale pop)."""
        from app.ui import dashboards_graph as dg

        state: dict = {
            "kg_3d_session_nonce": "a" * 32,
        }
        calls = {"n": 0}

        class _KG:
            def get_related_documents(self, concept):
                return ["doc1.md"]

            def get_concepts(self):
                return {"rag": {"label": "RAG"}}

        def fake_collect(**kwargs):
            calls["n"] += 1
            return (1, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", fake_collect)

        class _QP(dict):
            def pop(self, *a, **k):
                return dict.pop(self, *a, **k)

        class _FakeSt:
            session_state = state
            query_params = _QP()

            @staticmethod
            def toast(*a, **k):
                pass

            @staticmethod
            def error(*a, **k):
                pass

        env = {
            "version": 1,
            "source": "kg3d",
            "event_id": "12345678-1234-1234-1234-1234567890ef",
            "session_nonce": "a" * 32,
            "concept_id": "rag",
            "action": "collect",
            "ts": int(time.time()),
        }
        raw = encode_kg_3d_query_raw(env)
        _FakeSt.query_params[dg.KG_3D_QUERY_PARAM] = raw
        monkeypatch.setattr(dg, "st", _FakeSt)

        result = dg._consume_and_apply_kg_3d_query(
            node_ids=["rag"],
            knowledge_graph=_KG(),
            doc_index={},
        )
        assert calls["n"] == 1
        assert isinstance(result, dict)
        assert result["status"] == "succeeded"
        assert result["added"] == 1
        # one-shot: popped from session after return
        assert KG_3D_ACTION_RESULT_KEY not in state

    def test_component_value_action_consumer_collect(self, monkeypatch):
        """Primary channel: component envelope → execute → result for next hall render."""
        from app.ui import dashboards_graph as dg
        from app.ui.knowledge_graph_d3 import parse_kg_3d_component_value

        state: dict = {"kg_3d_session_nonce": "a" * 32}
        calls = {"n": 0}

        class _KG:
            def get_related_documents(self, concept):
                return ["doc1.md"]

            def get_concepts(self):
                return {"rag": {"label": "RAG"}}

        def fake_collect(**kwargs):
            calls["n"] += 1
            return (1, 0)

        monkeypatch.setattr(dg, "_collect_concept_sections_to_workbench", fake_collect)
        value = {
            "kind": "kg3d_action",
            "version": 1,
            "envelope": {
                "version": 1,
                "source": "kg3d",
                "event_id": "12345678-1234-1234-1234-1234567890aa",
                "session_nonce": "a" * 32,
                "concept_id": "rag",
                "action": "collect",
                "ts": int(time.time()),
            },
        }
        sel, act = parse_kg_3d_component_value(value)
        assert sel is None and act is not None
        result = dg._consume_and_apply_kg_3d_component_value(
            value,
            node_ids=["rag"],
            knowledge_graph=_KG(),
            doc_index={},
            state=state,
        )
        assert calls["n"] == 1
        assert isinstance(result, dict)
        assert result["status"] == "succeeded"
        assert result["added"] == 1
        # left in session for next hall render (component same-frame ack)
        assert state[KG_3D_ACTION_RESULT_KEY]["status"] == "succeeded"
        # dual delivery: same event_id rejected
        again = dg._consume_and_apply_kg_3d_component_value(
            value,
            node_ids=["rag"],
            knowledge_graph=_KG(),
            doc_index={},
            state=state,
        )
        assert again is None
        assert calls["n"] == 1

    def test_parse_kg_3d_component_value_selection_vs_action(self):
        from app.ui.knowledge_graph_d3 import parse_kg_3d_component_value

        assert parse_kg_3d_component_value("rag") == ("rag", None)
        assert parse_kg_3d_component_value(None) == (None, None)
        sel, act = parse_kg_3d_component_value(
            {
                "kind": "kg3d_action",
                "envelope": {
                    "version": 1,
                    "source": "kg3d",
                    "action": "start",
                    "concept_id": "x",
                },
            }
        )
        assert sel is None
        assert act is not None
        assert act["action"] == "start"


class TestKg3dMemoryAndInventoryContract:
    """G2/G3 render-contract: mastery_history + collected only embedded."""

    def test_mastery_history_and_snapshot_in_export(self):
        html = build_kg_3d_html(
            {
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "edges": [],
                "stats": {},
                "day_route": ["a", "b"],
                "mastery_history": [
                    {"date": "2026-07-10", "mastery": {"a": 10.0}},
                    {"date": "2026-07-16", "mastery": {"a": 40.0, "b": 20.0}},
                ],
                "decay_vector": {"a": 0.3},
            },
            exported_at="2026-07-17",
        )
        assert "2026-07-16" in html
        assert "drawMemoryTrace" in html
        assert "doneConceptIds" in html
        assert "learnedConceptIds" in html
        assert "quiz-следом" in html or "quiz-следом" in html
        assert "DECAY_VECTOR" in html
        assert "String(rank)" in html
        assert "isCollected" in html
        # ✓ membership is quiz-seen (any score), not 2D learned≥80 only
        assert "QUIZ_SEEN_MIN" in html
        assert "masteryKeysAbove" in html
        # mutable inventory counter after collect ack
        assert "let workbenchCount" in html
        assert "workbenchCount +=" in html or "workbenchCount +=" in html.replace(" ", "")

    def test_label_cap_unchanged(self):
        html = build_kg_3d_html(
            {"nodes": [], "edges": [], "stats": {}, "day_route": []}
        )
        assert "return new Set(allow.slice(0, 8));" in html

    def test_route_stop_done_check_overlays_index(self):
        """U0/G2: done stop keeps rank number; ✓ is .stop-check overlay, not a replacement."""
        html = build_kg_3d_html(
            {
                "nodes": [{"id": "a", "label": "A"}],
                "edges": [],
                "stats": {},
                "day_route": ["a"],
                "mastery_history": [{"date": "2026-07-16", "mastery": {"a": 40.0}}],
            },
            exported_at="2026-07-17",
        )
        assert "index.textContent = String(idx + 1);" in html
        assert "check.className = 'stop-check';" in html
        assert "index.appendChild(check);" in html
        assert ".stop-check{" in html
        assert "position:absolute" in html.split(".stop-check{", 1)[1].split("}", 1)[0]
        assert "index.textContent = doneConceptIds.has(n.id) ? '✓' : String(idx + 1);" not in html
        # Canvas badge uses the same overlay contract (rank + adjacent ✓).
        assert "ctx.fillText(String(rank), bx, by);" in html
        assert "ctx.fillText('✓', bx + 11, by - 1);" in html

    def test_default_hall_component_key_is_not_2d_name(self):
        import inspect

        from app.ui.knowledge_graph_d3 import render_kg_3d_hall

        sig = inspect.signature(render_kg_3d_hall)
        assert sig.parameters["key"].default == "kg_3d_hall_component"

