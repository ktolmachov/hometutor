"""
Адаптивная логика learning plan: снимок daily plan из KV, next-step после micro-quiz,
метаданные confidence dip.

Слой генерации плана — ``app.learning_plan_generation``; публичный фасад —
``app.learning_plan_service``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.adaptive_plan import ADAPTIVE_DAILY_PLAN_KV_KEY
from app.knowledge_graph import JsonKnowledgeGraph, knowledge_graph
from app.learner_state_scope import count_due_reviews_for_kg, filter_due_reviews_for_kg
from app.user_state import get_kv, get_preferred_style
from app.warmup_planner import confidence_dip_public_status

logger = logging.getLogger(__name__)


def get_saved_adaptive_daily_plan() -> dict[str, Any] | None:
    """Последний сохранённый план (``app_kv``), без пересчёта."""
    raw = get_kv(ADAPTIVE_DAILY_PLAN_KV_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def get_adaptive_daily_plan_for_orchestrator(*, user_id: str | None = None) -> dict[str, Any] | None:
    """
    План для оркестратора без пересчёта: только KV и только если ``date`` = сегодня (UTC).
    Иначе ``None`` (план обновляется после взаимодействий / кнопки «Пересчитать» / нового дня при явном build).
    """
    _ = user_id
    saved = get_saved_adaptive_daily_plan()
    if not saved:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    if str(saved.get("date") or "") != today:
        return None
    return saved


def iter_adaptive_daily_plan_blocks(blocks: list[Any]) -> list[tuple[int, dict[str, Any]]]:
    return [(idx, raw) for idx, raw in enumerate(blocks) if isinstance(raw, dict)]


def get_primary_adaptive_daily_plan_block(blocks: list[Any]) -> tuple[int, dict[str, Any]] | None:
    """First actionable daily-plan block; ``auto_loop`` is a fallback-only block."""
    rendered = iter_adaptive_daily_plan_blocks(blocks)
    for item in rendered:
        block_type = str(item[1].get("type") or "").strip()
        if block_type != "auto_loop":
            return item
    return rendered[0] if rendered else None


def get_primary_adaptive_daily_plan_block_from_plan(plan: dict[str, Any]) -> dict[str, Any] | None:
    primary = plan.get("primary_block")
    if isinstance(primary, dict):
        return primary
    fallback = get_primary_adaptive_daily_plan_block(list(plan.get("blocks") or []))
    if fallback is None:
        return None
    return fallback[1]


def primary_learning_item_from_adaptive_daily_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Small cross-channel contract for the user's single primary item for today."""
    if not isinstance(plan, dict):
        return None
    block = get_primary_adaptive_daily_plan_block_from_plan(plan)
    if not isinstance(block, dict):
        return None
    topic = str(
        block.get("concept")
        or block.get("topic")
        or block.get("title")
        or block.get("description")
        or ""
    ).strip()
    if not topic:
        return None
    return {
        "topic": topic,
        "source": "adaptive_daily_plan",
        "date": str(plan.get("date") or ""),
        "block": block,
    }


def get_today_primary_learning_item(*, user_id: str | None = None) -> dict[str, Any] | None:
    plan = get_adaptive_daily_plan_for_orchestrator(user_id=user_id)
    return primary_learning_item_from_adaptive_daily_plan(plan)


def _estimate_ui_mastery_after_micro_quiz(current: str, quiz_ok: bool) -> str:
    """Грубая оценка UI-уровня (beginner/intermediate/advanced) после micro-quiz."""
    cur = (current or "intermediate").strip().lower()
    if cur not in ("beginner", "intermediate", "advanced"):
        cur = "intermediate"
    if not quiz_ok:
        return cur
    if cur == "beginner":
        return "intermediate"
    if cur == "intermediate":
        return "advanced"
    return "advanced"


def _next_topic_hint(kg: JsonKnowledgeGraph, current_topic: str) -> str:
    concepts = list(kg.get_concepts().keys())
    if not concepts:
        return "Практика и применение"
    topo = kg.topological_sort(concepts)
    cur = (current_topic or "").strip()
    if cur in topo:
        i = topo.index(cur)
        if i + 1 < len(topo):
            return topo[i + 1]
    cur_low = cur.lower()
    for i, t in enumerate(topo):
        if cur_low and (cur_low in t.lower() or t.lower() in cur_low):
            if i + 1 < len(topo):
                return topo[i + 1]
            break
    return topo[0] if topo else "Практика и применение"


