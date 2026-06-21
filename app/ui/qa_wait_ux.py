"""US-3.5: педагогический копирайт ожидания и ненавязчивое подкрепление в Quick Answer."""

from __future__ import annotations

import hashlib
from typing import Final

# Согласовано с app.ui.answer_helpers.answer_latency_bucket_label_ru: «быстро» — < 2 с.
FAST_ANSWER_MS_THRESHOLD: Final[float] = 2000.0

_WAIT_RUNWAY_MESSAGES: tuple[str, ...] = (
    "Собираем опорные фрагменты из ваших материалов — обычно это несколько секунд.",
    "Сопоставляем вопрос с тем, что уже есть в вашей базе знаний.",
    "Ищем наиболее близкие по смыслу отрывки, чтобы ответ опирался на источники.",
    "Проверяем, насколько найденные фрагменты подходят к вашему вопросу.",
    "Формулируем ответ так, чтобы было видно, откуда взята информация.",
    "Ещё чуть-чуть: подбираем ссылки на конкретные места в файлах.",
)

_SUCCESS_PHRASES: tuple[str, ...] = (
    "Ответ готов — при желании загляните в источники ниже, чтобы закрепить мысль.",
    "Готово. Короткая сверка с источниками обычно помогает лучше запомнить.",
    "Собрали ответ; карточки источников справа покажут, из чего он сложился.",
)

# Stage-aware подписи ожидания (MoT #2): одна фаза за запрос, детерминированный выбор.
WAIT_STAGE_LABELS_RU: Final[tuple[str, ...]] = (
    "Ищем релевантные фрагменты в вашей базе.",
    "Сверяем найденное с вашим вопросом.",
    "Формулируем ответ со ссылками на источники.",
)


def wait_runway_message_for_question(question: str) -> str:
    """Детерминированный выбор фразы ожидания (ротация по тексту вопроса, одна фаза за запрос)."""
    raw = (question or "").strip()
    seed = raw.encode("utf-8") if raw else b"empty"
    idx = hashlib.sha256(seed).digest()[0] % len(_WAIT_RUNWAY_MESSAGES)
    return _WAIT_RUNWAY_MESSAGES[idx]


def wait_stage_message_for_question(question: str) -> str:
    """Одна стадия ожидания за запрос (детерминированно по тексту вопроса)."""
    raw = (question or "").strip()
    seed = raw.encode("utf-8") if raw else b"empty"
    idx = hashlib.sha256(seed).digest()[2] % len(WAIT_STAGE_LABELS_RU)
    return WAIT_STAGE_LABELS_RU[idx]


def answer_column_skeleton_placeholder_html() -> str:
    """Skeleton под колонку «Ответ»: фиксированные отступы/высота, чтобы снизить layout jump после загрузки."""
    bar = (
        "background:var(--secondaryBackgroundColor,#e8eef0);border-radius:4px;"
        "opacity:0.5;display:block;"
    )
    return (
        '<div class="qa-answer-skeleton" role="status" aria-live="polite" '
        'style="min-height:12rem;padding:0.15rem 0;" data-qa-wait-skeleton="1">'
        f'<span style="{bar}height:0.72rem;width:38%;margin-bottom:0.7rem;"></span>'
        f'<span style="{bar}height:0.58rem;width:100%;margin-bottom:0.42rem;"></span>'
        f'<span style="{bar}height:0.58rem;width:92%;margin-bottom:0.42rem;"></span>'
        f'<span style="{bar}height:0.58rem;width:88%;margin-bottom:0.42rem;"></span>'
        f'<span style="{bar}height:0.58rem;width:70%;margin-bottom:0;"></span>'
        "</div>"
    )


def progressive_reveal_markup(answer_markdown: str, *, prefer_instant: bool) -> str:
    """Прогрессивное раскрытие с мгновенным fallback (Req 2.5): при prefer_instant — без обёртки."""
    if not isinstance(answer_markdown, str):
        return ""
    body = answer_markdown
    if prefer_instant:
        return body
    return f"<!-- qa-progressive-reveal -->\n{body}"


def fast_success_reinforcement_phrase(question: str) -> str:
    """Короткая ненавязчивая фраза после быстрого ответа (вариативность без анимации)."""
    key = ((question or "").strip() or "q").encode("utf-8")
    idx = hashlib.sha256(key).digest()[1] % len(_SUCCESS_PHRASES)
    return _SUCCESS_PHRASES[idx]


def answer_qualifies_for_fast_success_reinforcement(
    *,
    total_answer_ms: object,
    confidence: dict | None,
    sources: list | None,
) -> bool:
    """Порог latency «быстро» + базовые trust-сигналы: не низкая уверенность и есть источники."""
    if total_answer_ms is None:
        return False
    try:
        ms = float(total_answer_ms)
    except (TypeError, ValueError):
        return False
    if ms >= FAST_ANSWER_MS_THRESHOLD:
        return False
    conf = confidence if isinstance(confidence, dict) else {}
    if conf.get("level") == "low":
        return False
    src = sources or []
    if not src:
        return False
    return True
