#!/usr/bin/env python3
"""Diagnostic probe for native tool-calling capability (Wave 0).

Sends a set of prompts with ``tools=`` against an OpenAI-compatible endpoint
(local llama.cpp via ``LLM_MODEL`` or a cloud model via ``--cloud-model``) and
measures how reliably the model:

  * emits a well-formed ``tool_calls`` payload (native function calling),
  * selects the *correct* tool for the prompt intent,
  * produces valid JSON arguments,
  * avoids hallucinated tool names.

The result feeds the decision for ``AGENT_TOOL_CALL_MODE`` (json | native | auto).

This is a **diagnostic script** — it imports the provider layer to build the LLM
client (per project rules) but has zero impact on runtime behaviour: nothing in
``app/`` imports it, and it does not touch ``data/`` or the vector index.

Usage::

    .\\.venv\\Scripts\\python.exe scripts/agent_toolcall_probe.py
    .\\.venv\\Scripts\\python.exe scripts/agent_toolcall_probe.py --limit 5
    .\\.venv\\Scripts\\python.exe scripts/agent_toolcall_probe.py \\
        --cloud-model openai/gpt-4o-mini
    .\\.venv\\Scripts\\python.exe scripts/agent_toolcall_probe.py --json-out probe_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A compact read-only tool registry mirroring the planned Wave 1 tools
# (§2.3 of docs/agent_roadmap.md). Args are intentionally small/strict so the
# probe can validate JSON-arg correctness without domain logic.
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Search the knowledge base for relevant documents and fragments about a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query text."},
                    "top_k": {"type": "integer", "description": "Maximum number of fragments to return."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learner_get_profile",
            "description": "Retrieve the learner's study profile and recent activity summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_history": {
                        "type": "boolean",
                        "description": "Whether to include recent session history.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cards_get_due",
            "description": "Get flashcards that are currently due for spaced-repetition review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum number of due cards."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quiz_generate",
            "description": "Generate a short practice quiz on a given topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The topic for the quiz."},
                    "question_count": {"type": "integer", "description": "Number of quiz questions."},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "progress_get_mastery",
            "description": "Report the learner's mastery level for a concept or topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string", "description": "The concept to assess."},
                },
                "required": ["concept"],
            },
        },
    },
]

_VALID_TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}

# Each case maps a natural-language prompt to the tool the model *should* select.
PROBE_CASES: list[tuple[str, str]] = [
    ("Find documents explaining how retrieval-augmented generation works.", "rag_search"),
    ("Search the knowledge base for information about gradient descent.", "rag_search"),
    ("What do you know about my recent study activity and progress?", "learner_get_profile"),
    ("Show me my learner profile and last sessions.", "learner_get_profile"),
    ("Which flashcards are due for review right now?", "cards_get_due"),
    ("What review cards do I have pending today?", "cards_get_due"),
    ("Create a short quiz about neural networks.", "quiz_generate"),
    ("Generate a practice quiz on the topic of linear algebra.", "quiz_generate"),
    ("How well do I understand the concept of backpropagation?", "progress_get_mastery"),
    ("Report my mastery level for the topic of attention mechanisms.", "progress_get_mastery"),
    ("I need to look up material on transformers in my notes.", "rag_search"),
    ("Give me my overdue spaced-repetition cards.", "cards_get_due"),
    ("Make me a few test questions about photosynthesis.", "quiz_generate"),
    ("Check my proficiency with the concept of recursion.", "progress_get_mastery"),
    ("Summarize my learning profile so far.", "learner_get_profile"),
    ("Find sources that discuss the CAP theorem.", "rag_search"),
    ("Quiz me on the French Revolution.", "quiz_generate"),
    ("How strong is my grasp of dynamic programming?", "progress_get_mastery"),
    ("Which cards should I review next?", "cards_get_due"),
    ("Pull up my study history and profile.", "learner_get_profile"),
]


@dataclass
class CaseResult:
    prompt: str
    expected_tool: str
    native_tool_call: bool = False
    called_tool: str | None = None
    args_valid: bool = False
    args_raw: str | None = None
    tool_correct: bool = False
    name_hallucinated: bool = False
    latency_ms: int | None = None
    error: str | None = None
    content_snippet: str = ""


@dataclass
class ModelProbeResult:
    model: str
    api_base: str
    cases: list[CaseResult] = field(default_factory=list)
    total: int = 0
    native_rate: float = 0.0
    args_valid_rate: float = 0.0
    tool_correct_rate: float = 0.0
    hallucination_rate: float = 0.0
    avg_latency_ms: float | None = None
    recommendation: str = ""


def _build_llm(model: str, api_base: str) -> Any:
    """Build an OpenAI-compatible LLM client via the provider layer."""
    from app.config import get_settings
    from app.provider import OpenAI

    s = get_settings()
    return OpenAI(
        model=model,
        api_key=s.openai_api_key or "lm-studio",
        api_base=api_base,
        max_retries=0,
        timeout=60.0,
        reuse_client=False,
    )


def _disable_llm_cache_for_probe() -> None:
    import os

    from app.config import reset_settings_cache

    os.environ["LLM_REQUEST_CACHE_PERSIST"] = "false"
    reset_settings_cache()
    import app.request_cache as rc

    rc._request_cache = None  # noqa: SLF001


def _analyze_tool_calls(raw: Any) -> tuple[bool, str | None, str | None, bool]:
    """Extract (native_call, tool_name, args_json, name_hallucinated) from a raw response."""
    try:
        message = raw.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return False, None, None, False

    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return False, None, None, False

    first = tool_calls[0]
    fn = getattr(first, "function", None)
    name = getattr(fn, "name", None) if fn is not None else None
    args = getattr(fn, "arguments", None) if fn is not None else None
    name_str = str(name or "").strip()
    hallucinated = bool(name_str) and name_str not in _VALID_TOOL_NAMES
    return True, name_str or None, args, hallucinated


def _parse_args_json(args_raw: str | None) -> bool:
    if not args_raw:
        return False
    try:
        value = json.loads(args_raw)
        return isinstance(value, dict)
    except (json.JSONDecodeError, TypeError):
        return False


def _probe_model(model: str, api_base: str, limit: int | None) -> ModelProbeResult:
    from llama_index.core.base.llms.types import ChatMessage

    result = ModelProbeResult(model=model, api_base=api_base)
    cases = PROBE_CASES[:limit] if limit else PROBE_CASES

    try:
        llm = _build_llm(model, api_base)
    except Exception as exc:  # noqa: BLE001
        result.recommendation = f"Не удалось построить LLM-клиент: {exc}"
        return result

    system_msg = ChatMessage(
        role="system",
        content=(
            "You are a study assistant. Use the provided tools to help the learner. "
            "Choose exactly one tool that best matches the request."
        ),
    )

    for prompt, expected in cases:
        case = CaseResult(prompt=prompt, expected_tool=expected)
        t0 = time.perf_counter()
        try:
            response = llm.chat(
                [system_msg, ChatMessage(role="user", content=prompt)],
                tools=TOOL_SPECS,
                tool_choice="auto",
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            case.latency_ms = int((time.perf_counter() - t0) * 1000)
            case.error = str(exc)[:500]
            result.cases.append(case)
            continue

        case.latency_ms = int((time.perf_counter() - t0) * 1000)
        raw = getattr(response, "raw", None)
        native, called, args_raw, hallucinated = _analyze_tool_calls(raw)
        case.native_tool_call = native
        case.called_tool = called
        case.args_raw = args_raw
        case.name_hallucinated = hallucinated
        case.args_valid = _parse_args_json(args_raw) if native else False
        case.tool_correct = native and called == expected
        content = getattr(getattr(response, "message", None), "content", None)
        if isinstance(content, str):
            case.content_snippet = content[:160]
        result.cases.append(case)

    _aggregate(result)
    return result


def _aggregate(result: ModelProbeResult) -> None:
    result.total = len(result.cases)
    if result.total == 0:
        result.recommendation = "Нет данных — ни один кейс не выполнен."
        return
    native = sum(1 for c in result.cases if c.native_tool_call)
    valid = sum(1 for c in result.cases if c.args_valid)
    correct = sum(1 for c in result.cases if c.tool_correct)
    halluc = sum(1 for c in result.cases if c.name_hallucinated)
    errors = sum(1 for c in result.cases if c.error)
    latencies = [c.latency_ms for c in result.cases if c.latency_ms is not None]

    result.native_rate = native / result.total
    result.args_valid_rate = valid / result.total
    result.tool_correct_rate = correct / result.total
    result.hallucination_rate = halluc / result.total
    result.avg_latency_ms = round(sum(latencies) / len(latencies), 1) if latencies else None

    if errors == result.total:
        result.recommendation = (
            "Все вызовы завершились ошибкой — endpoint не поддерживает tools= или модель недоступна. "
            "Рекомендация: AGENT_TOOL_CALL_MODE=json (JSON-decision)."
        )
    elif result.tool_correct_rate >= 0.8 and result.args_valid_rate >= 0.8 and result.hallucination_rate <= 0.1:
        result.recommendation = (
            f"Native tool-calling стабилен (correct={result.tool_correct_rate:.0%}, "
            f"args_valid={result.args_valid_rate:.0%}). Рекомендация: AGENT_TOOL_CALL_MODE=native "
            f"пригоден для этой модели; auto может выбирать native."
        )
    elif result.native_rate >= 0.5:
        result.recommendation = (
            f"Native tool-calling частично работает, но ненадёжно (correct={result.tool_correct_rate:.0%}, "
            f"hallucinations={result.hallucination_rate:.0%}). Рекомендация: AGENT_TOOL_CALL_MODE=json "
            f"с repair-циклом; native только как эксперимент."
        )
    else:
        result.recommendation = (
            f"Модель не выдаёт native tool_calls ({result.native_rate:.0%}). "
            "Рекомендация: AGENT_TOOL_CALL_MODE=json (JSON-decision)."
        )


def _resolve_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    """Return list of (model, api_base) pairs to probe."""
    from app.config import get_settings, is_cloud_model
    from app.provider import normalize_openai_compatible_api_base

    s = get_settings()
    targets: list[tuple[str, str]] = []

    local_model = (s.llm_model or "").strip()
    local_base = normalize_openai_compatible_api_base(
        getattr(s, "lmstudio_api_base", "") or getattr(s, "llm_api_base", "")
    )
    if local_model and local_base:
        targets.append((local_model, local_base))

    if args.cloud_model:
        cloud_base = normalize_openai_compatible_api_base(s.openai_api_base)
        targets.append((args.cloud_model, cloud_base))
    elif args.auto_cloud and is_cloud_model(local_model):
        cloud_base = normalize_openai_compatible_api_base(s.openai_api_base)
        targets.append((local_model, cloud_base))

    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe native tool-calling capability for AGENT_TOOL_CALL_MODE.")
    parser.add_argument("--cloud-model", help="Also probe a cloud model id (e.g. openai/gpt-4o-mini).")
    parser.add_argument(
        "--auto-cloud",
        action="store_true",
        help="If LLM_MODEL is already a cloud model, also probe it against OPENAI_API_BASE.",
    )
    parser.add_argument("--limit", type=int, help="Limit number of probe cases per model.")
    parser.add_argument("--no-cache", action="store_true", help="Disable LLM request cache for the probe.")
    parser.add_argument("--json-out", type=Path, help="Write full report JSON to path.")
    args = parser.parse_args(argv)

    if args.no_cache:
        _disable_llm_cache_for_probe()

    targets = _resolve_targets(args)
    if not targets:
        print("Не найдено моделей для probe. Задайте LLM_MODEL + LMSTUDIO_API_BASE или --cloud-model.")
        return 1

    report: dict[str, Any] = {"models": [], "tool_names": sorted(_VALID_TOOL_NAMES)}
    any_reliable = False

    for model, api_base in targets:
        print(f"\n=== Probe model: {model} ({api_base}) ===", flush=True)
        res = _probe_model(model, api_base, args.limit)
        for case in res.cases:
            tag = "OK" if case.tool_correct else ("NATIVE" if case.native_tool_call else "TEXT")
            err = f" ERR={case.error[:80]}" if case.error else ""
            print(
                f"  [{tag:6}] expected={case.expected_tool:24} called={case.called_tool or '-':24}"
                f" args_valid={case.args_valid} {case.latency_ms}ms{err}"
            )
        print(
            f"  native={res.native_rate:.0%} correct={res.tool_correct_rate:.0%} "
            f"args_valid={res.args_valid_rate:.0%} halluc={res.hallucination_rate:.0%}"
        )
        print(f"  -> {res.recommendation}")
        report["models"].append(asdict(res))
        if res.tool_correct_rate >= 0.8 and res.args_valid_rate >= 0.8:
            any_reliable = True

    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nReport written: {args.json_out}")

    print(f"\n=== Итог ===\nNative tool-calling надёжен хотя бы для одной модели: {any_reliable}")
    return 0 if any_reliable else 1


if __name__ == "__main__":
    raise SystemExit(main())