def get_recommended_next_step_after_micro_quiz(
    *,
    current_topic: str,
    mastery_level: str,
    last_quiz_feedback: dict[str, Any],
    quiz_question_type: str = "application",
    due_reviews_count: int = 0,
    kg: JsonKnowledgeGraph | None = None,
    preferred_style: str | None = None,
) -> dict[str, Any]:
    """
    Единая точка «что дальше» после micro-quiz (согласуется с tutor CTA и spaced repetition).
    """
    kg = kg or knowledge_graph
    topic = (current_topic or "").strip() or "general"
    ml = (mastery_level or "intermediate").strip().lower()
    if ml not in ("beginner", "intermediate", "advanced"):
        ml = "intermediate"

    ps = (preferred_style or "").strip().lower()
    if ps not in ("balanced", "examples", "theory", "practice"):
        ps = get_preferred_style()

    qtype = (quiz_question_type or "application").strip().lower()
    if qtype == "transfer":
        qtype = "application"

    ok = str(last_quiz_feedback.get("status") or "") == "correct"
    nxt = _next_topic_hint(kg, topic)

    due_total = max(int(due_reviews_count or 0), count_due_reviews_for_kg(kg))
    if due_total > 0:
        first = filter_due_reviews_for_kg(kg, limit=1)
        due_item = first[0] if first else None
        return {
            "next_action": "Пора повторить",
            "next_action_reason": (
                f"В очереди интервальных повторений: **{due_total}** тем к повторению."
            ),
            "suggested_ctas": ["Пора повторить", "Проверь меня", "Следующий шаг", "Дай пример"],
            "new_mastery_estimate": _estimate_ui_mastery_after_micro_quiz(ml, ok),
            "topic_progress": f"{topic} → {nxt}",
            "due_count": due_total,
            "due_review": due_item,
        }

    if not ok:
        if qtype == "application":
            next_action = "Дай пример"
            reason = "Закрепить перенос идеи на практику."
        elif qtype == "recall":
            next_action = "Повтори позже"
            reason = "Слабее воспроизведение — полезен повтор и интервальное повторение."
        else:
            next_action = "Объясни проще"
            reason = "Уточнить базовые термины и определения."
        if ps == "examples" and qtype == "application":
            reason = "Ты лучше учишься на примерах — разберём ещё один разбор."
        if ps == "theory" and qtype != "application":
            reason = reason + " С учётом твоего теоретического стиля — уточним формулировки."
        ctas_inc = ["Объясни проще", "Дай пример", "Проверь меня", "Следующий шаг"]
        if ps == "practice":
            ctas_inc = ["Дай задачу на применение", "Проверь меня", "Дай пример", "Следующий шаг"]
        return {
            "next_action": next_action,
            "next_action_reason": reason,
            "suggested_ctas": ctas_inc,
            "new_mastery_estimate": ml,
            "topic_progress": f"{topic} → {nxt}",
        }

    out = {
        "next_action": "Следующий шаг",
        "next_action_reason": f"Уровень {ml}: успешная проверка — можно двигаться дальше по графу.",
        "suggested_ctas": ["Следующий шаг", "Проверь меня", "Дай пример", "Повтори позже"],
        "new_mastery_estimate": _estimate_ui_mastery_after_micro_quiz(ml, True),
        "topic_progress": f"{topic} → {nxt}",
    }
    if ps == "practice":
        out["next_action"] = "Дай задачу на применение"
        out["next_action_reason"] = (
            f"Уровень {ml}: успешная проверка. Ты предпочитаешь практику — закрепим навык задачей."
        )
        cta = list(out["suggested_ctas"])
        if "Дай задачу на применение" not in cta:
            cta.insert(0, "Дай задачу на применение")
        out["suggested_ctas"] = cta[:8]
    elif ps == "examples":
        out["next_action"] = "Дай пример"
        out["next_action_reason"] = (
            f"Уровень {ml}: успешная проверка. Ты лучше учишься на примерах — добавим ещё один пример."
        )
        cta = list(out["suggested_ctas"])
        if "Дай пример" not in cta:
            cta.insert(0, "Дай пример")
        out["suggested_ctas"] = cta[:8]
    elif ps == "theory":
        out["next_action_reason"] = (
            f"Уровень {ml}: успешная проверка — можно углубить теорию и связи между понятиями."
        )
    return out


def attach_confidence_dip_metadata(
    plan_result: dict[str, Any],
    dip_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Не ломает потребителей плана: добавляет sidecar при активном repair-loop."""
    out = dict(plan_result)
    if not isinstance(dip_state, dict) or not dip_state.get("in_remediation"):
        return out
    snap = confidence_dip_public_status(dip_state)
    meta = dict(out.get("confidence_dip_meta") or {})
    meta.update(
        {
            "in_remediation": True,
            "recent_passes": snap.get("passes"),
            "remediation_plan": snap.get("remediation_plan"),
            "low_conf_sequence": snap.get("low_conf_sequence"),
        }
    )
    out["confidence_dip_meta"] = meta
    return out


__all__ = [
    "attach_confidence_dip_metadata",
    "get_adaptive_daily_plan_for_orchestrator",
    "get_primary_adaptive_daily_plan_block",
    "get_primary_adaptive_daily_plan_block_from_plan",
    "get_recommended_next_step_after_micro_quiz",
    "get_saved_adaptive_daily_plan",
    "get_today_primary_learning_item",
    "iter_adaptive_daily_plan_blocks",
    "primary_learning_item_from_adaptive_daily_plan",
]
