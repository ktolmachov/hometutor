"""Deterministic checks for the Wave 1A/1B agent golden cases."""
from __future__ import annotations

import json
from pathlib import Path

from app.agent.scenarios import (
    GRAPH_GAP_FINDER_SCENARIO,
    LIVING_KONSPEKT_COACH_SCENARIO,
    STUDY_SESSION_SCENARIO,
    build_graph_gap_report,
    build_konspekt_coach_draft,
    build_study_session_answer,
    get_agent_scenario,
)
from app.agent.tool_registry import build_default_registry


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "eval_data" / "agent_scenarios_golden_v1.json"


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_agent_golden_cases_have_valid_scenarios_and_read_only_tools():
    reg = build_default_registry()
    cases = _load_cases()

    assert {case["scenario_id"] for case in cases} == {
        "study_session",
        "graph_gap_finder",
        "living_konspekt_coach",
    }
    for case in cases:
        scenario = get_agent_scenario(case["question"])
        if case["scenario_id"] == "study_session":
            assert scenario is STUDY_SESSION_SCENARIO
        elif case["scenario_id"] == "graph_gap_finder":
            assert scenario is GRAPH_GAP_FINDER_SCENARIO
        else:
            assert scenario is LIVING_KONSPEKT_COACH_SCENARIO

        tool_names = set(case.get("required_tools_any_order") or [])
        tool_names.update(case.get("optional_tools") or [])
        for tool_name in tool_names:
            spec = reg.get_spec(tool_name)
            assert spec is not None, f"{case['id']} references unknown {tool_name}"
            assert spec.is_read_only, f"{tool_name} must stay read-only"


def test_agent_golden_sections_are_enforced_by_finalizers():
    for case in _load_cases():
        if case["scenario_id"] == "study_session":
            answer = build_study_session_answer("", [], []).answer
        elif case["scenario_id"] == "graph_gap_finder":
            answer = build_graph_gap_report("", [], []).answer
        else:
            answer = build_konspekt_coach_draft("", [], []).answer

        for section in case["required_sections"]:
            assert section in answer, f"{case['id']} missing {section}"
