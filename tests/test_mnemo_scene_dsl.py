"""W5b: scene-DSL schema/validator spike (no UI wiring)."""

from __future__ import annotations

from app.mnemo_scene_dsl import (
    SCENE_DSL_VERSION,
    SceneDslError,
    try_validate_scene_dsl,
    validate_scene_dsl,
)


def test_accepts_minimal_filter_command():
    ok = validate_scene_dsl(
        {"version": SCENE_DSL_VERSION, "command": "filter", "filter": "агент"},
        node_ids={"rag", "agent"},
    )
    assert ok["command"] == "filter"
    assert ok["filter"] == "агент"


def test_rejects_unknown_command_and_keys():
    bad, reason = try_validate_scene_dsl(
        {"version": 1, "command": "drop_table"},
        node_ids=set(),
    )
    assert bad is None
    assert reason == "unknown_command"

    bad2, reason2 = try_validate_scene_dsl(
        {"version": 1, "command": "focus", "mastery": 1},
        node_ids={"rag"},
    )
    assert bad2 is None
    assert reason2 and "forbidden" in reason2


def test_route_override_is_presentation_only():
    ok = validate_scene_dsl(
        {
            "version": 1,
            "command": "route_override",
            "route_override": ["rag", "tutor"],
        },
        node_ids={"rag", "tutor", "agent"},
    )
    assert ok["route_override"] == ["rag", "tutor"]
    assert ok["route_override_presentation_only"] is True


def test_unknown_node_rejected():
    try:
        validate_scene_dsl(
            {"version": 1, "command": "focus", "node_id": "nope"},
            node_ids={"rag"},
        )
        assert False, "expected SceneDslError"
    except SceneDslError as exc:
        assert "unknown_node" in str(exc)
