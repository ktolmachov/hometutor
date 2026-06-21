"""
Policy matrix: learning_goal × mastery × due × weak concepts (итерация 19.5).
Используется оркестратором / tutor_cycle для согласованных рекомендаций.
"""

from __future__ import annotations

import re
from typing import Any


def personalization_hints(
    *,
    learning_goal: str,
    mastery_level: str,
    due_reviews_count: int,
    weak_concepts: list[str] | None,
) -> dict[str, Any]:
    """
    Возвращает стабильные подсказки политики (не LLM): глубина объяснения, приоритет quiz, help.
    """
    lg = (learning_goal or "understand_topic").strip().lower()
    ml = (mastery_level or "intermediate").strip().lower()
    due = max(0, int(due_reviews_count or 0))
    weak_n = len([w for w in (weak_concepts or []) if str(w).strip()])

    explanation_depth = "examples"
    if lg == "exam_prep":
        explanation_depth = "deep"
    elif lg == "solve_homework":
        explanation_depth = "step_by_step"
    if ml == "beginner":
        explanation_depth = "simpler" if explanation_depth != "deep" else explanation_depth

    quiz_emphasis = "balanced"
    if due > 0:
        quiz_emphasis = "due_review_first"
    elif weak_n >= 3:
        quiz_emphasis = "weak_concepts_first"
    elif ml == "advanced":
        quiz_emphasis = "transfer_heavy"

    help_policy = "standard"
    if due > 2:
        help_policy = "spaced_repetition_priority"
    elif weak_n >= 2:
        help_policy = "extra_scaffolding"
    elif lg == "solve_homework":
        help_policy = "anti_overhelp_scaffold"

    return {
        "contract_version": 1,
        "explanation_depth": explanation_depth,
        "quiz_emphasis": quiz_emphasis,
        "help_policy": help_policy,
        "inputs": {
            "learning_goal": lg,
            "mastery_level": ml,
            "due_reviews_count": due,
            "weak_concepts_count": weak_n,
        },
    }


def _apply_router_intent_e11r_clamps(
    out: dict[str, Any],
    learner_profile: dict[str, Any],
    reasons: list[str],
) -> None:
    """
    Стабильные контрактные правила intent (E11-R): quiz / Socratic / SRS / error-diagnosis.
    Срабатывают только если в профиле есть ``orchestrator_clamp_user_message`` (pipeline / router eval).
    """
    msg = str(learner_profile.get("orchestrator_clamp_user_message") or "").strip()
    if not msg:
        return
    if not isinstance(out.get("parameters"), dict):
        out["parameters"] = {}
    low = msg.lower()
    hw_level = str(learner_profile.get("homework_level") or "").strip().lower()
    protected_hw = hw_level in {"hint", "plan", "error_review"}
    agent = str(out.get("selected_agent") or "").strip()

    def _bump(reason: str, new_agent: str) -> None:
        nonlocal agent
        if new_agent == agent:
            return
        out["selected_agent"] = new_agent
        reasons.append(reason)
        agent = new_agent

    # 1) Явная диагностика логической ошибки после квиза (immediate feedback).
    if ("логическ" in low or "логичес" in low) and (
        "рассужден" in low or "рассужд" in low or "ошиб" in low
    ) and re.search(r"в\s+ч[её]м", low):
        _bump("intent_explicit_quiz_logic_error_diagnosis", "ErrorDiagnoser")
        return

    # 2) SM-2 / spaced repetition: команда «Повтори <тему>» в начале реплики (не мета «что стоит повторить»).
    if re.match(r"(?is)^\s*повтори\s+\S", msg):
        _bump("intent_sm2_repeat_topic_command", "MicroQuizGenerator")
        out["should_trigger_microquiz"] = True
        return

    # 2b) После реплики ассистента с объяснением — вопрос «Почему…» → Socratic (не повторное лекторское explain).
    if learner_profile.get("orchestrator_prior_assistant_context") and re.match(
        r"(?is)^почему\b",
        msg.strip(),
    ):
        _bump("intent_post_explanation_why_question", "SocraticQuestioner")
        out["parameters"]["question_type"] = "probing"
        return

    # 3) Провал квиза + мета-выбор «что дальше» / упростить (recovery quiz, не разбор ошибки).
    raw_score = learner_profile.get("quiz_answer_score")
    if raw_score is not None:
        try:
            qscore = float(raw_score)
        except (TypeError, ValueError):
            qscore = None
        if qscore is not None and qscore < 0.5:
            if ("что дальше" in low or "упростить" in low) and "логическ" not in low:
                _bump("intent_quiz_failure_recovery_meta_choice", "MicroQuizGenerator")
                out["should_trigger_microquiz"] = True
                return

    # 4) Длинная сессия + выбор «квиз или объяснение» → консолидация объяснением (не новый тест).
    try:
        smc = int(learner_profile.get("session_message_count") or 0)
    except (TypeError, ValueError):
        smc = 0
    if smc >= 12 and "квиз" in low and "объяснен" in low:
        _bump("intent_long_session_consolidation_branch", "ConceptExplainer")
        return

    # 5) Cold start «как работает / how does» без истории → сначала active recall (micro-quiz).
    if smc <= 1 and re.search(r"(?i)\b(как работает|how\s+does|как устроен)\b", low):
        if not re.search(r"(?i)(что такое|what\s+is|what's|кратко:\s*что такое)\b", low):
            _bump("intent_cold_start_mechanism_active_recall", "MicroQuizGenerator")
            out["should_trigger_microquiz"] = True
            return

    # 6) Anti-overhelp: явная просьба «сделай за меня» без scaffold-режима ДЗ.
    overhelp_markers = (
        "реши за меня",
        "сделай за меня",
        "solve for me",
        "do it for me",
        "решение целиком за меня",
    )
    if not protected_hw and any(m in low for m in overhelp_markers):
        _bump("intent_anti_overhelp_solve_for_me", "SocraticQuestioner")
        out["parameters"]["question_type"] = "clarification"
        return

    # 7) Counterfactual / scaling (первые ~40 символов).
    if re.match(r"(?is)^.{0,40}что если\b", msg):
        _bump("intent_counterfactual_challenge", "SocraticQuestioner")
        out["parameters"]["question_type"] = "challenge"
        return

    # 8) Просьба о последствиях / «что ты видишь» — Socratic implications, не готовый лекторский список.
    if (
        ("последств" in low and ("ux" in low or "для ux" in low))
        or "что ты видишь" in low
        or "какой ux" in low
    ):
        _bump("intent_implications_elicit_not_lecture", "SocraticQuestioner")
        out["parameters"]["question_type"] = "implications"
        return

    # 9) Явный drill / самопроверка / короткий вопрос на проверку.
    drill_like = (
        "быстрый drill" in low
        or ("drill" in low and "быстр" in low)
        or "самопроверк" in low
        or "проверь меня" in low
        or ("дай " in low and "вопрос" in low and "коротк" in low)
    )
    if drill_like:
        _bump("intent_explicit_drill_or_self_check", "MicroQuizGenerator")
        out["should_trigger_microquiz"] = True
        return

    # 10) Misconception: ложное утверждение или переконанность в неверном тезисе.
    misconception = (
        "разве не так" in low
        or "правильно ли, что" in low
        or "уверен, что" in low
        or ("bm25" in low and "не нужен" in low)
        or ("rag" in low and "просто" in low and "вектор" in low)
    )
    if misconception:
        _bump("intent_misconception_signal", "ErrorDiagnoser")
        out["parameters"]["question_type"] = "probing"


