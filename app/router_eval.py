"""Router eval (E10.3): gold labels vs pedagogical orchestrator ``selected_agent``."""

from __future__ import annotations

import time
from typing import Any

from app.config import get_settings
from app.knowledge_graph import knowledge_graph
from app.tutor_orchestrator import (
    build_knowledge_graph_subgraph_text,
    build_tutor_session_state,
    invoke_pedagogical_orchestrator_llm,
)
from app.tutor_personalization_policy import (
    apply_orchestrator_policy_clamp,
    attach_personalization_policy_to_learner_profile,
)
from app.tutor_prompts import ORCHESTRATOR_AGENT_NAMES


class _SimpleMsg:
    __slots__ = ("role", "content")

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


def _topic_from_input(inp: dict[str, Any], message: str) -> str:
    t = str(inp.get("topic") or "").strip()
    if t:
        return t
    m = message.lower()
    if "prompt injection" in m:
        return "Prompt Injection"
    if "rerank" in m or "reranking" in m:
        return "reranking"
    if "rag" in m:
        return "RAG"
    if "документ" in m or "10000" in m:
        return "scaling retrieval"
    return "general"


def _quiz_difficulty_from_input(inp: dict[str, Any]) -> str:
    raw = inp.get("previous_quiz_score")
    if raw is None:
        return str(inp.get("quiz_difficulty") or "recognition").strip().lower() or "recognition"
    try:
        sc = float(raw)
    except (TypeError, ValueError):
        return "recognition"
    if sc >= 0.85:
        return "transfer"
    if sc >= 0.55:
        return "recall"
    return "recognition"


def conversation_history_from_input(inp: dict[str, Any]) -> list[Any]:
    h = inp.get("history") or inp.get("followup_context")
    if not h:
        return []
    return [_SimpleMsg("assistant", str(h).strip())]


def user_message_for_router_case(inp: dict[str, Any], router_eval: dict[str, Any] | None) -> str:
    q = str(inp.get("question") or "").strip()
    if q:
        return q
    rev = router_eval if isinstance(router_eval, dict) else {}
    stub = str(rev.get("stub_user_message") or "").strip()
    return stub


def build_learner_profile_bundle(inp: dict[str, Any], message: str) -> dict[str, Any]:
    topic = _topic_from_input(inp, message)
    orch = build_tutor_session_state(
        current_topic=topic,
        mastery_level=str(inp.get("mastery_level") or "intermediate").strip().lower() or "intermediate",
        preferred_style=str(inp.get("preferred_style") or "balanced").strip().lower() or "balanced",
        learning_goal=str(inp.get("learning_goal") or "understand_topic").strip().lower() or "understand_topic",
        quiz_difficulty=_quiz_difficulty_from_input(inp),
        kg=knowledge_graph,
    )
    profile = dict(orch["learner_profile"])
    # Регрессионный harness: поля из кейса должны доходить до оркестратора (E11-R), иначе
    # priority rules по quiz/session не срабатывают в eval.
    if isinstance(inp, dict):
        hl = inp.get("homework_level")
        if hl is not None and str(hl).strip():
            profile["homework_level"] = str(hl).strip().lower()
        if inp.get("quiz_answer_score") is not None:
            try:
                profile["quiz_answer_score"] = float(inp["quiz_answer_score"])
            except (TypeError, ValueError):
                pass
        if inp.get("message_count") is not None:
            try:
                profile["session_message_count"] = int(inp["message_count"])
            except (TypeError, ValueError):
                pass
        if inp.get("history") or inp.get("followup_context"):
            profile["orchestrator_prior_assistant_context"] = True
    return profile


def run_single_router_case(case: dict[str, Any]) -> dict[str, Any]:
    """Один вызов оркестратора; сравнение с ``router_eval.gold_selected_agent``."""
    case_id = str(case.get("id") or "unknown")
    category = str(case.get("category") or "unknown").strip().lower()
    inp = case.get("input") if isinstance(case.get("input"), dict) else {}
    router_eval = case.get("router_eval") if isinstance(case.get("router_eval"), dict) else {}

    llm_model = str(get_settings().llm_model or "").strip() or None

    gold = str(router_eval.get("gold_selected_agent") or "").strip()
    if not gold or gold not in ORCHESTRATOR_AGENT_NAMES:
        return {
            "id": case_id,
            "category": category,
            "status": "skipped",
            "reason": "missing_or_invalid_router_gold",
            "gold_selected_agent": gold or None,
            "predicted_agent": None,
            "match": None,
            "latency_ms": None,
            "llm_model": llm_model,
        }

    message = user_message_for_router_case(inp, router_eval)
    if not message:
        return {
            "id": case_id,
            "category": category,
            "status": "skipped",
            "reason": "no_user_message",
            "gold_selected_agent": gold,
            "predicted_agent": None,
            "match": None,
            "latency_ms": None,
            "llm_model": llm_model,
        }

    learner_profile = build_learner_profile_bundle(inp, message)
    learner_profile["orchestrator_clamp_user_message"] = message
    learner_profile = attach_personalization_policy_to_learner_profile(learner_profile)
    history = conversation_history_from_input(inp)
    subgraph = build_knowledge_graph_subgraph_text(learner_profile, kg=knowledge_graph)

    t0 = time.perf_counter()
    decision, usage = invoke_pedagogical_orchestrator_llm(
        learner_profile=learner_profile,
        current_user_message=message,
        conversation_history=history,
        knowledge_graph_subgraph_override=subgraph,
    )
    decision, policy_clamp_meta = apply_orchestrator_policy_clamp(decision, learner_profile)
    latency_ms = int(round((time.perf_counter() - t0) * 1000.0))
    predicted = str(decision.get("selected_agent") or "").strip()
    match = predicted == gold
    gold_rationale = str(router_eval.get("gold_rationale") or "").strip() or None
    row: dict[str, Any] = {
        "id": case_id,
        "category": category,
        "status": "completed",
        "gold_selected_agent": gold,
        "predicted_agent": predicted,
        "match": match,
        "fallback": bool(decision.get("_fallback")),
        "usage": usage,
        "latency_ms": latency_ms,
        "llm_model": llm_model,
        "user_message_preview": message[:240] + ("…" if len(message) > 240 else ""),
        "policy_clamp": policy_clamp_meta,
    }
    if gold_rationale:
        row["gold_rationale"] = gold_rationale
    if not match:
        # Surface orchestrator rationale on mismatch for diagnosis.
        row["predicted_rationale"] = str(decision.get("rationale") or "").strip() or None
        row["predicted_reasoning_steps"] = decision.get("reasoning_steps")
    return row


def aggregate_router_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Overall и per-category accuracy по строкам со ``status==completed``."""
    done = [r for r in rows if r.get("status") == "completed"]
    n = len(done)
    if not n:
        return {
            "cases_completed": 0,
            "overall_accuracy": None,
            "per_category": {},
        }
    correct = sum(1 for r in done if r.get("match"))
    by_cat: dict[str, list[bool]] = {}
    for r in done:
        cat = str(r.get("category") or "unknown")
        by_cat.setdefault(cat, []).append(bool(r.get("match")))

    per_cat: dict[str, Any] = {}
    for cat, flags in sorted(by_cat.items()):
        t = len(flags)
        c = sum(1 for x in flags if x)
        per_cat[cat] = {
            "correct": c,
            "total": t,
            "accuracy": round(c / t, 4) if t else None,
        }

    return {
        "cases_completed": n,
        "cases_correct": correct,
        "overall_accuracy": round(correct / n, 4),
        "per_category": per_cat,
    }
