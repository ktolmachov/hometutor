"""Scoped quiz generation (split from ``app.quiz_service``)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from app.config import get_settings
from app.latency_budget import budget_meta_to_session_event, with_budget
from app.llm_resilience import complete_with_resilience
from app.prompts import QUIZ_SCOPED_PROMPT, normalize_quiz_learning_mode, quiz_mc_mode_block
from app.quiz_parse import (
    _MAX_CONTEXT_CHARS,
    _SCOPED_DIFFICULTIES,
    _strip_code_fence,
)

logger = logging.getLogger(__name__)

def _normalize_scoped_questions(raw: list[Any]) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(raw, list):
        return [], "Корень JSON должен быть массивом."
    n = len(raw)
    if n < 5 or n > 8:
        return [], f"Ожидалось 5–8 вопросов, получено {n}."
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"Вопрос {i + 1}: ожидался объект JSON."
        q = (item.get("question") or "").strip()
        opts = item.get("options")
        ci = item.get("correct_index")
        diff = str(item.get("difficulty") or "recall").strip().lower()
        if diff not in _SCOPED_DIFFICULTIES:
            diff = "recall"
        if not q:
            return [], f"Вопрос {i + 1}: пустой текст."
        if not isinstance(opts, list) or len(opts) != 4:
            return [], f"Вопрос {i + 1}: нужно ровно 4 варианта."
        if not all(isinstance(o, str) and o.strip() for o in opts):
            return [], f"Вопрос {i + 1}: варианты должны быть непустыми строками."
        if not isinstance(ci, int) or ci < 0 or ci > 3:
            return [], f"Вопрос {i + 1}: correct_index должен быть 0..3."
        out.append(
            {
                "question": q,
                "options": [o.strip() for o in opts],
                "correct_index": ci,
                "difficulty": diff,
                "explanation": str(item.get("explanation") or "").strip(),
            }
        )
    return out, None


def parse_scoped_quiz_json(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Разбор JSON scoped-quiz (5–8 вопросов, поле difficulty)."""
    cleaned = _strip_code_fence((text or "").strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", cleaned)
        if not m:
            return [], "Не удалось разобрать JSON с вопросами."
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return [], f"JSON ошибка: {e}"
    if not isinstance(data, list):
        return [], "Корень JSON должен быть массивом."
    return _normalize_scoped_questions(data)


def _scoped_adaptive_profile_hint(level: str) -> str:
    return {
        "recognition": "Больше узнавания терминов и определений; формулировки ближе к тексту.",
        "recall": "Больше вопросов на воспроизведение без прямого цитирования.",
        "transfer": "Больше коротких сценариев и применения к новым ситуациям.",
    }.get(level, "Сбалансированный микс recognition / recall / transfer.")


def estimate_mastery_percent(concept: str) -> int:
    """Грубая оценка % для мотивации (по уровню в quiz_mastery)."""
    from app.quiz_adaptive import get_recommended_difficulty

    lv = get_recommended_difficulty(concept)
    return {"recognition": 44, "recall": 68, "transfer": 82}.get(lv, 55)


def weak_spot_scoped_quiz_params(weak_concepts: list[str]) -> dict[str, Any] | None:
    """
    Параметры для ``generate_scoped_quiz`` по первому слабому концепту (topic scope).
    Возвращает None, если список пуст.
    """
    if not weak_concepts:
        return None
    ident = str(weak_concepts[0]).strip()
    if not ident:
        return None
    return {"scope": "topic", "identifier": ident}


def scoped_quiz_xp_reward(correct: int, total: int) -> int:
    if total <= 0:
        return 0
    ratio = correct / total
    return max(5, min(45, int(8 + ratio * 32)))


def generate_scoped_quiz(
    scope: Literal["document", "topic"],
    identifier: str,
    num_questions: int = 6,
    difficulty: str = "adaptive",
    *,
    learning_mode: str | None = None,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    """
    Единая точка входа для scoped-тестов: 5–8 вопросов (MC), микс Recognition / Recall / Transfer.
    """
    from app.explain_service import explain_file
    from app.knowledge_graph import get_topic_subgraph, synthesize_topic_summary
    from app.quiz_adaptive import get_adaptive_difficulty

    ident = (identifier or "").strip()
    if not ident:
        return {"success": False, "error": "Пустой identifier.", "questions": []}

    nq = max(5, min(8, int(num_questions)))

    if scope == "document":
        try:
            doc = explain_file(ident)
        except Exception as e:  # noqa: BLE001 - scoped document quiz degrades to a user-facing error.
            logger.exception("scoped quiz explain_file failed")
            return {"success": False, "error": str(e), "questions": []}
        content = (doc.get("content_preview") or "").strip()
        title = ident
        subgraph: dict[str, Any] = {"topic_name": title, "key_concepts": [], "documents": [ident]}
        adaptive_level = get_adaptive_difficulty(difficulty, ident)
        extra = "—"
    else:
        if source_paths:
            from app.knowledge_synthesis import fetch_document_chunks_text
            try:
                content = fetch_document_chunks_text(source_paths, topic_query=ident)
            except Exception as e:  # noqa: BLE001 - scoped topic quiz degrades to a user-facing error.
                logger.exception("scoped topic quiz (source_paths) failed")
                return {"success": False, "error": str(e), "questions": []}
            title = ident
            subgraph = {"topic_name": ident, "key_concepts": [], "documents": list(source_paths)}
            adaptive_level = get_adaptive_difficulty(difficulty, ident)
            extra = "—"
        else:
            try:
                subgraph = get_topic_subgraph(ident)
                content = synthesize_topic_summary(ident)
            except Exception as e:  # noqa: BLE001 - scoped topic quiz degrades to a user-facing error.
                logger.exception("scoped topic quiz failed")
                return {"success": False, "error": str(e), "questions": []}
            title = str(subgraph.get("topic_name") or ident)
            adaptive_level = get_adaptive_difficulty(difficulty, ident)
            kc = subgraph.get("key_concepts") or []
            extra = ", ".join(str(x) for x in kc[:24]) if kc else "—"

    if len(content) < 120:
        return {
            "success": False,
            "error": "Слишком мало текста для генерации quiz (нужно хотя бы ~120 символов).",
            "questions": [],
        }

    def _generate_body() -> dict[str, Any]:
        trimmed = content[:_MAX_CONTEXT_CHARS]
        mode_key = normalize_quiz_learning_mode(
            learning_mode or get_settings().quiz_learning_mode_default
        )
        prompt = QUIZ_SCOPED_PROMPT.format(
            mode_block=quiz_mc_mode_block(mode_key),
            num_questions=nq,
            adaptive_profile=_scoped_adaptive_profile_hint(adaptive_level),
            title=(title or "без названия").strip() or "без названия",
            extra_context=extra,
            context_str=trimmed,
        )
        try:
            from app.quiz_service import get_quiz_llm_for_generation as _quiz_llm

            llm = _quiz_llm()
            response = complete_with_resilience(
                llm,
                prompt,
                stage="quiz.scoped.generate",
                temperature=0.25,
            )
            text = (response.text or "").strip()
        except Exception as e:  # noqa: BLE001 - scoped quiz LLM failures are returned as controlled errors.
            logger.exception("scoped quiz LLM failed")
            return {"success": False, "error": f"Ошибка LLM: {e}", "questions": []}

        questions, err = parse_scoped_quiz_json(text)
        if err or not questions:
            return {
                "success": False,
                "error": err or "Пустой или невалидный quiz",
                "questions": [],
            }

        pct = estimate_mastery_percent(ident)
        xp_max = scoped_quiz_xp_reward(len(questions), len(questions))

        if scope == "document":
            motivation = (
                f"Ты на **{pct}%** знаешь этот документ! 🔥 **+{xp_max} XP** при идеальном результате"
            )
        else:
            motivation = (
                f"Глубокий тест по теме **{title}** — до **+{xp_max} XP** 🔥"
            )

        return {
            "success": True,
            "scope": scope,
            "identifier": ident,
            "num_questions": len(questions),
            "questions": questions,
            "motivation": motivation,
            "motivation_detail": f"Оценка по прогрессу: **{pct}%** · streak и расписание повторений обновятся после «Завершить».",
            "subgraph": subgraph,
            "adaptive_level": adaptive_level,
            "mastery_estimate_percent": pct,
            "xp_max": xp_max,
        }

    budget = with_budget("quiz_gen", _generate_body)
    payload = dict(budget.result)
    payload["latency_budget"] = budget_meta_to_session_event(budget.meta)
    return payload
