"""
Промпты для режима AI Tutor (итерация 19.1): Socratic, квиз, план, next action.

Переменные шаблонов — как в ``app/prompts.py`` (``{context_str}``, ``{query_str}`` и т.д.).
Литеральные фигурные скобки в тексте не используются: иначе ``PromptTemplate``/format
воспримут их как поля шаблона.
"""

from __future__ import annotations

import hashlib
from typing import Any

from llama_index.core.prompts import PromptTemplate

# ─────────────────────────────────────────────────────────────
# Source-of-truth bridge: prompt text теперь в app.prompts.py.
# ─────────────────────────────────────────────────────────────
from app import prompts as _prompt_source

SOCRATIC_TYPES = _prompt_source.SOCRATIC_TYPES
SOCRATIC_TYPE_KEYS = _prompt_source.SOCRATIC_TYPE_KEYS
TUTOR_SYSTEM_PROMPT_V2 = _prompt_source.TUTOR_SYSTEM_PROMPT_V2
TUTOR_RAG_V2_INLINE_QUIZ_SUFFIX = _prompt_source.TUTOR_RAG_V2_INLINE_QUIZ_SUFFIX
TUTOR_RAG_V2_BODY = _prompt_source.TUTOR_RAG_V2_BODY
TUTOR_RAG_QUIZ_BODY = _prompt_source.TUTOR_RAG_V2_BODY
TUTOR_RAG_WITH_QUIZ_PROMPT = _prompt_source.TUTOR_RAG_WITH_QUIZ_PROMPT
TUTOR_SYSTEM_PROMPT = _prompt_source.TUTOR_SYSTEM_PROMPT
QUIZ_PROMPT = _prompt_source.QUIZ_PROMPT
ADAPTIVE_PLAN_PROMPT = _prompt_source.ADAPTIVE_PLAN_PROMPT
NEXT_ACTION_PROMPT = _prompt_source.NEXT_ACTION_PROMPT
ORCHESTRATOR_AGENT_NAMES = _prompt_source.ORCHESTRATOR_AGENT_NAMES
ORCHESTRATOR_DEPTH_TO_ANSWER = _prompt_source.ORCHESTRATOR_DEPTH_TO_ANSWER
ORCHESTRATOR_SYSTEM_PROMPT = _prompt_source.ORCHESTRATOR_SYSTEM_PROMPT
ORCHESTRATOR_DECISION_PROMPT = _prompt_source.ORCHESTRATOR_DECISION_PROMPT
ORCHESTRATOR_OUTPUT_SCHEMA = _prompt_source.ORCHESTRATOR_OUTPUT_SCHEMA
ORCHESTRATOR_PROMPT_FINGERPRINT = _prompt_source.ORCHESTRATOR_PROMPT_FINGERPRINT
ORCHESTRATOR_PROMPT_LEVEL = _prompt_source.ORCHESTRATOR_PROMPT_LEVEL
CONCEPT_EXPLAINER_PROMPT = _prompt_source.CONCEPT_EXPLAINER_PROMPT
SOCRATIC_QUESTIONER_PROMPT = _prompt_source.SOCRATIC_QUESTIONER_PROMPT
ERROR_DIAGNOSER_PROMPT = _prompt_source.ERROR_DIAGNOSER_PROMPT
MOTIVATION_COACH_PROMPT = _prompt_source.MOTIVATION_COACH_PROMPT
MICRO_QUIZ_GENERATOR_PROMPT = _prompt_source.MICRO_QUIZ_GENERATOR_PROMPT
SELF_CORRECTION_PROMPT = _prompt_source.SELF_CORRECTION_PROMPT
_LEARNING_GOAL_HINTS = _prompt_source.TUTOR_LEARNING_GOAL_HINTS
_ANSWER_DEPTH_HINTS = _prompt_source.TUTOR_ANSWER_DEPTH_HINTS
_PREFERRED_STYLE_HINTS = _prompt_source.TUTOR_PREFERRED_STYLE_HINTS
SYSTEM_RULES = _prompt_source.SYSTEM_RULES

select_socratic_followup_type = _prompt_source.select_socratic_followup_type
build_tutor_rag_prompt_with_quiz_difficulty = _prompt_source.build_tutor_rag_prompt_with_quiz_difficulty
build_flashcard_handoff_tutor_prompt = _prompt_source.build_flashcard_handoff_tutor_prompt
get_tutor_prompt = _prompt_source.get_tutor_prompt
HOMEWORK_MODES = _prompt_source.HOMEWORK_MODES
infer_homework_level_from_message = _prompt_source.infer_homework_level_from_message

_ORCHESTRATOR_PROMPT_MATERIAL = getattr(_prompt_source, "_ORCHESTRATOR_PROMPT_MATERIAL", None)


__all__ = [
    "ADAPTIVE_PLAN_PROMPT",
    "build_flashcard_handoff_tutor_prompt",
    "build_tutor_rag_prompt_with_quiz_difficulty",
    "CONCEPT_EXPLAINER_PROMPT",
    "ERROR_DIAGNOSER_PROMPT",
    "get_tutor_prompt",
    "HOMEWORK_MODES",
    "infer_homework_level_from_message",
    "MICRO_QUIZ_GENERATOR_PROMPT",
    "MOTIVATION_COACH_PROMPT",
    "NEXT_ACTION_PROMPT",
    "ORCHESTRATOR_AGENT_NAMES",
    "ORCHESTRATOR_DECISION_PROMPT",
    "ORCHESTRATOR_DEPTH_TO_ANSWER",
    "ORCHESTRATOR_OUTPUT_SCHEMA",
    "ORCHESTRATOR_PROMPT_FINGERPRINT",
    "ORCHESTRATOR_PROMPT_LEVEL",
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "QUIZ_PROMPT",
    "SELF_CORRECTION_PROMPT",
    "SOCRATIC_QUESTIONER_PROMPT",
    "select_socratic_followup_type",
    "SOCRATIC_TYPE_KEYS",
    "SOCRATIC_TYPES",
    "TUTOR_RAG_QUIZ_BODY",
    "TUTOR_RAG_WITH_QUIZ_PROMPT",
    "TUTOR_SYSTEM_PROMPT",
    "TUTOR_SYSTEM_PROMPT_V2",
]
