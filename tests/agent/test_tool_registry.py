"""Tests: tool registry exposes only read-only tools with valid strict schemas."""
from __future__ import annotations

import pytest

from app.agent.contracts import ToolAccess, ToolArgModel
from app.agent.tool_registry import ToolRegistry, build_default_registry


def test_default_registry_has_expected_read_only_tools():
    reg = build_default_registry()
    expected = {
        "rag.search",
        "rag.answer",
        "learner.get_profile",
        "cards.get_due",
        "progress.get_mastery",
        "quiz.generate",
        "cards.propose",
        "graph.inspect",
        "konspekt.inspect",
    }
    assert set(reg.tool_names) == expected


def test_all_tools_are_read_only():
    reg = build_default_registry()
    assert len(reg) > 0
    for spec in reg.specs:
        assert spec.access is ToolAccess.READ, f"{spec.name} should be read-only"


def test_no_write_tools_registered():
    reg = build_default_registry()
    for spec in reg.specs:
        assert spec.is_read_only


def test_args_schemas_are_strict_pydantic():
    """Every args model forbids extra fields (no user_id/session_id smuggling)."""
    reg = build_default_registry()
    assert len(reg) > 0
    for spec in reg.specs:
        schema_cls = spec.args_schema
        # Must be a Pydantic model
        assert hasattr(schema_cls, "model_validate"), f"{spec.name} args not Pydantic"
        # Must forbid extra fields
        config = getattr(schema_cls, "model_config", {})
        assert config.get("extra") == "forbid", (
            f"{spec.name} args_schema must use extra='forbid'"
        )


@pytest.mark.parametrize("field_name", ["user_id", "session_id", "uid", "sid"])
def test_model_cannot_supply_user_id_or_session_id(field_name):
    """user_id / session_id must not be part of any tool's args schema."""
    reg = build_default_registry()
    for spec in reg.specs:
        schema = spec.args_schema.model_json_schema()
        properties = schema.get("properties", {})
        assert field_name not in properties, (
            f"{spec.name} args must not expose {field_name}"
        )
        # extra='forbid' rejects unknown fields at runtime too
        with pytest.raises(Exception):
            spec.args_schema.model_validate({field_name: "attacker"})


def test_register_write_tool_raises():
    from pydantic import BaseModel, ConfigDict

    from app.agent.contracts import ToolSpec

    class _Args(BaseModel):
        model_config = ConfigDict(extra="forbid")
        x: int = 0

    write_spec = ToolSpec(
        name="cards.save_deck",
        description="save",
        when_to_use="never in Wave 1",
        args_schema=_Args,
        access=ToolAccess.WRITE,
    )
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="read-only"):
        reg.register(write_spec, lambda ctx, args: None)


def test_duplicate_registration_raises():
    reg = build_default_registry()
    spec = reg.get_spec("rag.search")
    handler = reg.get_handler("rag.search")
    with pytest.raises(ValueError, match="already registered"):
        reg.register(spec, handler)


def test_to_openai_tools_format():
    reg = build_default_registry()
    tools = reg.to_openai_tools()
    assert len(tools) == len(reg)
    for tool in tools:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert isinstance(fn["parameters"], dict)


def test_describe_tools_for_prompt_is_nonempty():
    reg = build_default_registry()
    desc = reg.describe_tools_for_prompt()
    assert isinstance(desc, str)
    assert "rag.search" in desc
    assert "quiz.generate" in desc
