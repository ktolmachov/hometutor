"""Rule-based Smart Study Router recommendation contract.

Локально проверяемые explainability-сигналы живут в ``app/smart_study_evidence.py``.
Финализация леджера по финальному маршруту: ``finalize_smart_study_confidence_ledger_lines`` (там же, реэкспорт через ``app.smart_study_router``).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal


SmartStudyRouterHintKind = Literal[
    "cards_due",
    "sm2_due",
    "quiz_failed",
    "tutor_resume",
    "answer_ready",
    "mastery_stale",
    "adaptive_plan",
    "safe_default",
]

SmartStudyPrimaryNav = Literal[
    "flashcards_review",
    "sm2_tutor",
    "quiz_recovery_tutor",
    "tutor_resume",
    "qa_continue",
    "tutor_weak_gap",
    "plan_block_tutor",
    "safe_tutor_5min",
]


@dataclass(frozen=True)
class SmartStudySecondaryAction:
    """Безопасное вторичное действие (не скрывает основные режимы приложения)."""

    action_id: str
    label_ru: str


@dataclass(frozen=True)
class SmartStudyRecommendation:
    """US-20.x: локальный детерминированный контракт «объяснимого следующего шага»."""

    hint_kind: SmartStudyRouterHintKind
    primary_label_ru: str
    why_now_ru: str
    primary_nav: SmartStudyPrimaryNav
    secondaries: tuple[SmartStudySecondaryAction, ...]
    route_pedagogy_ru: str = ""
    ml_audit_ru: str = ""


def smart_study_contrastive_explanation(rec: SmartStudyRecommendation) -> str:
    """US-20.7: компактное «лучше, чем X» относительно видимого альтернативного режима.

    Учитывает итоговый rec после overlay/defer (hint_kind = исходный сигнал, primary_nav = фактический шаг).
    """
    hk = rec.hint_kind
    nav = rec.primary_nav
    lab_l = rec.primary_label_ru.lower()

    if nav == "qa_continue" and ("источник" in lab_l or "свериться" in lab_l):
        return (
            "Сначала можно спокойно сверить выдержки из индекса, а уже потом идти в quiz или длинный чат."
        )

    if hk == "cards_due" and nav == "safe_tutor_5min":
        return (
            "Мягкий вход через чат оставляет карточки на потом, без ощущения срочного повтора."
        )
    if hk == "sm2_due" and nav == "qa_continue":
        return (
            "Сначала можно сверить формулировку и источники в быстром ответе, затем вернуться к повтору концепта."
        )
    if hk == "quiz_failed" and nav == "qa_continue":
        return (
            "Перед разбором ошибки квиза полезнее уточнить вопрос по базе, чем сразу углубляться в диалог."
        )
    if hk == "tutor_resume" and nav == "safe_tutor_5min":
        return (
            "Мягче, чем насильно возвращать длинный контекст: короткий шаг без давления на прошлую сессию."
        )
    if hk == "answer_ready" and nav == "safe_tutor_5min":
        return (
            "Альтернатива шагу с быстрым ответом: один мини-ход в тьюторе без перегруза вместо следующего действия Q&A."
        )
    if hk == "mastery_stale" and nav == "qa_continue":
        return (
            "Сначала опереться на цитаты полезнее, чем идти в чат без сверки с материалом базы."
        )
    if hk == "adaptive_plan" and nav == "qa_continue":
        return (
            "Короткая сверка с источниками перед шагом плана помогает зайти в чат с ясной опорой."
        )
    if hk == "safe_default" and nav == "qa_continue":
        return (
            "Спокойная проверка фрагментов в Q&A вместо длинного чата, когда нет сильных сигналов очередей."
        )

    if nav == "flashcards_review":
        return (
            "Карточки с интервалами уже ждут повторения; это короткий способ не потерять материал."
        )
    if nav == "sm2_tutor":
        return (
            "Концепты SM-2 созрели по расписанию; повторение сейчас поддержит долгую память лучше, чем новые flashcards."
        )
    if nav == "quiz_recovery_tutor":
        return (
            "После ошибки полезно сначала разобрать её с тьютором, а не сразу запускать новый quiz."
        )
    if nav == "plan_block_tutor":
        return "Шаг плана помогает продолжить день последовательно, без лишнего переключения режимов."
    if nav == "tutor_resume":
        return "Можно сохранить нить темы и микроконтекст прошлой сессии, не начиная с нуля."
    if nav == "qa_continue" and hk == "answer_ready":
        return (
            "Сначала можно перенести быстрый ответ в освоение темы, а quiz оставить следующим действием."
        )
    if nav == "tutor_weak_gap":
        return (
            "Разбор пробела по теме даёт больше, чем короткий quiz без объяснения."
        )
    if nav == "safe_tutor_5min" and hk == "safe_default":
        return (
            "Прямого сравнения с quiz или очередями нет — мало локальных сигналов; ориентируйтесь на абзац основной причины выше."
        )
    if nav == "safe_tutor_5min":
        return (
            "Короткий структурированный чат вместо более тяжёлого режима, который вы временно отложили."
        )

    return "Недостаточно данных, чтобы честно сравнить с другим режимом; ниже — основная причина шага."


_WHYNOT_MAX_WORDS = 80


def _truncate_russian_words(text: str, *, max_words: int = _WHYNOT_MAX_WORDS) -> str:
    words = [w for w in str(text).replace("\n", " ").strip().split() if w]
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(".,;:—").rstrip() + "…"


def smart_study_why_not_others_ru(rec: SmartStudyRecommendation) -> str:
    """Contrastive блок US-20: явно именует тьютора, quiz, карточки и прогресс как отложенные режимы.

    Детерминированная копийка по финальному маршруту (после overlay/steering), без смены правил роутера.
    """
    nav = str(rec.primary_nav)
    hk = str(rec.hint_kind)

    paragraph: str
    if nav == "flashcards_review":
        paragraph = (
            "Приоритет — интервальные карточки: они уже созрели к повтору и поддерживают удержание. "
            "Свободный чат тьютора и дополнительный интерактивный quiz сейчас отложены, чтобы не распылять "
            "внимание вне намеченной короткой сессии повторений. Экран прогресса оставлен на обзор трендов "
            "после завершённого блока самих карточек."
        )
    elif nav == "sm2_tutor":
        paragraph = (
            "Приоритет — повтор концептов SM-2 по расписанию: окно интервальной памяти узкое. "
            "Свободный чат с тьютором без явной очередной цели и новый quiz сейчас вторичнее, пока не закрыт "
            "минимальный цикл интервалов; дополнительные карточки не должны маскировать просроченные шаги. "
            "Экран прогресса не выполняет сами интервалы — только даёт общую картину."
        )
    elif nav == "quiz_recovery_tutor":
        paragraph = (
            "Приоритет — разобрать провал последнего quiz с опорой на тьютора, чтобы не закрепить ошибочную модель. "
            "Ещё один интерактивный quiz до разговора вторичнее. Свободный чат вне ошибки вторичнее, пока нет понимания сбоя. "
            "Карточки по расписанию и статистический прогресс остаются ниже этого микрофокуса."
        )
    elif nav == "tutor_resume":
        paragraph = (
            "Приоритет — сохранить нить темы и живой контекст в чате тьютора после прошлой сессии. "
            "Стартовый quiz с параллельной нулевой задачей сейчас отложим, чтобы не разорвать линию обсуждения. "
            "Очереди карточек ждут по своим триггерам — не подменяем ими возобновление диалоговой темы. "
            "Экран прогресса не заменяет продолжение разговора, его удобно открыть после шага темы."
        )
    elif nav == "qa_continue" and hk == "answer_ready":
        paragraph = (
            "Приоритет — зафиксировать базу через быстрый ответ и цитаты, прежде чем уходить в интерактивный навык. "
            "Длинный тьютор и новый quiz сейчас вторичнее — не смешиваем проверку навыков с уточнением фактов. "
            "Карточки живут своим календарём повторений, экран прогресса служит мета-обзором после короткой зацепки источников."
        )
    elif nav == "qa_continue":
        paragraph = (
            "Приоритет — быстрая верификация выдержкой из базы перед тяжёлыми режимами. Свободный тьютор и quiz "
            "с большим объёмом сценариев оставлены на следующий шаг после сверки. Карточки не отменяются, но задают "
            "отдельный ритм. Экран прогресса не должен заменять сам точечный переход здесь и сейчас."
        )
    elif nav == "tutor_weak_gap":
        paragraph = (
            "Приоритет — закрыть конкретное слабое место понимания в тьюторе. Quiz до понимания рискует превратиться в "
            "угадайку без разборов. Свободный чат вне задачи вторичнее. Интервальные карточки и статистический прогресс "
            "не диагностируют pinpoint-пробел и остаются в стороне до фокусированного диалога."
        )
    elif nav == "plan_block_tutor":
        paragraph = (
            "Приоритет — связный шаг адаптивного плана, чтобы сохранять дневную последовательность. Свободный quiz и случайная "
            "тьюторская сессия вне блока вторичнее. Карточки и экран прогресса доступны как параллельные входы, но не как "
            "замена переходу, который предлагает план именно здесь и сейчас."
        )
    elif nav == "safe_tutor_5min" and hk == "cards_due":
        paragraph = (
            "Приоритет — один мягкий заход через тьютора вместо жёсткого повтора карточек: вы сохранили мотивацию, не отменяя "
            "наличие очереди интервалов радом. Интерактивный quiz и обзор прогресса оставлены после короткой сессии, чтобы не "
            "смешивать короткий тёплый шаг с громоздкими проверками карточками уже ждущими своего времени после шага выше."
        )
    elif nav == "safe_tutor_5min":
        paragraph = (
            "Приоритет — спокойный мини-ход через тьютора при малом числе локальных сигналов очередей. Жёсткий quiz и затяжной "
            "чат вторичнее, пока нет узких оснований давления. Интервальные карточки и экран прогресса остаются вашими вторичными "
            "режимами: их открывают явным выбором, но основной маленький шаг задаёт диалог здесь и сейчас."
        )
    else:
        paragraph = (
            "Подсказка опирается на текущие локальные сигналы без изменения правил выбора. Чат тьютора, интерактивный quiz, "
            "повтор карточек и экран прогресса остаются доступными рядом; их можно открыть отдельно, если хочется переключиться."
        )

    return _truncate_russian_words(paragraph, max_words=_WHYNOT_MAX_WORDS)


def _quiz_feedback_failed(status: str | None) -> bool:
    s = str(status or "").strip().lower()
    return s in ("fail", "failed", "incorrect", "wrong", "bad", "partial")


def _ru_flashcard_due_word(n: int) -> str:
    """Склонение «N карточек» для строки короткой причины шага."""
    k = int(n)
    if k % 100 in (11, 12, 13, 14):
        return "карточек"
    if k % 10 == 1:
        return "карточка"
    if k % 10 in (2, 3, 4):
        return "карточки"
    return "карточек"


_SSR_SOURCE_COVERAGE_GUARD_PRIMARY: frozenset[SmartStudyPrimaryNav] = frozenset(
    {
        "quiz_recovery_tutor",
        "sm2_tutor",
        "tutor_resume",
        "tutor_weak_gap",
        "plan_block_tutor",
        "safe_tutor_5min",
    }
)

_SSR_GUARD_PEDAGOGY_RU = (
    "Тип приоритета: доверие к выдержкам — при недостаточном покрытии источниками проверка в quiz "
    "или длинном тьюторе будет ненадёжной; сначала сверка с базой."
)


def _retrieval_confidence_is_low(val: str | float | None) -> bool:
    """True только при явно заданном низком confidence (отсутствие значения = нет сигнала)."""
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return float(val) < 0.5
    s = str(val).strip().lower()
    if not s:
        return False
    if s in {"high", "good", "strong", "ok", "okay", "medium", "mid", "moderate", "neutral"}:
        return False
    return s in {"low", "weak", "poor", "bad", "very_low", "uncertain"}


def source_coverage_route_guard_should_apply(
    *,
    retrieval_confidence: str | float | None = None,
    source_evidence_count: int | None = None,
) -> bool:
    """US-20.x: guard активен при низком retrieval confidence или недостаточном числе источников (<2)."""
    if _retrieval_confidence_is_low(retrieval_confidence):
        return True
    if source_evidence_count is None:
        return False
    return int(source_evidence_count) < 2


def apply_source_coverage_route_guard(
    rec: SmartStudyRecommendation,
    *,
    retrieval_confidence: str | float | None = None,
    source_evidence_count: int | None = None,
) -> SmartStudyRecommendation:
    """Не предлагает quiz/тьютор как primary, если мало доверия к retrieval/coverage — ведёт в Q&A/источники."""
    # Lazy import: избегаем цикла recommendation ↔ scoring при загрузке модулей.
    from app.smart_study_scoring import _stable_secondaries

    if not source_coverage_route_guard_should_apply(
        retrieval_confidence=retrieval_confidence,
        source_evidence_count=source_evidence_count,
    ):
        return rec
    if rec.primary_nav not in _SSR_SOURCE_COVERAGE_GUARD_PRIMARY:
        return rec
    audit = (str(rec.ml_audit_ru or "").strip() + " source_coverage_route_guard=1").strip()
    return replace(
        rec,
        primary_nav="qa_continue",
        primary_label_ru="Свериться с источниками",
        why_now_ru=(
            "Источников в индексе мало для честной проверки — сначала откройте быстрый ответ и список цитат "
            "или уточните вопрос; интерактивный quiz и длинный чат тьютора остаются вторичными."
        ),
        route_pedagogy_ru=_SSR_GUARD_PEDAGOGY_RU,
        secondaries=_stable_secondaries(primary_nav="qa_continue"),
        ml_audit_ru=audit,
    )


from app.smart_study_scoring import (
    _STEERING_PREFS,
    _ssr_recommendation_for_kind,
    apply_smart_study_steering_preference,
)


def _build_smart_study_recommendation_rules(
    *,
    surface: Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"],
    flashcard_due_n: int = 0,
    sm2_due_n: int = 0,
    quiz_feedback_status: str | None = None,
    has_tutor_resume: bool = False,
    tutor_topic: str | None = None,
    has_last_answer_qa: bool = False,
    has_reading_resume: bool = False,
    first_weak_concept: str | None = None,
    plan_primary_block: dict[str, Any] | None = None,
) -> SmartStudyRecommendation:
    """Deterministic rule-only baseline for SSR."""
    for hint_kind in (
        "cards_due",
        "sm2_due",
        "quiz_failed",
        "adaptive_plan",
        "tutor_resume",
        "answer_ready",
        "mastery_stale",
        "safe_default",
    ):
        rec = _ssr_recommendation_for_kind(
            hint_kind,
            surface=surface,
            flashcard_due_n=flashcard_due_n,
            sm2_due_n=sm2_due_n,
            quiz_feedback_status=quiz_feedback_status,
            has_tutor_resume=has_tutor_resume,
            tutor_topic=tutor_topic,
            has_last_answer_qa=has_last_answer_qa,
            has_reading_resume=has_reading_resume,
            first_weak_concept=first_weak_concept,
            plan_primary_block=plan_primary_block,
        )
        if rec is not None:
            return rec
    raise RuntimeError("Smart Study Router failed to build fallback recommendation")
