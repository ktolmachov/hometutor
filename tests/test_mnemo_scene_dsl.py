"""W5b / W5b.1: scene-DSL schema, validator, presentation apply."""

from __future__ import annotations

from app.mnemo_scene_dsl import (
    SCENE_DSL_VERSION,
    SceneDslError,
    nl_to_presentation,
    parse_nl_scene_command,
    presentation_from_dsl,
    preset_presentation,
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


def test_presentation_from_dsl_is_presentation_only():
    env = validate_scene_dsl(
        {
            "version": 1,
            "command": "route_override",
            "route_override": ["rag", "tutor"],
        },
        node_ids={"rag", "tutor"},
    )
    pres = presentation_from_dsl(env)
    assert pres["domain_day_route_unchanged"] is True
    assert pres["route_override_presentation_only"] is True
    assert pres["route_override"] == ["rag", "tutor"]


def test_preset_weak_and_clear():
    weak = preset_presentation("weak")
    assert weak["filter"] == "weak"
    assert weak["domain_day_route_unchanged"] is True
    cleared = preset_presentation("clear")
    assert cleared["filter"] == ""
    assert cleared["scene_mode"] is None


def test_nl_scene_commands_safe_mapping():
    weak, err = nl_to_presentation("покажи слабое", node_ids={"rag", "agent"})
    assert err is None
    assert weak is not None
    assert weak["filter"] == "weak"
    assert weak["domain_day_route_unchanged"] is True

    calm, _ = nl_to_presentation("спокойный мир", node_ids=set())
    assert calm is not None
    assert calm["overlay"] == "calm"

    focus, _ = nl_to_presentation(
        "фокус RAG",
        node_ids={"rag", "agent"},
        node_labels={"rag": "RAG", "agent": "Agent"},
    )
    assert focus is not None
    assert focus["focus_id"] == "rag"

    bad, reason = parse_nl_scene_command("eval(alert(1))")
    assert bad is None
    assert reason == "forbidden_token"

    inj, reason2 = nl_to_presentation("<script>x</script>", node_ids={"rag"})
    assert inj is None
    assert reason2
