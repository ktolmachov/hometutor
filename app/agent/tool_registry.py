"""Tool registry for the agent loop (Wave 1: read-only tools only).

Registers the read-only tool set from the roadmap §2.3. Write tools are NOT
registered (deferred to Wave 5). Provides ``to_openai_tools()`` for the native
tools backend, though Wave 1 uses JSON-decision mode by default.
"""
from __future__ import annotations

from typing import Any

from app.agent.contracts import ToolAccess, ToolHandler, ToolSpec


class ToolRegistry:
    """Registry of tool specs and their handler callables.

    Wave 1 registers only ``access=READ`` tools. Attempting to register a write
    tool raises :class:`ValueError` to enforce the read-only invariant.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.access is ToolAccess.WRITE:
            raise ValueError(
                f"Write tool {spec.name!r} cannot be registered in Wave 1 "
                f"(read-only). Write tools are deferred to Wave 5."
            )
        if spec.name in self._specs:
            raise ValueError(f"Tool {spec.name!r} is already registered")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def get_handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self._specs.keys())

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Convert specs to OpenAI function-calling format (native tools backend).

        Not the default mode in Wave 1 (JSON-decision is), but provided for
        Wave 3 native tools support.
        """
        tools: list[dict[str, Any]] = []
        for spec in self._specs.values():
            schema = spec.args_schema.model_json_schema()
            schema = _strip_title_from_schema(schema)
            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": f"{spec.description}\n\nWhen to use: {spec.when_to_use}",
                    "parameters": schema,
                },
            })
        return tools

    def describe_tools_for_prompt(self) -> str:
        """Compact text listing of tools for the JSON-decision user prompt."""
        lines: list[str] = []
        for spec in self._specs.values():
            schema = spec.args_schema.model_json_schema()
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            param_parts: list[str] = []
            for pname, pschema in props.items():
                ptype = pschema.get("type", "any")
                desc = pschema.get("description", "")
                marker = " (required)" if pname in required else ""
                extra = f" — {desc}" if desc else ""
                param_parts.append(f"    {pname}: {ptype}{marker}{extra}")
            params_str = "\n".join(param_parts) if param_parts else "    (no parameters)"
            lines.append(
                f"- {spec.name}: {spec.description}\n"
                f"  When to use: {spec.when_to_use}\n"
                f"  Parameters:\n{params_str}"
            )
        return "\n".join(lines)


def _strip_title_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove ``title`` fields from a JSON schema (noise for the LLM)."""
    out = {k: v for k, v in schema.items() if k != "title"}
    if "properties" in out and isinstance(out["properties"], dict):
        cleaned: dict[str, Any] = {}
        for pname, pschema in out["properties"].items():
            if isinstance(pschema, dict):
                cleaned[pname] = {k: v for k, v in pschema.items() if k != "title"}
            else:
                cleaned[pname] = pschema
        out["properties"] = cleaned
    return out


def build_default_registry() -> ToolRegistry:
    """Build the Wave 1 read-only tool registry from all tool modules."""
    from app.agent.tools_flashcards import get_flashcards_tool_specs
    from app.agent.tools_learner import get_learner_tool_specs
    from app.agent.tools_quiz import get_quiz_tool_specs
    from app.agent.tools_rag import get_rag_tool_specs

    registry = ToolRegistry()
    for spec, handler in (
        *get_rag_tool_specs(),
        *get_learner_tool_specs(),
        *get_quiz_tool_specs(),
        *get_flashcards_tool_specs(),
    ):
        registry.register(spec, handler)
    return registry


__all__ = [
    "ToolRegistry",
    "build_default_registry",
]
