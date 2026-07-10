"""Core contracts for the agent loop (Wave 1).

Design rules (docs/agent_roadmap.md §2.2–2.3, Урок 2/5):
- ``args`` are always strict Pydantic models (``extra="forbid"``); the model
  can never supply ``user_id``/``session_id`` — those are injected by the
  harness via :class:`ToolContext` (least privilege).
- Every stop produces an explicit :class:`StopReason`.
- No persistence here — trace goes into ``AgentRunResult.trace``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.models import QueryOptions


class ToolAccess(str, Enum):
    """Access level of a tool. Wave 1 registers only ``READ`` tools."""

    READ = "read"
    WRITE = "write"


class StopReason(str, Enum):
    """Explicit reason the agent loop terminated.

    Every transition to ``stopped``/``completed`` carries one of these so the
    trace is self-explanatory (Урок 4: harness owns control + stop reasons).
    """

    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    MAX_TIME = "max_time"
    MAX_TOKENS = "max_tokens"
    MAX_COST = "max_cost"
    REPEATED_TOOL_CALL = "repeated_tool_call"
    TOOL_ERROR_LIMIT = "tool_error_limit"
    INVALID_ARGS_AFTER_REPAIR = "invalid_args_after_repair"
    GUARDRAIL_TRIGGERED = "guardrail_triggered"
    UNKNOWN_TOOL = "unknown_tool"
    LLM_ERROR = "llm_error"
    INVALID_DECISION = "invalid_decision"

    @property
    def is_success(self) -> bool:
        return self is StopReason.COMPLETED


class AgentState(str, Enum):
    """FSM states for :class:`AgentRunner` (docs/agent_roadmap.md §2.2)."""

    RUNNING = "running"
    TOOL_CALL = "tool_call"
    REPAIRING = "repairing"
    STOPPED = "stopped"
    COMPLETED = "completed"


class ToolArgModel(BaseModel):
    """Base for all tool argument schemas.

    ``extra="forbid"`` ensures the model cannot smuggle ``user_id`` /
    ``session_id`` or any undocumented field (least privilege, Урок 5).
    """

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolSpec:
    """Declarative description of one agent tool (Урок 2: tools = contracts).

    Attributes:
        name: dotted tool id, e.g. ``"rag.search"``.
        description: human/LLM-readable summary of what the tool does.
        when_to_use: guidance on when the model should pick this tool.
        args_schema: strict Pydantic model class for the tool's arguments.
        access: ``read`` or ``write``. Wave 1 = ``read`` only.
        idempotent: whether repeated identical calls are safe (write tools).
        limits: declarative caps (e.g. ``max_result_chars``) consumed by the
            runner when truncating tool output for the context window.
    """

    name: str
    description: str
    when_to_use: str
    args_schema: type[BaseModel]
    access: ToolAccess = ToolAccess.READ
    idempotent: bool = False
    limits: dict[str, Any] = field(default_factory=dict)

    @property
    def is_read_only(self) -> bool:
        return self.access is ToolAccess.READ


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a single tool invocation.

    Either ``ok=True`` with ``data``, or ``ok=False`` with ``error``.
    ``meta`` carries optional structured metadata (e.g. ``sources``,
    ``row_count``) consumed by the runner.
    """

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, data: Any = None, **meta: Any) -> "ToolResult":
        return cls(ok=True, data=data, meta=dict(meta))

    @classmethod
    def failure(cls, error: str, **meta: Any) -> "ToolResult":
        return cls(ok=False, error=error, meta=dict(meta))


@dataclass(frozen=True)
class ToolContext:
    """Harness-injected context for tool handlers.

    The model never sees or controls ``user_id`` / ``session_id`` — they are
    injected here from the authenticated request / query options.
    """

    user_id: str
    question: str
    query_options: "QueryOptions"
    session_id: str | None = None


ToolHandler = Callable[[ToolContext, BaseModel], ToolResult]


@dataclass(frozen=True)
class StopDecision:
    """Verdict from the stop controller."""

    stop: bool
    reason: StopReason | None = None
    detail: str = ""

    @classmethod
    def continue_run(cls) -> "StopDecision":
        return cls(stop=False)

    @classmethod
    def halt(cls, reason: StopReason, detail: str = "") -> "StopDecision":
        return cls(stop=True, reason=reason, detail=detail)


@dataclass
class AgentStep:
    """One recorded step of the agent loop (for trace/debug)."""

    step_index: int
    state: AgentState
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_args_valid: bool | None = None
    tool_result: ToolResult | None = None
    decision_raw: Any = None
    error: str | None = None
    repair_attempt: bool = False


@dataclass
class AgentRunResult:
    """Final output of :meth:`AgentRunner.run`."""

    answer: str
    sources: list[dict[str, Any]]
    steps: list[AgentStep]
    stop_reason: StopReason
    state: AgentState
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.stop_reason.is_success


__all__ = [
    "AgentRunResult",
    "AgentState",
    "AgentStep",
    "StopDecision",
    "StopReason",
    "ToolAccess",
    "ToolArgModel",
    "ToolContext",
    "ToolHandler",
    "ToolResult",
    "ToolSpec",
]
