"""B4 Agent dispatch — unit + contract + integration tests.

Verifies: agent tile removed from primary tiles, composition intents dispatch
to agent when AGENT_ENABLED=true and fallback to tutor when false, simple
intents never go to agent, feature registry gate, no auto-save cards.
"""

from __future__ import annotations

from pathlib import Path


# ── source-level contracts ──────────────────────────────────────────────────

class TestAgentDispatchSourceContracts:
    def test_agent_tile_removed_from_primary(self) -> None:
        src = (Path("app/ui/mission_control.py")).read_text(encoding="utf-8")
        fn = src.split("def _tile_definitions")[1].split("\ndef ")[0]
        assert "agent_session" not in fn, "B4: agent tile must not be in primary tiles"

    def test_composition_intents_in_tuple(self) -> None:
        from app.ui.learning_intents import INTENTS
        ids = {i.intent_id for i in INTENTS}
        assert "compose_session" in ids
        assert "find_gap_practice" in ids
        assert "connect_graph_quiz" in ids

    def test_dispatch_to_agent_exported(self) -> None:
        from app.ui.learning_intents import dispatch_to_agent
        assert callable(dispatch_to_agent)

    def test_agent_view_still_in_main(self) -> None:
        """B4: agent view code remains in main.py for «Ещё» access."""
        src = (Path("app/ui/main.py")).read_text(encoding="utf-8")
        assert 'selected_view == "Собрать учебную сессию"' in src

    def test_agent_view_has_card_save_confirmation(self) -> None:
        """B4: agent does not save cards without approval."""
        src = (Path("app/ui/main.py")).read_text(encoding="utf-8")
        assert "Сохранить" in src
        assert "save_quiz_result" not in src

    def test_feature_registry_agent_gate(self) -> None:
        src = (Path("app/ui/feature_registry.py")).read_text(encoding="utf-8")
        assert 'view:agent_session' in src
        assert 'agent_enabled' in src

    def test_composition_prompts_in_prompt_layer(self) -> None:
        """P1: composition prompts must live in app/prompts, not UI."""
        from app.prompts import AGENT_COMPOSITION_INTENT_PROMPTS
        assert "compose_session" in AGENT_COMPOSITION_INTENT_PROMPTS
        assert "find_gap_practice" in AGENT_COMPOSITION_INTENT_PROMPTS
        assert "connect_graph_quiz" in AGENT_COMPOSITION_INTENT_PROMPTS
        for key in ("compose_session", "find_gap_practice", "connect_graph_quiz"):
            assert "{topic}" in AGENT_COMPOSITION_INTENT_PROMPTS[key]

    def test_composition_prompts_not_hardcoded_in_ui(self) -> None:
        """P1: learning_intents.py must not contain hardcoded composition prompt text."""
        src = (Path("app/ui/learning_intents.py")).read_text(encoding="utf-8")
        fn = src.split("def apply_learning_intent")[1].split("\ndef ")[0]
        assert "подбери нужные инструменты" not in fn
        assert "AGENT_COMPOSITION_INTENT_PROMPTS" in fn

    def test_composition_prompt_scenario_routing(self) -> None:
        """P1 regression: each composition prompt must route to the correct scenario.
        compose_session → STUDY_SESSION (no konspekt/graph markers)
        find_gap_practice → GRAPH_GAP_FINDER
        connect_graph_quiz → LIVING_KONSPEKT_COACH
        """
        from app.prompts import AGENT_COMPOSITION_INTENT_PROMPTS
        from app.agent.scenarios import get_agent_scenario

        scenarios = {}
        for intent_id in ("compose_session", "find_gap_practice", "connect_graph_quiz"):
            prompt = AGENT_COMPOSITION_INTENT_PROMPTS[intent_id].format(topic="Linear Algebra")
            scenario = get_agent_scenario(prompt)
            assert scenario is not None, f"{intent_id}: no scenario matched for prompt: {prompt!r}"
            scenarios[intent_id] = scenario.scenario_id

        assert scenarios["compose_session"] == "study_session", (
            f"compose_session routed to {scenarios['compose_session']}, expected study_session"
        )
        assert scenarios["find_gap_practice"] == "graph_gap_finder", (
            f"find_gap_practice routed to {scenarios['find_gap_practice']}, expected graph_gap_finder"
        )
        assert scenarios["connect_graph_quiz"] == "living_konspekt_coach", (
            f"connect_graph_quiz routed to {scenarios['connect_graph_quiz']}, expected living_konspekt_coach"
        )

    def test_global_nav_still_has_agent(self) -> None:
        """B4: agent still accessible via «Ещё» in global navigation."""
        src = (Path("app/ui/global_navigation.py")).read_text(encoding="utf-8")
        assert "Собрать учебную сессию" in src


# ── dispatch_to_agent behavioral ────────────────────────────────────────────

