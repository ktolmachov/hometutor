"""
PedagogicalRouter: graph-augmented оркестратор + опциональные LLM-агенты.

Продовый путь приложения — RAG (``build_query_engine``) + tutor JSON; этот класс нужен для:
- единой точки «решение оркестратора + personalized subgraph»;
- опционального эксперимента с отдельными вызовами суб-агентов (дорого, без retrieval).

Не подменяет ``build_tutor_pipeline`` / ``run_pipeline`` без явного вызова из кода:
``QueryContext``-пайплайн остаётся источником истины (ADR-010; E6.0 — контракт
``metadata["tutor_orchestration_pipeline"]`` + ``trace["tutor_pipeline"]``).
Класс используется для экспериментов и альтернативных entrypoints; продовый путь
``query_mode=tutor`` — шаги в ``pipeline_steps`` + ``invoke_pedagogical_orchestrator_llm``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from llama_index.core.base.llms.types import MessageRole
from llama_index.core.llms import ChatMessage

from app.config import get_settings
from app.knowledge_graph import get_personalized_subgraph
from app.llm_resilience import chat_with_resilience
from app.models import QueryContext
from app.provider import get_graph_llm
from app.quiz_service import get_quiz_llm_for_generation
from app.session_store import session_store
from app.learner_model_service import merge_personalized_into_learner_profile
from app.tutor_orchestrator import (
    build_tutor_session_state,
    format_session_history_for_orchestrator,
    invoke_pedagogical_orchestrator_llm,
)
from app.tutor_personalization_policy import attach_personalization_policy_to_learner_profile
from app.tutor_prompts import (
    CONCEPT_EXPLAINER_PROMPT,
    ERROR_DIAGNOSER_PROMPT,
    MICRO_QUIZ_GENERATOR_PROMPT,
    MOTIVATION_COACH_PROMPT,
    ORCHESTRATOR_AGENT_NAMES,
    SELF_CORRECTION_PROMPT,
    SOCRATIC_QUESTIONER_PROMPT,
)
from app.user_state import get_tutor_learner_profile

logger = logging.getLogger(__name__)


def get_learner_profile(user_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    """Профиль ученика: лёгкий tutor JSON + Personalized Learner Model 19.5."""
    base = get_tutor_learner_profile()
    return merge_personalized_into_learner_profile(base, user_id=user_id, session_id=session_id)


def get_session_history(session_id: str | None, *, last_n: int = 6) -> str:
    """Текст последних сообщений сессии для промпта оркестратора."""
    if not session_id:
        return "(нет session_id)"
    messages = list(session_store.get(session_id))
    return format_session_history_for_orchestrator(messages, limit=last_n)


def _format_focus_concepts(params: dict[str, Any]) -> str:
    fc = params.get("focus_concepts")
    if isinstance(fc, list):
        return ", ".join(str(x).strip() for x in fc if str(x).strip())
    return str(fc or "").strip() or "(не задано)"


class PedagogicalRouter:
    """Оркестратор: personalized subgraph → JSON-решение → опционально суб-агенты → self-correction → micro-quiz."""

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or get_graph_llm()
        self.agents: dict[str, Any] = {
            "ConceptExplainer": self._run_concept_explainer,
            "SocraticQuestioner": self._run_socratic_questioner,
            "ErrorDiagnoser": self._run_error_diagnoser,
            "MotivationCoach": self._run_motivation_coach,
            "MicroQuizGenerator": self._run_micro_quiz_generator,
        }

    def _user_message(self, state: dict[str, Any]) -> str:
        return str(
            state.get("user_message") or state.get("current_user_message") or ""
        ).strip()

    def _resolve_learner_profile(self, state: dict[str, Any]) -> dict[str, Any]:
        lp = state.get("learner_profile")
        if isinstance(lp, dict) and lp:
            return attach_personalization_policy_to_learner_profile(dict(lp))
        persisted = state.get("persisted_learner_profile")
        if not isinstance(persisted, dict):
            persisted = get_tutor_learner_profile()
        orch = build_tutor_session_state(
            current_topic=str(state.get("current_topic") or "general"),
            mastery_level=str(state.get("mastery_level") or "intermediate"),
            preferred_style=str(state.get("preferred_style") or "balanced"),
            learning_goal=str(state.get("learning_goal") or "understand_topic"),
            quiz_difficulty=str(state.get("quiz_difficulty") or "recognition"),
            persisted_profile=persisted,
        )
        state.setdefault("_tutor_session_state_cache", orch)
        lp = orch["learner_profile"]
        return attach_personalization_policy_to_learner_profile(
            lp if isinstance(lp, dict) else {}
        )

    def _conversation_history(self, state: dict[str, Any]) -> list[Any]:
        if state.get("conversation_history") is not None:
            return list(state["conversation_history"])
        sid = state.get("session_id")
        if sid:
            return list(session_store.get(str(sid)))
        return []

    def route_and_execute(
        self,
        state: dict[str, Any],
        *,
        execute_agents: bool = False,
        apply_self_correction_llm: bool | None = None,
    ) -> dict[str, Any]:
        """
        1) personalized subgraph → 2) решение оркестратора (JSON) → 3) опционально LLM-агенты
        → 4) опционально self-correction LLM → 5) micro-quiz при наличии ``query_context``.

        По умолчанию ``execute_agents=False``: решение кладётся в ``state["orchestrator_decision"]``,
        RAG-ответ в приложении строится как раньше (metadata / tutor prompt).

        ``apply_self_correction_llm``: по умолчанию ``settings.enable_self_correction``.
        """
        if apply_self_correction_llm is None:
            apply_self_correction_llm = bool(get_settings().enable_self_correction)

        learner_profile = self._resolve_learner_profile(state)
        uid = state.get("user_id") or "local"
        sid = state.get("session_id")
        learner_profile = merge_personalized_into_learner_profile(
            learner_profile,
            user_id=str(uid) if uid else "local",
            session_id=str(sid) if sid else None,
        )
        state["learner_profile"] = learner_profile
        state["cognitive_load"] = learner_profile.get("cognitive_load")
        state["emotional_state"] = learner_profile.get("emotional_state")
        state["optimal_depth"] = learner_profile.get("optimal_depth")

        try:
            from app.learning_plan_service import get_adaptive_daily_plan_for_orchestrator

            daily_plan = get_adaptive_daily_plan_for_orchestrator(
                user_id=str(uid) if uid else "local",
            )
            if daily_plan:
                state["daily_plan"] = daily_plan
                learner_profile = {**learner_profile, "adaptive_daily_plan": daily_plan}
                state["learner_profile"] = learner_profile
                blocks = daily_plan.get("blocks") if isinstance(daily_plan, dict) else None
                if isinstance(blocks, list) and blocks:
                    first = blocks[0] if isinstance(blocks[0], dict) else {}
                    hint = str(first.get("description") or first.get("type") or "").strip()
                    if hint:
                        state["adaptive_daily_plan_next"] = hint
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("adaptive_daily_plan_in_router_failed", exc_info=True)

        seed = str(state.get("current_topic") or learner_profile.get("focus_topic") or "general")
        limit = int(state.get("subgraph_limit") or 12)
        personalized = get_personalized_subgraph(seed_topic=seed, limit=limit)
        state["personalized_subgraph"] = personalized
        subgraph_text = json.dumps(personalized, ensure_ascii=False, indent=2)

        um = self._user_message(state)
        history_list = self._conversation_history(state)

        decision, usage = invoke_pedagogical_orchestrator_llm(
            learner_profile=learner_profile,
            current_user_message=um or "(пусто)",
            conversation_history=history_list,
            knowledge_graph_subgraph_override=subgraph_text,
        )
        if usage:
            state.setdefault("trace", {})["pedagogical_orchestrator_usage"] = usage

        state["orchestrator_decision"] = decision
        agent_name = str(decision.get("selected_agent") or "ConceptExplainer").strip()
        if agent_name not in ORCHESTRATOR_AGENT_NAMES:
            agent_name = "ConceptExplainer"
        state["selected_agent"] = agent_name
        state["should_trigger_microquiz"] = bool(decision.get("should_trigger_microquiz"))
        state["next_best_action"] = str(decision.get("next_best_action") or "")
        if not state["next_best_action"] and state.get("adaptive_daily_plan_next"):
            state["next_best_action"] = str(state["adaptive_daily_plan_next"])

        if execute_agents:
            fn = self.agents.get(agent_name)
            if fn:
                params = decision.get("parameters") if isinstance(decision.get("parameters"), dict) else {}
                state = fn(state, params)
            else:
                state["agent_error"] = f"unknown_agent:{agent_name}"

        if apply_self_correction_llm and state.get("agent_response"):
            state = self._self_correction(state)

        if state.get("should_trigger_microquiz") and isinstance(
            state.get("query_context"), QueryContext
        ):
            from app.quiz_service import generate_and_attach_micro_quiz

            try:
                state["auto_quiz_payload"] = generate_and_attach_micro_quiz(state["query_context"])
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                logger.exception("pedagogical_router_micro_quiz_failed")
                state["auto_quiz_payload"] = None
        elif state.get("should_trigger_microquiz"):
            state["micro_quiz_note"] = "pass_query_context_for_server_micro_quiz"

        return state

    def _graph_block(self, state: dict[str, Any]) -> str:
        g = state.get("personalized_subgraph") or {}
        return json.dumps(g, ensure_ascii=False, indent=2)[:12000]

    def _chat_user_only(self, prompt: str) -> str:
        r = chat_with_resilience(
            self._llm,
            [ChatMessage(role=MessageRole.USER, content=prompt)],
            stage="orchestrator_router.chat_user_only",
            temperature=0.2,
        )
        return str(r.message.content or "").strip()

    def _chat_user_only_with_llm(self, llm: Any, prompt: str, *, temperature: float = 0.2) -> str:
        r = chat_with_resilience(
            llm,
            [ChatMessage(role=MessageRole.USER, content=prompt)],
            stage="orchestrator_router.chat_user_only_custom_llm",
            temperature=temperature,
        )
        return str(r.message.content or "").strip()

    def _chat_system_user(self, system: str, user: str, *, temperature: float = 0.2) -> tuple[str, Any]:
        r = chat_with_resilience(
            self._llm,
            [
                ChatMessage(role=MessageRole.SYSTEM, content=system),
                ChatMessage(role=MessageRole.USER, content=user),
            ],
            stage="orchestrator_router.chat_system_user",
            temperature=temperature,
        )
        text = str(r.message.content or "").strip()
        return text, r

    def _run_concept_explainer(self, state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        ml = str(state.get("mastery_level") or "intermediate")
        lg = str(state.get("learning_goal") or "understand_topic")
        base = CONCEPT_EXPLAINER_PROMPT.format(mastery_level=ml, learning_goal=lg)
        user = (
            f"{base}\n\nКонтекст графа (JSON):\n{self._graph_block(state)}\n\n"
            f"Сообщение ученика:\n{self._user_message(state)}"
        )
        state["agent_response"] = self._chat_user_only(user)
        return state

    def _run_socratic_questioner(self, state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        fc = _format_focus_concepts(params)
        base = SOCRATIC_QUESTIONER_PROMPT.format(focus_concepts=fc)
        user = f"{base}\n\nКонтекст графа (JSON):\n{self._graph_block(state)}\n\nСообщение ученика:\n{self._user_message(state)}"
        state["agent_response"] = self._chat_user_only(user)
        return state

    def _run_error_diagnoser(self, state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        user = (
            f"{ERROR_DIAGNOSER_PROMPT}\n\nКонтекст графа (JSON):\n{self._graph_block(state)}\n\n"
            f"Фокус: {_format_focus_concepts(params)}\n\nСообщение ученика:\n{self._user_message(state)}"
        )
        state["agent_response"] = self._chat_user_only(user)
        return state

    def _run_motivation_coach(self, state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        lg = str(state.get("learning_goal") or "understand_topic")
        base = MOTIVATION_COACH_PROMPT.format(learning_goal=lg)
        user = f"{base}\n\nКонтекст графа (JSON):\n{self._graph_block(state)}\n\nСообщение ученика:\n{self._user_message(state)}"
        state["agent_response"] = self._chat_user_only(user)
        return state

    def _run_micro_quiz_generator(self, state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        ml = str(state.get("mastery_level") or "intermediate")
        lg = str(state.get("learning_goal") or "understand_topic")
        fc = _format_focus_concepts(params)
        base = MICRO_QUIZ_GENERATOR_PROMPT.format(
            mastery_level=ml,
            learning_goal=lg,
            focus_concepts=fc,
        )
        user = f"{base}\n\nКонтекст графа (JSON):\n{self._graph_block(state)}\n\nСообщение ученика:\n{self._user_message(state)}"
        state["agent_response"] = self._chat_user_only_with_llm(get_quiz_llm_for_generation(), user)
        return state

    def _self_correction(self, state: dict[str, Any]) -> dict[str, Any]:
        ar = str(state.get("agent_response") or "").strip()
        if not ar:
            return state
        correction_prompt = SELF_CORRECTION_PROMPT + "\n\nПредыдущий ответ:\n" + ar
        from app.usage_cost import extract_token_usage

        out, raw = self._chat_system_user(
            "Ты — Self-Correction Agent для ответа репетитора.",
            correction_prompt,
            temperature=0.1,
        )
        state["final_response"] = out
        tr = state.setdefault("trace", {})
        tr["orchestrator"] = state.get("orchestrator_decision")
        u = extract_token_usage(raw)
        if u:
            tr["self_correction_usage"] = u
        return state


__all__ = [
    "PedagogicalRouter",
    "get_learner_profile",
    "get_session_history",
]