def attach_personalization_policy_to_learner_profile(
    learner_profile: dict[str, Any],
) -> dict[str, Any]:
    """Добавить ``personalization_policy`` в профиль для LLM-оркестратора (идемпотентно)."""
    if not isinstance(learner_profile, dict):
        return {}
    out = dict(learner_profile)
    if out.get("personalization_policy"):
        return out
    out["personalization_policy"] = personalization_hints(
        learning_goal=str(out.get("learning_goal") or "understand_topic"),
        mastery_level=str(out.get("mastery_level") or "intermediate"),
        due_reviews_count=int(out.get("due_review_count") or 0),
        weak_concepts=list(out.get("weak_concepts") or []),
    )
    return out


def apply_orchestrator_policy_clamp(
    decision: dict[str, Any],
    learner_profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Согласовать решение LLM с rule-based маршрутом (due review / spaced priority).

    Не трогает rule-fallback решения (``_fallback``). Возвращает
    ``({"policy_clamped": bool, "clamp_reasons": [...]}, ...)``.
    """
    reasons: list[str] = []
    if not isinstance(decision, dict) or decision.get("_fallback"):
        return decision, {"policy_clamped": False, "clamp_reasons": []}
    lp = learner_profile if isinstance(learner_profile, dict) else {}
    poly = lp.get("personalization_policy")
    if not isinstance(poly, dict):
        poly = personalization_hints(
            learning_goal=str(lp.get("learning_goal") or "understand_topic"),
            mastery_level=str(lp.get("mastery_level") or "intermediate"),
            due_reviews_count=int(lp.get("due_review_count") or 0),
            weak_concepts=list(lp.get("weak_concepts") or []),
        )
    route = str(lp.get("route") or "standard")
    learning_goal = str(lp.get("learning_goal") or "understand_topic").strip().lower()
    weak_n = len([x for x in (lp.get("weak_concepts") or []) if str(x).strip()])
    due = int(lp.get("due_review_count") or 0)
    qe = str(poly.get("quiz_emphasis") or "")

    out = dict(decision)
    params = out.get("parameters") if isinstance(out.get("parameters"), dict) else {}
    out["parameters"] = dict(params)

    if qe == "due_review_first" and due > 0 and out.get("should_trigger_microquiz") is False:
        out["should_trigger_microquiz"] = True
        reasons.append("due_review_forced_microquiz")

    agent = str(out.get("selected_agent") or "").strip()
    if route == "due_review" and due > 0 and agent == "MotivationCoach":
        out["selected_agent"] = "MicroQuizGenerator"
        preview = [str(x).strip() for x in (lp.get("due_review_preview") or []) if str(x).strip()]
        focus = preview[:3] if preview else [str(lp.get("focus_topic") or "review").strip()]
        out["parameters"]["focus_concepts"] = focus
        reasons.append("due_review_overrides_motivation_agent")

    # Anti-overhelp: для homework держим scaffold-first, не прямую выдачу.
    if learning_goal == "solve_homework" and due == 0 and agent == "ConceptExplainer":
        out["selected_agent"] = "SocraticQuestioner"
        out["parameters"]["question_type"] = "clarification"
        reasons.append("homework_prefers_socratic_scaffold")

    # Misconception-handling: при явных слабых местах не уходим в общий explain.
    if weak_n >= 2 and route in {"targeted_reinforcement", "foundation"} and agent in {
        "ConceptExplainer",
        "MotivationCoach",
    }:
        out["selected_agent"] = "ErrorDiagnoser"
        reasons.append("weak_concepts_require_diagnosis")

    _apply_router_intent_e11r_clamps(out, lp, reasons)

    return out, {"policy_clamped": bool(reasons), "clamp_reasons": reasons}


__all__ = [
    "apply_orchestrator_policy_clamp",
    "attach_personalization_policy_to_learner_profile",
    "personalization_hints",
]
