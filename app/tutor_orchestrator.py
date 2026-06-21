"""Server-side pedagogical orchestration for tutor sessions.

Phase 1 scope:
- unify tutor routing across explanation, due review, weak spots, and next step;
- add graph-aware hints for prompts and UI/debug;
- apply lightweight self-correction to tutor payloads after generation;
- choose the best target for the automatic micro-quiz.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from llama_index.core.base.llms.types import MessageRole
from llama_index.core.llms import ChatMessage

from app.knowledge_graph import JsonKnowledgeGraph, knowledge_graph
from app.llm_resilience import chat_with_resilience
from app.learner_state_scope import (
    count_due_reviews_for_kg,
    filter_due_reviews_for_kg,
    get_mastery_levels_for_kg,
    weak_concepts_for_kg,
)
from app.learning_plan_service import get_recommended_next_step_after_micro_quiz
from app.provider import get_graph_llm
from app.spaced_repetition import due_priority_reason
from app.tutor_prompts import (
    ORCHESTRATOR_AGENT_NAMES,
    ORCHESTRATOR_DECISION_PROMPT,
    ORCHESTRATOR_DEPTH_TO_ANSWER,
    ORCHESTRATOR_SYSTEM_PROMPT,
    SOCRATIC_TYPE_KEYS,
)
from app.usage_cost import extract_token_usage

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset(
    {
        "Объясни проще",
        "Дай пример",
        "Проверь меня",
        "Следующий шаг",
        "Пора повторить",
        "Повтори позже",
        "Дай задачу на применение",
        "Повторить базу",
    }
)


def _normalize_topic(topic: str | None) -> str:
    return (topic or "").strip() or "general"


def build_learner_goal_context_dict(
    *,
    topic: str,
    preferred_style: str,
    learning_goal: str,
    tutor_goal_subtopic: str | None = None,
    tutor_goal_target_level: str | None = None,
    tutor_goal_desired_outcome: str | None = None,
    tutor_goal_time_budget_min: int | None = None,
) -> dict[str, Any]:
    """Stable request-scoped goal context for tutor (E24-A)."""
    return {
        "topic": _normalize_topic(topic),
        "subtopic": tutor_goal_subtopic,
        "target_level": tutor_goal_target_level,
        "desired_outcome": tutor_goal_desired_outcome,
        "time_budget_min": tutor_goal_time_budget_min,
        "preferred_style": (preferred_style or "balanced").strip().lower() or "balanced",
        "learning_goal": (learning_goal or "understand_topic").strip().lower() or "understand_topic",
    }


def _first_distinct(values: list[str], *, limit: int) -> list[str]:
    out: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _graph_cluster_for_topic(kg: JsonKnowledgeGraph, topic: str) -> list[str]:
    concepts = kg.get_concepts()
    if topic not in concepts:
        return [topic]
    node = concepts.get(topic) or {}
    related = list(node.get("related_concepts") or [])
    if not related:
        related = list(node.get("examples") or [])
    prereqs = list(kg.get_prerequisites(topic))
    return _first_distinct([topic, *prereqs, *related], limit=5)


def _route_name(
    *,
    due_count: int,
    current_topic: str,
    weak_concepts: list[str],
    quiz_difficulty: str,
) -> str:
    if due_count > 0:
        return "due_review"
    if current_topic and current_topic in weak_concepts[:3]:
        return "targeted_reinforcement"
    if quiz_difficulty == "recognition":
        return "foundation"
    if quiz_difficulty == "transfer":
        return "advance"
    return "standard"


def build_tutor_session_state(
    *,
    current_topic: str,
    mastery_level: str,
    preferred_style: str,
    learning_goal: str,
    quiz_difficulty: str,
    persisted_profile: dict[str, Any] | None = None,
    kg: JsonKnowledgeGraph | None = None,
    tutor_goal_subtopic: str | None = None,
    tutor_goal_target_level: str | None = None,
    tutor_goal_desired_outcome: str | None = None,
    tutor_goal_time_budget_min: int | None = None,
) -> dict[str, Any]:
    """Snapshot learner + graph state for prompting, routing, and debug/UI."""
    graph = kg or knowledge_graph
    topic = _normalize_topic(current_topic)
    weak = weak_concepts_for_kg(graph, threshold=70, limit=6)
    due_items = filter_due_reviews_for_kg(graph, limit=3)
    due_count = count_due_reviews_for_kg(graph)
    cluster = _graph_cluster_for_topic(graph, topic)
    due_preview = _first_distinct([str(row.get("concept") or "") for row in due_items], limit=3)
    top_due_reason = ""
    if due_items:
        top_due_row = due_items[0]
        top_due_reason = due_priority_reason(top_due_row)
    persisted = persisted_profile if isinstance(persisted_profile, dict) else {}
    recent_topics = _first_distinct(
        [topic, *[str(x) for x in (persisted.get("recent_topics") or [])]],
        limit=5,
    )
    route = _route_name(
        due_count=due_count,
        current_topic=topic,
        weak_concepts=weak,
        quiz_difficulty=(quiz_difficulty or "recognition").strip().lower(),
    )
    quiz_topic = due_preview[0] if due_preview else (weak[0] if weak else topic)
    learner_profile = {
        "mastery_level": (mastery_level or "intermediate").strip().lower() or "intermediate",
        "preferred_style": (preferred_style or "balanced").strip().lower() or "balanced",
        "learning_goal": (learning_goal or "understand_topic").strip().lower() or "understand_topic",
        "focus_topic": topic,
        "weak_concepts": weak,
        "due_review_count": due_count,
        "due_review_preview": due_preview,
        "due_review_reason": top_due_reason,
        "graph_cluster": cluster,
        "route": route,
        "recommended_quiz_topic": quiz_topic,
        "recent_topics": recent_topics,
    }
    goal_ctx = build_learner_goal_context_dict(
        topic=topic,
        preferred_style=str(learner_profile["preferred_style"]),
        learning_goal=str(learner_profile["learning_goal"]),
        tutor_goal_subtopic=tutor_goal_subtopic,
        tutor_goal_target_level=tutor_goal_target_level,
        tutor_goal_desired_outcome=tutor_goal_desired_outcome,
        tutor_goal_time_budget_min=tutor_goal_time_budget_min,
    )
    learner_profile["goal_context"] = goal_ctx
    learner_hint = (
        f"Фокус: {topic}; mastery: {learner_profile['mastery_level']}; "
        f"style: {learner_profile['preferred_style']}; goal: {learner_profile['learning_goal']}; "
        f"recent topics: {', '.join(recent_topics)}."
    )
    graph_hint = (
        f"Graph cluster: {', '.join(cluster)}."
        if cluster
        else "Graph cluster unavailable."
    )
    orchestration_hint = (
        f"Orchestration route: {route}; due reviews: {due_count}; "
        f"weak concepts: {', '.join(weak[:3]) if weak else 'none'}."
    )
    return {
        "learner_profile": learner_profile,
        "learner_goal_context": goal_ctx,
        "learner_hint": learner_hint,
        "graph_hint": graph_hint,
        "orchestration_hint": orchestration_hint,
    }


def format_session_history_for_orchestrator(messages: list[Any], *, limit: int = 6) -> str:
    """Последние сообщения сессии — компактная строка для LLM-оркестратора."""
    if not messages:
        return "(нет сообщений в сессии)"
    tail = messages[-max(1, limit) :]
    lines: list[str] = []
    for m in tail:
        role = str(getattr(m, "role", "user") or "user")
        content = str(getattr(m, "content", "") or "").strip()
        if len(content) > 2000:
            content = content[:2000] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def build_knowledge_graph_subgraph_text(
    learner_profile: dict[str, Any],
    kg: JsonKnowledgeGraph | None = None,
) -> str:
    """Подграф: кластер из графа + уровни quiz_mastery по узлам."""
    graph = kg or knowledge_graph
    cluster = list(learner_profile.get("graph_cluster") or [])
    if not cluster:
        return "(подграф недоступен: нет кластера по теме)"
    mastery = get_mastery_levels_for_kg(graph)
    lines: list[str] = []
    for cid in cluster:
        lv = str(mastery.get(cid, "recognition")).strip()
        lines.append(f"- {cid}: quiz_mastery_level={lv}")
    try:
        topic = str(learner_profile.get("focus_topic") or cluster[0])
        prereqs = list(graph.get_prerequisites(topic))
        if prereqs:
            lines.append(f"prerequisites({topic}): {', '.join(prereqs[:5])}")
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass
    return "\n".join(lines)


def format_quiz_and_reviews_block(learner_profile: dict[str, Any]) -> str:
    """Сводка due / weak для промпта оркестратора."""
    return json.dumps(
        {
            "due_review_count": int(learner_profile.get("due_review_count") or 0),
            "due_review_preview": learner_profile.get("due_review_preview") or [],
            "weak_concepts": learner_profile.get("weak_concepts") or [],
            "route": learner_profile.get("route"),
            "recommended_quiz_topic": learner_profile.get("recommended_quiz_topic"),
        },
        ensure_ascii=False,
    )


def make_rule_fallback_orchestrator_decision(*, reason: str) -> dict[str, Any]:
    """Детерминированное решение при сбое LLM/JSON или исключении в шаге пайплайна (E6.0)."""
    out = normalize_pedagogical_orchestrator_decision(
        {
            "selected_agent": "ConceptExplainer",
            "should_trigger_microquiz": False,
            "rationale": f"Rule fallback: {reason}.",
            "confidence_score": 0.35,
            "reasoning_steps": [
                "Сбой или невалидный ответ оркестратора.",
                "Безопасный шаг: ясное объяснение без принудительного micro-quiz.",
                "ConceptExplainer по умолчанию.",
                "Micro-quiz отключён до успешного JSON-решения оркестратора.",
            ],
        }
    )
    out["_fallback"] = True
    out["_error"] = str(reason).strip() or "unknown"
    return out


def normalize_pedagogical_orchestrator_decision(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Привести ответ LLM к ожидаемой форме (мягкая валидация)."""
    data = raw if isinstance(raw, dict) else {}
    agent = str(data.get("selected_agent") or "").strip()
    if agent not in ORCHESTRATOR_AGENT_NAMES:
        agent = "ConceptExplainer"
    params_in = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
    qc = params_in.get("focus_concepts")
    focus: list[str] = []
    if isinstance(qc, list):
        focus = [str(x).strip() for x in qc if str(x).strip()]
    qt = str(params_in.get("question_type") or "probing").strip().lower()
    if qt not in SOCRATIC_TYPE_KEYS:
        qt = "probing"
    depth = str(params_in.get("depth") or "intermediate").strip().lower()
    if depth not in ORCHESTRATOR_DEPTH_TO_ANSWER:
        depth = "intermediate"
    mot = str(params_in.get("motivation_link") or "").strip()
    steps = data.get("reasoning_steps")
    if not isinstance(steps, list) or len(steps) < 4:
        steps = [
            "Состояние: оценка по входным данным.",
            "Цель шага: уточнить понимание.",
            "Агент: ConceptExplainer для ясного объяснения.",
            "Micro-quiz: по необходимости после ответа.",
        ]
    else:
        steps = [str(s).strip() for s in steps[:4]]
        while len(steps) < 4:
            steps.append("…")
    try:
        conf = float(data.get("confidence_score"))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    st = data.get("should_trigger_microquiz")
    if not isinstance(st, bool):
        st = True
    rationale = str(data.get("rationale") or "").strip() or "Orchestrator fallback."
    next_best = str(data.get("next_best_action") or "").strip()
    return {
        "reasoning_steps": steps,
        "selected_agent": agent,
        "rationale": rationale,
        "parameters": {
            "focus_concepts": focus,
            "question_type": qt,
            "depth": depth,
            "motivation_link": mot,
        },
        "should_trigger_microquiz": st,
        "next_best_action": next_best,
        "confidence_score": conf,
    }