class TestDispatchToAgentBehavioral:
    def test_dispatch_agent_when_enabled(self, monkeypatch) -> None:
        import types
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)

        orig = _cfg._settings
        _cfg._settings = types.SimpleNamespace(agent_enabled=True)
        try:
            from app.ui.learning_intents import dispatch_to_agent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            dispatch_to_agent("Собери сессию по Machine Learning", topic_hint="ML", intent_id="compose_session")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Собрать учебную сессию"
            assert st.session_state["agent_session_input"] == "Собери сессию по Machine Learning"
            assert st.session_state["current_topic"] == "ML"
            assert st.session_state.get("tutor_pending_prompt") is None
        finally:
            _cfg._settings = orig

    def test_dispatch_fallback_tutor_when_disabled(self, monkeypatch) -> None:
        import types
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)
        monkeypatch.setattr("app.ui.learning_intents._tutor_setup", lambda: None)

        orig = _cfg._settings
        _cfg._settings = types.SimpleNamespace(agent_enabled=False)
        try:
            from app.ui.learning_intents import dispatch_to_agent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            dispatch_to_agent("Найди пробел по Python", topic_hint="Python")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Чат с тьютором"
            assert st.session_state["tutor_pending_prompt"] == "Найди пробел по Python"
            assert st.session_state.get("agent_session_input") is None
        finally:
            _cfg._settings = orig

    def test_dispatch_fallback_on_config_error(self, monkeypatch) -> None:
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)
        monkeypatch.setattr("app.ui.learning_intents._tutor_setup", lambda: None)

        orig = _cfg._settings
        _cfg._settings = None
        try:
            from app.ui.learning_intents import dispatch_to_agent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            dispatch_to_agent("Собери сессию")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Чат с тьютором"
        finally:
            _cfg._settings = orig


# ── simple intents never go to agent ────────────────────────────────────────

class TestSimpleIntentsNeverAgent:
    def test_simpler_always_to_tutor(self, monkeypatch) -> None:
        import types
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)
        monkeypatch.setattr("app.ui.learning_intents._tutor_setup", lambda: None)

        orig = _cfg._settings
        _cfg._settings = types.SimpleNamespace(agent_enabled=True)
        try:
            from app.ui.learning_intents import apply_learning_intent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            apply_learning_intent("simpler", topic_hint="Linear Algebra")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Чат с тьютором"
            assert "agent_session_input" not in st.session_state
        finally:
            _cfg._settings = orig

    def test_practice_always_to_tutor(self, monkeypatch) -> None:
        import types
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)
        monkeypatch.setattr("app.ui.learning_intents._tutor_setup", lambda: None)

        orig = _cfg._settings
        _cfg._settings = types.SimpleNamespace(agent_enabled=True)
        try:
            from app.ui.learning_intents import apply_learning_intent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            apply_learning_intent("practice", topic_hint="Calculus")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Чат с тьютором"
            assert "agent_session_input" not in st.session_state
        finally:
            _cfg._settings = orig

    def test_composition_intent_to_agent_when_enabled(self, monkeypatch) -> None:
        import types
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)

        orig = _cfg._settings
        _cfg._settings = types.SimpleNamespace(agent_enabled=True)
        try:
            from app.ui.learning_intents import apply_learning_intent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            apply_learning_intent("compose_session", topic_hint="AI Agents")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Собрать учебную сессию"
            assert "agent_session_input" in st.session_state
            assert "AI Agents" in st.session_state["agent_session_input"]
        finally:
            _cfg._settings = orig

    def test_composition_intent_fallback_when_disabled(self, monkeypatch) -> None:
        import types
        import streamlit as st
        import app.config as _cfg
        monkeypatch.setattr(st, "session_state", {"_session_tape_id": "s1"})
        monkeypatch.setattr(st, "rerun", lambda: None)
        monkeypatch.setattr("app.ui.learning_intents._tutor_setup", lambda: None)

        orig = _cfg._settings
        _cfg._settings = types.SimpleNamespace(agent_enabled=False)
        try:
            from app.ui.learning_intents import apply_learning_intent
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            apply_learning_intent("find_gap_practice", topic_hint="Rust")

            assert st.session_state[PENDING_CURRENT_VIEW_KEY] == "Чат с тьютором"
            assert "agent_session_input" not in st.session_state
        finally:
            _cfg._settings = orig


# ── tile definitions ────────────────────────────────────────────────────────

class TestAgentTileRemoved:
    def test_no_agent_in_primary_tiles(self) -> None:
        from app.ui.mission_control import _tile_definitions
        tiles = _tile_definitions(due_count=0)
        tile_ids = {t.tile_id for t in tiles}
        assert "agent_session" not in tile_ids, "B4: agent tile removed from primary"

    def test_primary_tile_count(self) -> None:
        from app.ui.mission_control import _tile_definitions
        tiles = _tile_definitions(due_count=0)
        assert len(tiles) == 8, f"expected 8 primary tiles (agent removed), got {len(tiles)}"


# ── intent palette integration ──────────────────────────────────────────────

class TestIntentPaletteAgent:
    def test_ssr_card_iterates_all_intents(self) -> None:
        src = (Path("app/ui/smart_study_next_step_card.py")).read_text(encoding="utf-8")
        assert "for i, intent in enumerate(INTENTS)" in src

    def test_composition_intents_have_sr_labels(self) -> None:
        from app.ui.learning_intents import INTENTS
        comp_intents = [i for i in INTENTS if i.intent_id in {"compose_session", "find_gap_practice", "connect_graph_quiz"}]
        assert len(comp_intents) == 3
        for ci in comp_intents:
            assert ci.sr_label
            assert ci.intent_id not in ci.sr_label
            assert len(ci.sr_label) > 10
