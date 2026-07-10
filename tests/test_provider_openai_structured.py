"""Wave 0 tests: provider structured/tool-calling support + AGENT_* config.

Covers (docs/agent_roadmap.md §Wave 0):
  * tools/tool_choice/response_format reach the chat.completions.create payload,
  * request_cache is bypassed for structured/tool kwargs (sync + async),
  * tool/response schema tokens are counted in the input-token guard estimate,
  * AGENT_* settings are wired with correct defaults and validation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from llama_index.core.base.llms.types import ChatMessage

from app import provider_openai
from app.config import Settings, reset_settings_cache
from app.provider_openai import (
    OpenAI,
    _estimate_structured_kwargs_tokens,
    _has_structured_or_tool_kwargs,
)
from app.request_cache import RequestCache

_MODEL = "gpt-4o-mini"
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Search the knowledge base for fragments about a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "top_k": {"type": "integer", "description": "Max fragments to return."},
                },
                "required": ["query"],
            },
        },
    }
]
_RESPONSE_FORMAT = {"type": "json_object"}


# ── fixtures / helpers ──────────────────────────────────────────────────────


def _fake_response(content: str = "answer") -> SimpleNamespace:
    msg = SimpleNamespace(
        role="assistant",
        content=content,
        tool_calls=None,
        audio=None,
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=msg, logprobs=None, index=0, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage, id="test", model=_MODEL)


def _make_llm(response: SimpleNamespace | None = None) -> OpenAI:
    client = MagicMock()
    client.chat.completions.create.return_value = response or _fake_response()
    return OpenAI(
        model=_MODEL,
        api_key="test-key",
        api_base="http://127.0.0.1:1234/v1",
        openai_client=client,
        reuse_client=True,
    )


def _make_async_llm(response: SimpleNamespace | None = None) -> tuple[OpenAI, MagicMock]:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response or _fake_response())
    llm = OpenAI(
        model=_MODEL,
        api_key="test-key",
        api_base="http://127.0.0.1:1234/v1",
        async_openai_client=client,
        reuse_client=True,
    )
    return llm, client


class _TrackingCache:
    """Minimal cache that records get/set calls and stores one entry."""

    def __init__(self) -> None:
        self.get_calls = 0
        self.set_calls = 0
        self._store: dict[tuple, object] = {}

    def get(self, model: str, messages: list, **kwargs):
        self.get_calls += 1
        return self._store.get((model, repr(messages)))

    def set(self, model: str, messages: list, response: object, **kwargs) -> None:
        self.set_calls += 1
        self._store[(model, repr(messages))] = response


def _patch_cache(monkeypatch, cache: _TrackingCache) -> None:
    monkeypatch.setattr(provider_openai, "get_request_cache", lambda: cache)


def _messages(text: str = "hello") -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


# ── unit tests for the helpers ──────────────────────────────────────────────


def test_structured_kwarg_detection() -> None:
    assert _has_structured_or_tool_kwargs({}) is False
    assert _has_structured_or_tool_kwargs({"temperature": 0}) is False
    assert _has_structured_or_tool_kwargs({"tools": _TOOLS}) is True
    assert _has_structured_or_tool_kwargs({"tool_choice": "auto"}) is True
    assert _has_structured_or_tool_kwargs({"response_format": _RESPONSE_FORMAT}) is True


def test_estimate_structured_kwargs_tokens_positive_for_schemas() -> None:
    assert _estimate_structured_kwargs_tokens({}, _MODEL) == 0
    tokens = _estimate_structured_kwargs_tokens({"tools": _TOOLS}, _MODEL)
    assert tokens > 0
    with_fmt = _estimate_structured_kwargs_tokens({"tools": _TOOLS, "response_format": _RESPONSE_FORMAT}, _MODEL)
    assert with_fmt > tokens


# ── payload passthrough (sync) ──────────────────────────────────────────────


def test_tools_and_tool_choice_reach_payload_sync() -> None:
    llm = _make_llm()
    llm._chat(_messages(), tools=_TOOLS, tool_choice="auto")

    create_kwargs = llm._client.chat.completions.create.call_args.kwargs
    assert create_kwargs["tools"] == _TOOLS
    assert create_kwargs["tool_choice"] == "auto"


def test_response_format_reaches_payload_sync() -> None:
    llm = _make_llm()
    llm._chat(_messages(), response_format=_RESPONSE_FORMAT)

    create_kwargs = llm._client.chat.completions.create.call_args.kwargs
    assert create_kwargs["response_format"] == _RESPONSE_FORMAT


def test_plain_kwargs_have_no_structured_keys_in_payload(monkeypatch) -> None:
    _patch_cache(monkeypatch, _TrackingCache())
    llm = _make_llm()
    llm._chat(_messages(), temperature=0.0)

    create_kwargs = llm._client.chat.completions.create.call_args.kwargs
    assert "tools" not in create_kwargs
    assert "tool_choice" not in create_kwargs
    assert "response_format" not in create_kwargs


# ── cache bypass (sync) ─────────────────────────────────────────────────────


def test_cache_bypassed_for_tools_sync(monkeypatch) -> None:
    cache = _TrackingCache()
    _patch_cache(monkeypatch, cache)
    llm = _make_llm()

    llm._chat(_messages(), tools=_TOOLS, tool_choice="auto")

    assert cache.get_calls == 0
    assert cache.set_calls == 0
    assert llm._client.chat.completions.create.call_count == 1


def test_cache_bypassed_for_response_format_sync(monkeypatch) -> None:
    cache = _TrackingCache()
    _patch_cache(monkeypatch, cache)
    llm = _make_llm()

    llm._chat(_messages(), response_format=_RESPONSE_FORMAT)

    assert cache.get_calls == 0
    assert cache.set_calls == 0


def test_cache_used_for_plain_kwargs_sync(monkeypatch) -> None:
    cache = _TrackingCache()
    _patch_cache(monkeypatch, cache)
    llm = _make_llm()
    msgs = _messages()

    llm._chat(msgs)
    assert cache.get_calls == 1
    assert cache.set_calls == 1

    # Second identical call must hit the cache and skip the provider.
    llm._chat(msgs)
    assert cache.get_calls == 2
    assert cache.set_calls == 1  # not written again
    assert llm._client.chat.completions.create.call_count == 1


# ── schema tokens counted in guard estimate ────────────────────────────────


def test_guard_sees_schema_tokens(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def _capture(tokens: int) -> None:
        captured["tokens"] = tokens

    monkeypatch.setattr(provider_openai, "check_input_tokens", _capture)
    llm = _make_llm()
    msgs = _messages("short question")

    _, input_plain, _, stats_plain = llm._guarded_message_dicts(msgs, {})
    tokens_plain = captured["tokens"]

    _, input_with_tools, _, stats_with_tools = llm._guarded_message_dicts(msgs, {"tools": _TOOLS})
    tokens_with_tools = captured["tokens"]

    assert tokens_with_tools > tokens_plain
    assert input_with_tools > input_plain
    assert stats_plain["structured_kwargs_tokens_estimate"] == 0
    assert stats_with_tools["structured_kwargs_tokens_estimate"] > 0
    assert stats_with_tools["input_tokens_estimate"] == input_with_tools
    assert stats_with_tools["message_tokens_estimate"] == stats_plain["message_tokens_estimate"]


# ── payload passthrough + cache bypass (async) ─────────────────────────────


def test_tools_reach_payload_async() -> None:
    llm, client = _make_async_llm()
    asyncio.run(llm._achat(_messages(), tools=_TOOLS, tool_choice="auto"))

    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs["tools"] == _TOOLS
    assert create_kwargs["tool_choice"] == "auto"


def test_cache_bypassed_for_tools_async(monkeypatch) -> None:
    cache = _TrackingCache()
    _patch_cache(monkeypatch, cache)
    llm, _ = _make_async_llm()

    asyncio.run(llm._achat(_messages(), tools=_TOOLS))

    assert cache.get_calls == 0
    assert cache.set_calls == 0


def test_cache_used_for_plain_kwargs_async(monkeypatch) -> None:
    cache = _TrackingCache()
    _patch_cache(monkeypatch, cache)
    llm, client = _make_async_llm()
    msgs = _messages()

    asyncio.run(llm._achat(msgs))
    assert cache.get_calls == 1
    assert cache.set_calls == 1

    asyncio.run(llm._achat(msgs))
    assert cache.get_calls == 2
    assert cache.set_calls == 1
    assert client.chat.completions.create.call_count == 1


def test_real_request_cache_distinguishes_plain_kwargs() -> None:
    cache = RequestCache(maxsize=10, ttl_seconds=60, persist=False)
    messages = [{"role": "user", "content": "hello"}]
    response = object()

    cache.set(_MODEL, messages, response, temperature=0.0)

    assert cache.get(_MODEL, messages, temperature=0.0) is response
    assert cache.get(_MODEL, messages, temperature=1.0) is None


# ── AGENT_* config defaults + validation ───────────────────────────────────


def test_agent_settings_defaults() -> None:
    s = Settings()
    assert s.agent_enabled is False
    assert s.agent_tool_call_mode == "json"
    assert s.agent_max_steps == 6
    assert s.agent_max_run_tokens == 60_000
    assert s.agent_max_run_cost_usd == 0.0
    assert s.agent_max_run_seconds == 120.0


def test_agent_tool_call_mode_validation(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_TOOL_CALL_MODE", raising=False)
    cases = [("native", "native"), ("auto", "auto"), ("NATIVE", "native"), ("bad-value", "json")]
    for raw, expected in cases:
        monkeypatch.setenv("AGENT_TOOL_CALL_MODE", raw)
        assert Settings().agent_tool_call_mode == expected


def test_agent_enabled_env_override(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("AGENT_MAX_STEPS", "10")
    reset_settings_cache()
    try:
        s = Settings()
        assert s.agent_enabled is True
        assert s.agent_max_steps == 10
    finally:
        reset_settings_cache()
