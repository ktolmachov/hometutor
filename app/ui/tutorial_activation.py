"""First-ten-minutes activation journey (W2): action-based checkpoints.

Inline, non-blocking coach marks. Full chaptered tour stays optional via dialog.
Does not invent product paths — only references existing views/actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping, Sequence


@dataclass(frozen=True)
class ActivationCheckpoint:
    id: str
    title_ru: str
    body_ru: str
    reason_ru: str
    target_view: str | None
    action_hint_ru: str


# Max 7 steps, ~7–10 minutes path. Copy: one instruction, one action, one reason.
ACTIVATION_CHECKPOINTS: tuple[ActivationCheckpoint, ...] = (
    ActivationCheckpoint(
        id="course_confirmed",
        title_ru="Выберите курс",
        body_ru="Активируйте курс на главной — так ответы и карточки сузятся к вашим материалам.",
        reason_ru="Без курса система не знает, по каким файлам учить.",
        target_view="Mission Control",
        action_hint_ru="Главная → активировать курс",
    ),
    ActivationCheckpoint(
        id="first_question_sent",
        title_ru="Задайте первый вопрос",
        body_ru="Откройте «Быстрый ответ» и спросите что-то по материалам курса.",
        reason_ru="Первый ответ с источниками — быстрый «вау» и проверка, что индекс жив.",
        target_view="Быстрый ответ",
        action_hint_ru="Быстрый ответ → отправить вопрос",
    ),
    ActivationCheckpoint(
        id="source_opened",
        title_ru="Откройте источник",
        body_ru="В ответе раскройте карточку источника — увидите, откуда взялась мысль.",
        reason_ru="Доверие к ответу строится на проверяемых фрагментах, не на «голосе ИИ».",
        target_view="Быстрый ответ",
        action_hint_ru="Карточка источника в ответе",
    ),
    ActivationCheckpoint(
        id="tutor_handoff_completed",
        title_ru="Перейдите к тьютору",
        body_ru="Продолжите разбор в «Чате с тьютором» — контекст вопроса сохраняется.",
        reason_ru="Тьютор углубляет ответ и готовит к проверке.",
        target_view="Чат с тьютором",
        action_hint_ru="Кнопка handoff → Чат с тьютором",
    ),
    ActivationCheckpoint(
        id="micro_quiz_submitted",
        title_ru="Зафиксируйте ответ в quiz",
        body_ru="В «Интерактивный Quiz» ответьте на вопрос и нажмите «Ответить».",
        reason_ru="Проверка без подглядывания — честный сигнал для плана и графа.",
        target_view="Интерактивный Quiz",
        action_hint_ru="Quiz → Ответить",
    ),
    ActivationCheckpoint(
        id="memory_change_seen",
        title_ru="Посмотрите память",
        body_ru="Откройте Knowledge Graph или Flashcards — увидите, что уже «запомнилось».",
        reason_ru="Обучение замкнуто: ответ → проверка → след в памяти.",
        target_view="Knowledge Graph",
        action_hint_ru="Knowledge Graph или Flashcards",
    ),
    ActivationCheckpoint(
        id="mission_control_returned",
        title_ru="Вернитесь на главную",
        body_ru="Вернитесь на Mission Control — там следующий шаг дня.",
        reason_ru="Дом продукта: один экран «что делать сейчас».",
        target_view="Mission Control",
        action_hint_ru="Главная / Mission Control",
    ),
)

ACTIVATION_IDS: tuple[str, ...] = tuple(c.id for c in ACTIVATION_CHECKPOINTS)
ACTIVATION_ACTIVE_KEY = "activation_flow_active"
ACTIVATION_INDEX_KEY = "activation_step_index"
ACTIVATION_DONE_KEY = "activation_completed_ids"
ACTIVATION_SKIPPED_KEY = "activation_flow_skipped"


def checkpoint_by_id(checkpoint_id: str) -> ActivationCheckpoint | None:
    cid = str(checkpoint_id or "").strip()
    for item in ACTIVATION_CHECKPOINTS:
        if item.id == cid:
            return item
    return None


def current_checkpoint(
    *,
    step_index: int,
    completed_ids: Sequence[str],
) -> ActivationCheckpoint | None:
    done = {str(x).strip() for x in completed_ids if str(x).strip()}
    # Prefer first incomplete by canonical order
    for item in ACTIVATION_CHECKPOINTS:
        if item.id not in done:
            return item
    idx = max(0, min(int(step_index or 0), len(ACTIVATION_CHECKPOINTS) - 1))
    if len(done) >= len(ACTIVATION_CHECKPOINTS):
        return None
    return ACTIVATION_CHECKPOINTS[idx]


def activation_progress_payload(
    *,
    active: bool,
    step_index: int,
    completed_ids: Sequence[str],
    skipped: bool = False,
) -> dict[str, Any]:
    done = [str(x).strip() for x in completed_ids if str(x).strip()]
    cur = current_checkpoint(step_index=step_index, completed_ids=done)
    return {
        "active": bool(active) and not skipped,
        "skipped": bool(skipped),
        "step_index": max(0, int(step_index or 0)),
        "completed_ids": done,
        "total": len(ACTIVATION_CHECKPOINTS),
        "current_id": cur.id if cur else None,
        "current_title": cur.title_ru if cur else None,
        "target_view": cur.target_view if cur else None,
    }


def apply_checkpoint_event(
    checkpoint_id: str,
    *,
    active: bool,
    step_index: int,
    completed_ids: Sequence[str],
    skipped: bool = False,
) -> dict[str, Any]:
    """Mark checkpoint done if it is the current (or already past) step.

    Returns new state dict: active, step_index, completed_ids, advanced (bool).
    """
    if skipped or not active:
        return {
            "active": False if skipped else bool(active),
            "step_index": int(step_index or 0),
            "completed_ids": list(completed_ids or []),
            "advanced": False,
            "skipped": bool(skipped),
        }
    cid = str(checkpoint_id or "").strip()
    if cid not in ACTIVATION_IDS:
        return {
            "active": True,
            "step_index": int(step_index or 0),
            "completed_ids": list(completed_ids or []),
            "advanced": False,
            "skipped": False,
        }
    done = [str(x).strip() for x in completed_ids if str(x).strip()]
    if cid in done:
        return {
            "active": True,
            "step_index": int(step_index or 0),
            "completed_ids": done,
            "advanced": False,
            "skipped": False,
        }
    cur = current_checkpoint(step_index=step_index, completed_ids=done)
    # Allow completing current only (no skip-ahead by random events)
    if cur is None or cur.id != cid:
        return {
            "active": True,
            "step_index": int(step_index or 0),
            "completed_ids": done,
            "advanced": False,
            "skipped": False,
        }
    done = list(done) + [cid]
    # Advance index to next incomplete
    next_idx = 0
    for i, item in enumerate(ACTIVATION_CHECKPOINTS):
        if item.id not in set(done):
            next_idx = i
            break
    else:
        next_idx = len(ACTIVATION_CHECKPOINTS)
    still_active = len(done) < len(ACTIVATION_CHECKPOINTS)
    return {
        "active": still_active,
        "step_index": next_idx if still_active else max(0, len(ACTIVATION_CHECKPOINTS) - 1),
        "completed_ids": done,
        "advanced": True,
        "skipped": False,
        "finished": not still_active,
    }


def write_activation_state(state: MutableMapping[str, Any], payload: dict[str, Any]) -> None:
    state[ACTIVATION_ACTIVE_KEY] = bool(payload.get("active"))
    state[ACTIVATION_INDEX_KEY] = int(payload.get("step_index") or 0)
    state[ACTIVATION_DONE_KEY] = list(payload.get("completed_ids") or [])
    if payload.get("skipped"):
        state[ACTIVATION_SKIPPED_KEY] = True
    if payload.get("finished"):
        state[ACTIVATION_ACTIVE_KEY] = False


def read_activation_state(state: MutableMapping[str, Any] | None) -> dict[str, Any]:
    s = state or {}
    return activation_progress_payload(
        active=bool(s.get(ACTIVATION_ACTIVE_KEY)),
        step_index=int(s.get(ACTIVATION_INDEX_KEY) or 0),
        completed_ids=list(s.get(ACTIVATION_DONE_KEY) or []),
        skipped=bool(s.get(ACTIVATION_SKIPPED_KEY)),
    )


__all__ = [
    "ACTIVATION_ACTIVE_KEY",
    "ACTIVATION_CHECKPOINTS",
    "ACTIVATION_DONE_KEY",
    "ACTIVATION_IDS",
    "ACTIVATION_INDEX_KEY",
    "ACTIVATION_SKIPPED_KEY",
    "ActivationCheckpoint",
    "apply_checkpoint_event",
    "checkpoint_by_id",
    "current_checkpoint",
    "read_activation_state",
    "write_activation_state",
]