def invoke_pedagogical_orchestrator_llm(
    *,
    learner_profile: dict[str, Any],
    current_user_message: str,
    conversation_history: list[Any],
    kg: JsonKnowledgeGraph | None = None,
    knowledge_graph_subgraph_override: str | None = None,
) -> tuple[dict[str, Any], dict[str, int] | None]:
    """
    Один вызов chat completion (JSON object) — выбор педагогического «агента» и параметров.
    Возвращает (decision, token_usage).

    Если задан ``knowledge_graph_subgraph_override``, он подставляется в промпт вместо
    авто-текста из ``build_knowledge_graph_subgraph_text`` (graph-augmented / personalized).
    """
    from app.quiz_parse import _extract_first_json_object

    lp = json.dumps(learner_profile, ensure_ascii=False)
    if knowledge_graph_subgraph_override is not None:
        subgraph = str(knowledge_graph_subgraph_override).strip() or "(пустой подграф)"
    else:
        subgraph = build_knowledge_graph_subgraph_text(learner_profile, kg=kg)
    history = format_session_history_for_orchestrator(conversation_history, limit=6)
    last_q = format_quiz_and_reviews_block(learner_profile)
    user_content = ORCHESTRATOR_DECISION_PROMPT.format(
        learner_profile=lp,
        knowledge_graph_subgraph=subgraph,
        session_history=history,
        last_quiz_results=last_q,
        current_user_message=str(current_user_message or "").strip() or "(пусто)",
    )
    try:
        llm = get_graph_llm()
        response = chat_with_resilience(
            llm,
            [
                ChatMessage(role=MessageRole.SYSTEM, content=ORCHESTRATOR_SYSTEM_PROMPT),
                ChatMessage(role=MessageRole.USER, content=user_content),
            ],
            stage="tutor_orchestrator.invoke_pedagogical_orchestrator_llm",
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        usage = extract_token_usage(response)
        text = (response.message.content or "").strip()
        parsed = _extract_first_json_object(text)
        if not parsed:
            logger.warning("pedagogical_orchestrator_json_parse_failed | preview=%s", text[:200])
            return make_rule_fallback_orchestrator_decision(reason="json_parse"), usage
        out = normalize_pedagogical_orchestrator_decision(parsed)
        out["_fallback"] = False
        return out, usage
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.exception("pedagogical_orchestrator_llm_failed")
        return make_rule_fallback_orchestrator_decision(reason="exception"), None


def apply_pedagogical_orchestrator_to_metadata(
    ctx: Any,
    decision: dict[str, Any],
    *,
    policy_clamp_meta: dict[str, Any] | None = None,
) -> None:
    """Записать решение оркестратора в ctx.metadata (socratic, depth, quiz topic, micro-quiz flag)."""
    from app.tutor_pipeline_contract import merge_orchestration_pipeline_contract

    md = getattr(ctx, "metadata", None)
    if not isinstance(md, dict):
        return
    md["pedagogical_orchestrator"] = decision
    md["pedagogical_orchestrator_applied"] = True
    agent = str(decision.get("selected_agent") or "").strip()
    md["orchestrator_selected_agent"] = agent
    params = decision.get("parameters") if isinstance(decision.get("parameters"), dict) else {}
    if agent == "SocraticQuestioner":
        qt = str(params.get("question_type") or "").strip().lower()
        if qt in SOCRATIC_TYPE_KEYS:
            md["socratic_type"] = qt
    elif agent == "ConceptExplainer":
        depth = str(params.get("depth") or "").strip().lower()
        if depth in ORCHESTRATOR_DEPTH_TO_ANSWER:
            md["answer_depth"] = ORCHESTRATOR_DEPTH_TO_ANSWER[depth]
    elif agent == "MicroQuizGenerator":
        qd = str(md.get("quiz_difficulty") or "recognition").strip().lower()
        if qd == "recognition":
            md["quiz_difficulty"] = "recall"
    fc = params.get("focus_concepts") if isinstance(params.get("focus_concepts"), list) else []
    if fc:
        first = str(fc[0]).strip()
        if first:
            md["orchestrator_quiz_topic"] = first
    st = decision.get("should_trigger_microquiz")
    if isinstance(st, bool):
        md["orchestrator_trigger_microquiz"] = st
    else:
        md["orchestrator_trigger_microquiz"] = True
    oh = str(md.get("orchestration_hint") or "").strip()
    extra = (
        f"PedagogicalOrchestrator: agent={agent}; "
        f"conf={decision.get('confidence_score')}; "
        f"microquiz={md.get('orchestrator_trigger_microquiz')}"
    )
    md["orchestration_hint"] = f"{oh} | {extra}".strip(" |") if oh else extra

    merge_kw: dict[str, Any] = dict(
        phase="orchestrate",
        selected_agent=agent,
        should_trigger_microquiz=md.get("orchestrator_trigger_microquiz"),
        decision_source="rule_fallback" if decision.get("_fallback") else "llm",
    )
    if policy_clamp_meta:
        merge_kw["policy_clamped"] = bool(policy_clamp_meta.get("policy_clamped"))
        merge_kw["policy_clamp_reasons"] = list(policy_clamp_meta.get("clamp_reasons") or [])
    merge_orchestration_pipeline_contract(md, **merge_kw)


def _cta_priority_for_route(route: str) -> list[str]:
    if route == "due_review":
        return ["Пора повторить", "Проверь меня", "Следующий шаг", "Дай пример"]
    if route == "targeted_reinforcement":
        return ["Объясни проще", "Дай пример", "Проверь меня", "Повторить базу"]
    if route == "advance":
        return ["Следующий шаг", "Дай задачу на применение", "Проверь меня", "Дай пример"]
    if route == "foundation":
        return ["Объясни проще", "Проверь меня", "Дай пример", "Следующий шаг"]
    return ["Проверь меня", "Дай пример", "Следующий шаг", "Повтори позже"]


def _merge_ctas(existing: Any, route: str) -> list[str]:
    current = [str(item).strip() for item in (existing or []) if str(item).strip()]
    merged = _first_distinct(_cta_priority_for_route(route) + current, limit=6)
    return [item for item in merged if item in _VALID_ACTIONS]


def apply_tutor_self_correction(
    teaching: dict[str, Any] | None,
    *,
    session_state: dict[str, Any] | None,
    source_count: int,
    graph_prerequisites_health: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Align tutor payload with learner state, graph, and review pressure.

    ``graph_prerequisites_health``: результат ``get_graph_prerequisites_health()`` (17 Extension);
    при циклах в prerequisites добавляет заметку в ``trust_signals``, не трогая MVP retrieval path.
    """
    if not isinstance(teaching, dict):
        return teaching
    state = session_state or {}
    profile = state.get("learner_profile") if isinstance(state, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    route = str(profile.get("route") or "standard")
    corrected = dict(teaching)
    llm_filled_next = bool(
        str(teaching.get("next_action") or "").strip()
        and str(teaching.get("next_action_reason") or "").strip()
    )
    apply_cta_trust = route == "due_review" or not llm_filled_next
    if apply_cta_trust:
        corrected["suggested_ctas"] = _merge_ctas(corrected.get("suggested_ctas"), route)
        trust = corrected.get("trust_signals")
        if not isinstance(trust, dict):
            trust = {}
        trust["sources_used"] = max(int(trust.get("sources_used") or 0), int(source_count or 0))
        if trust["sources_used"] <= 1:
            trust["confidence"] = "low"
            trust.setdefault(
                "coverage_warning",
                "Низкое покрытие источников: стоит проверить ответ через повторный вопрос или review.",
            )
        corrected["trust_signals"] = trust
    else:
        sc = teaching.get("suggested_ctas")
        if isinstance(sc, list):
            corrected["suggested_ctas"] = [str(x).strip() for x in sc if str(x).strip()]
        ts = teaching.get("trust_signals")
        if isinstance(ts, dict):
            corrected["trust_signals"] = dict(ts)

    if graph_prerequisites_health and graph_prerequisites_health.get("has_prerequisite_cycles"):
        trust = corrected.get("trust_signals")
        if not isinstance(trust, dict):
            trust = {}
            corrected["trust_signals"] = trust
        trust["graph_prerequisite_cycles"] = True
        trust.setdefault(
            "graph_note",
            "В графе знаний есть циклические prerequisites; порядок шагов может быть неоднозначен.",
        )

    if route == "due_review":
        due_preview = profile.get("due_review_preview") or []
        focus = due_preview[0] if due_preview else profile.get("focus_topic") or "эту тему"
        due_reason = str(profile.get("due_review_reason") or "").strip() or "давно не повторял"
        corrected["next_action"] = "Пора повторить"
        corrected["next_action_reason"] = (
            f"Есть просроченное повторение по теме {focus}: {due_reason}; закрепление сейчас полезнее, чем идти дальше."
        )
        risk = "Есть риск забывания по due review."
    elif route == "targeted_reinforcement" and not llm_filled_next:
        weak_preview = [
            str(x).strip()
            for x in (profile.get("weak_concepts") or [])
            if str(x).strip()
        ][:2]
        corrected["next_action"] = "Проверь меня"
        corrected["next_action_reason"] = (
            "Есть признаки misconceptions в слабых темах, поэтому сначала нужна короткая диагностическая проверка."
        )
        risk = (
            f"Возможны misconceptions по темам: {', '.join(weak_preview)}."
            if weak_preview
            else "Тема всё ещё в зоне слабого понимания."
        )
    elif route == "foundation" and not llm_filled_next:
        corrected["next_action"] = "Объясни проще"
        corrected["next_action_reason"] = (
            "Система видит базовый уровень усвоения, поэтому сначала стоит упростить объяснение и проверить распознавание идеи."
        )
        risk = "Нужно укрепить базовые определения и различения."
    elif route == "advance" and not llm_filled_next:
        corrected["next_action"] = "Дай задачу на применение"
        corrected["next_action_reason"] = (
            "Ученик готов к переносу знания на новый случай, поэтому следующий лучший шаг — короткая задача на применение."
        )
        risk = "Важно проверить перенос знания, а не только узнавание."
    else:
        risk = str((corrected.get("understanding_state") or {}).get("risk_gaps") or "").strip()

    ustate = corrected.get("understanding_state")
    if not isinstance(ustate, dict):
        ustate = {}
    if risk:
        ustate["risk_gaps"] = risk
    if not str(ustate.get("what_to_do_now") or "").strip():
        ustate["what_to_do_now"] = str(corrected.get("next_action") or "").strip()
    corrected["understanding_state"] = ustate

    # Anti-overhelp guard in homework route: в умолчаниях держим scaffold-first.
    if str(profile.get("learning_goal") or "").strip().lower() == "solve_homework" and not llm_filled_next:
        corrected["next_action"] = "Следующий шаг"
        corrected["next_action_reason"] = (
            "Для homework-режима сначала делаем scaffold: один шаг решения и проверка понимания, без полного разбора."
        )
        corrected["suggested_ctas"] = _merge_ctas(corrected.get("suggested_ctas"), "foundation")
    return corrected


def decide_tutor_next_action(
    *,
    current_topic: str,
    mastery_level: str,
    preferred_style: str,
    learning_goal: str,
    quiz_difficulty: str,
    session_state: dict[str, Any] | None = None,
    kg: JsonKnowledgeGraph | None = None,
) -> dict[str, Any]:
    """Rule-based маршрут + рекомендация следующего шага после micro-quiz (граф / spaced repetition).

    LLM Pedagogical Orchestrator (19.4) вызывается отдельно до generation —
    см. ``invoke_pedagogical_orchestrator_llm`` и поле ``pedagogical_orchestrator`` в ``tutor_decision``.
    """
    graph = kg or knowledge_graph
    state = session_state or build_tutor_session_state(
        current_topic=current_topic,
        mastery_level=mastery_level,
        preferred_style=preferred_style,
        learning_goal=learning_goal,
        quiz_difficulty=quiz_difficulty,
        kg=graph,
    )
    profile = state.get("learner_profile") if isinstance(state, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    route = str(profile.get("route") or "standard")
    synthetic_feedback = {
        "status": "incorrect" if route in {"due_review", "targeted_reinforcement", "foundation"} else "correct"
    }
    recommended = get_recommended_next_step_after_micro_quiz(
        current_topic=_normalize_topic(current_topic),
        mastery_level=(mastery_level or "intermediate").strip().lower() or "intermediate",
        last_quiz_feedback=synthetic_feedback,
        quiz_question_type="recall" if route in {"due_review", "foundation"} else "application",
        due_reviews_count=int(profile.get("due_review_count") or 0),
        kg=graph,
        preferred_style=(preferred_style or "balanced").strip().lower() or "balanced",
    )
    return {
        "route": route,
        "focus_topic": profile.get("focus_topic") or _normalize_topic(current_topic),
        "recommended_quiz_topic": profile.get("recommended_quiz_topic") or _normalize_topic(current_topic),
        "weak_concepts": profile.get("weak_concepts") or [],
        "due_review_count": int(profile.get("due_review_count") or 0),
        "due_review_preview": profile.get("due_review_preview") or [],
        "graph_cluster": profile.get("graph_cluster") or [],
        "action": recommended,
    }


def build_redacted_tutor_expert_snapshot(tutor_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Compact, UI-safe tutor metadata for expert diagnostics (no prompts / raw LLM text)."""
    if not isinstance(tutor_meta, dict) or not tutor_meta:
        return {"note": "нет tutor metadata (ответ или метаданные ещё не сохранены)"}
    snap: dict[str, Any] = {}
    for key in (
        "orchestration_phase",
        "orchestration_decision_source",
        "policy_clamped",
        "policy_clamp_reasons",
        "tutor_orchestration_pipeline",
        "orchestration_state",
        "pedagogical_orchestrator",
    ):
        if key not in tutor_meta:
            continue
        val = tutor_meta.get(key)
        if key == "tutor_orchestration_pipeline" and isinstance(val, dict):
            snap[key] = {
                str(k): val.get(k)
                for k in list(val.keys())[:30]
                if not str(k).lower().endswith("prompt")
            }
        else:
            snap[key] = val
    decision = tutor_meta.get("decision")
    if isinstance(decision, dict):
        action = decision.get("action") or decision.get("next_action")
        reason = str(decision.get("reason") or "")[:400]
        snap["decision_excerpt"] = {
            "next_action": str(action or "")[:160],
            "reason": reason,
        }
    teaching = tutor_meta.get("teaching")
    if isinstance(teaching, dict):
        snap["teaching_depth"] = teaching.get("depth_level")
    if isinstance(tutor_meta.get("auto_quiz"), dict):
        aq = tutor_meta["auto_quiz"]
        snap["auto_quiz_immediate"] = bool(aq.get("show_immediately"))
    return snap


__all__ = [
    "apply_pedagogical_orchestrator_to_metadata",
    "apply_tutor_self_correction",
    "make_rule_fallback_orchestrator_decision",
    "build_knowledge_graph_subgraph_text",
    "build_tutor_session_state",
    "decide_tutor_next_action",
    "format_quiz_and_reviews_block",
    "format_session_history_for_orchestrator",
    "invoke_pedagogical_orchestrator_llm",
    "normalize_pedagogical_orchestrator_decision",
    "build_redacted_tutor_expert_snapshot",
]
