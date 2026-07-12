"""Scoring and steering helpers for Smart Study Router recommendations."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from app.adaptive_plan_step_text import (
    BLOCK_TYPE_LABEL_RU,
    build_plan_step_reason,
    is_placeholder_plan_concept as _is_placeholder_concept,
)
from app.smart_study_recommendation import (
    SmartStudyPrimaryNav,
    SmartStudyRecommendation,
    SmartStudySecondaryAction,
    _quiz_feedback_failed,
    _ru_flashcard_due_word,
)

_STEERING_PREFS = frozenset({"review_first", "new_topic", "gentle"})


def _stable_secondaries(
    *,
    primary_nav: SmartStudyPrimaryNav,
    exclude_ids: frozenset[str] | None = None,
) -> tuple[SmartStudySecondaryAction, ...]:
    """Фиксированный порядок; всегда 2–4 пункта без скрытия tutor/quiz/flashcards/dashboard."""
    exclude_ids = exclude_ids or frozenset()
    pool: list[SmartStudySecondaryAction] = [
        SmartStudySecondaryAction("qa_sources", "Открыть быстрый ответ и список источников"),
        SmartStudySecondaryAction("tutor_simpler", "Попросить объяснить проще в чате тьютора"),
        SmartStudySecondaryAction("quiz_nav", "Открыть интерактивный quiz"),
        SmartStudySecondaryAction("progress_go", "Открыть экран прогресса обучения"),
        SmartStudySecondaryAction("fc_create", "Создать новую flashcard-карточку"),
    ]
    picked: list[SmartStudySecondaryAction] = []
    for item in pool:
        if item.action_id in exclude_ids:
            continue
        if primary_nav == "flashcards_review" and item.action_id == "fc_create":
            continue
        picked.append(item)
        if len(picked) >= 4:
            break
    while len(picked) < 2:
        filler = SmartStudySecondaryAction("topics_nav", "Открыть темы и учебный маршрут")
        if filler not in picked:
            picked.append(filler)
        else:
            break
    return tuple(picked[:4])


_SSR_ROUTE_PEDAGOGY_RETENTION_RU = (
    "Тип приоритета: долг удержания — интервальное повторение снижает забывание."
)


_SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU = (
    "Тип приоритета: восстановление слабого понятия — разберите ошибку до следующей проверки."
)


_SSR_ROUTE_PEDAGOGY_NEW_LEARNING_RU = (
    "Тип приоритета: новое обучение — перенесите быстрый ответ в освоение темы."
)


def _ssr_recommendation_for_kind(
    hint_kind: str,
    *,
    surface: Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"],
    flashcard_due_n: int,
    sm2_due_n: int,
    quiz_feedback_status: str | None,
    has_tutor_resume: bool,
    tutor_topic: str | None,
    has_last_answer_qa: bool,
    has_reading_resume: bool,
    first_weak_concept: str | None,
    plan_primary_block: dict[str, Any] | None,
    ml_audit_ru: str = "",
) -> SmartStudyRecommendation | None:
    fc = max(0, int(flashcard_due_n))
    due = max(0, int(sm2_due_n))
    topic_t = str(tutor_topic or "").strip() or None
    weak = str(first_weak_concept or "").strip() or None
    plan_block = plan_primary_block if isinstance(plan_primary_block, dict) else None
    plan_first = surface == "adaptive_plan" and plan_block is not None
    hk = str(hint_kind or "").strip()
    if hk == "cards_due":
        if fc <= 0:
            return None
        sec_ex = frozenset({"fc_create"} if surface != "flashcards_hub" else set())
        w = _ru_flashcard_due_word(fc)
        return SmartStudyRecommendation(
            hint_kind="cards_due",
            primary_label_ru="Повторить",
            why_now_ru=(
                f"Очередь интервальных повторений: к повтору {fc} {w}. Интервал уже наступил, "
                "короткая сессия удержит факты и снижает риск забывания."
            ),
            primary_nav="flashcards_review",
            secondaries=_stable_secondaries(primary_nav="flashcards_review", exclude_ids=sec_ex),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_RETENTION_RU,
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "sm2_due":
        if fc > 0 or due <= 0:
            return None
        return SmartStudyRecommendation(
            hint_kind="sm2_due",
            primary_label_ru="Повторить тему из очереди повторений",
            why_now_ru="Очередь интервальных повторений по темам уже созрела и помогает удержать материал в долгой памяти.",
            primary_nav="sm2_tutor",
            secondaries=_stable_secondaries(primary_nav="sm2_tutor"),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_RETENTION_RU,
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "quiz_failed":
        if not _quiz_feedback_failed(quiz_feedback_status):
            return None
        return SmartStudyRecommendation(
            hint_kind="quiz_failed",
            primary_label_ru="Разобрать слабое место",
            why_now_ru=(
                "Сигнал последней мини-проверки: ответ не зачтён. Можно спокойно разобрать слабое место "
                "с тьютором, чтобы не закрепить неверную модель."
            ),
            primary_nav="quiz_recovery_tutor",
            secondaries=_stable_secondaries(primary_nav="quiz_recovery_tutor"),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU,
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "adaptive_plan":
        if not (plan_first and fc == 0 and due == 0):
            return None
        bt = str(plan_block.get("type") or "").strip()
        concept_raw = str(plan_block.get("concept") or "").strip()
        step_human = BLOCK_TYPE_LABEL_RU.get(bt, bt or "шаг")
        if _is_placeholder_concept(concept_raw):
            line = step_human
        else:
            line = f"{step_human}: «{concept_raw}»"
        return SmartStudyRecommendation(
            hint_kind="adaptive_plan",
            primary_label_ru=f"Следовать шагу плана — {line}",
            why_now_ru=build_plan_step_reason(plan_block),
            primary_nav="plan_block_tutor",
            secondaries=_stable_secondaries(primary_nav="plan_block_tutor"),
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "tutor_resume":
        if not (has_tutor_resume and topic_t):
            return None
        return SmartStudyRecommendation(
            hint_kind="tutor_resume",
            primary_label_ru=f"Продолжить чат по теме «{topic_t}»",
            why_now_ru="Контекст диалога уже сохранён: можно продолжить разбор там, где остановились.",
            primary_nav="tutor_resume",
            secondaries=_stable_secondaries(primary_nav="tutor_resume"),
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "answer_ready":
        if not has_last_answer_qa:
            return None
        return SmartStudyRecommendation(
            hint_kind="answer_ready",
            primary_label_ru="Учить тему",
            why_now_ru=(
                "Локально уже есть быстрый ответ по базе. Можно перенести материал в учёбу темы в чате "
                "или проверьте понимание коротким квизом."
            ),
            primary_nav="qa_continue",
            secondaries=_stable_secondaries(primary_nav="qa_continue"),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_NEW_LEARNING_RU,
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "mastery_stale":
        if not (weak or has_reading_resume):
            return None
        focus = weak or "сохранённой теме"
        return SmartStudyRecommendation(
            hint_kind="mastery_stale",
            primary_label_ru="Проверить запоминание и освежить тему",
            why_now_ru=(
                f"Можно вернуться к «{focus}»: короткое закрепление снижает провалы в квизах и повторениях."
            ),
            primary_nav="tutor_weak_gap",
            secondaries=_stable_secondaries(primary_nav="tutor_weak_gap"),
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    if hk == "safe_default":
        return SmartStudyRecommendation(
            hint_kind="safe_default",
            primary_label_ru="Короткая учебная сессия с тьютором",
            why_now_ru="Нет сильных сигналов очередей. Короткий диалог задаст тему без перегруза.",
            primary_nav="safe_tutor_5min",
            secondaries=_stable_secondaries(primary_nav="safe_tutor_5min"),
            ml_audit_ru=ml_audit_ru,
            flashcard_due_n=fc,
            sm2_due_n=due,
        )
    return None



def apply_smart_study_steering_preference(
    rec: SmartStudyRecommendation,
    *,
    steering: str | None,
    has_last_answer_qa: bool = False,
    defer_was_applied: bool = False,
) -> tuple[SmartStudyRecommendation, bool]:
    """US-20.10: локальные предпочтения с явными компромиссами (сильные сигналы не скрываются)."""

    s = (steering or "").strip().lower()
    if s not in _STEERING_PREFS:
        return rec, False

    changed = False
    out = rec
    hk = rec.hint_kind

    if s == "gentle" and not defer_was_applied:
        if hk == "quiz_failed":
            extra = (
                " Мягкий режим не отменяет разбор провала мини-проверки — иначе выше риск закрепить ошибочную модель."
            )
            if extra not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + extra)
                changed = True
        elif hk == "adaptive_plan":
            extra = (
                " Мягкий режим не отменяет шаг адаптивного плана; при необходимости сначала сверьтесь с источниками."
            )
            if extra not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + extra)
                changed = True
        elif hk == "cards_due":
            out = replace(
                out,
                primary_nav="safe_tutor_5min",
                primary_label_ru="Короткий чат (мягкий режим)",
                why_now_ru=(
                    rec.why_now_ru
                    + " Вы выбрали мягкий вход: первичный шаг — короткий тьютор, "
                    "но очередь карточек к повтору сохраняется — вернитесь к ней, когда будет комфортнее."
                ),
                secondaries=_stable_secondaries(primary_nav="safe_tutor_5min"),
            )
            changed = True
        elif hk == "sm2_due":
            if has_last_answer_qa:
                out = replace(
                    out,
                    primary_nav="qa_continue",
                    primary_label_ru="Свериться с базой (мягкий вход)",
                    why_now_ru=(
                        rec.why_now_ru
                        + " Мягкий режим: вместо немедленного повторения — короткая сверка с быстрым ответом; очередь тем сохраняется."
                    ),
                    secondaries=_stable_secondaries(primary_nav="qa_continue"),
                )
            else:
                out = replace(
                    out,
                    primary_nav="safe_tutor_5min",
                    primary_label_ru="Короткий чат (мягкий режим)",
                    why_now_ru=(
                        rec.why_now_ru
                        + " Мягкий режим: без готового Q&A — короткий тьютор; очередь повторений сохраняется."
                    ),
                    secondaries=_stable_secondaries(primary_nav="safe_tutor_5min"),
                )
            changed = True
        elif rec.primary_nav == "tutor_weak_gap":
            out = replace(
                out,
                primary_nav="qa_continue",
                primary_label_ru="Сначала свериться с источниками (мягче)",
                why_now_ru=(
                    rec.why_now_ru
                    + " Мягкий режим: сначала опора на выдержки из базы, затем возврат к пробелу понимания."
                ),
                secondaries=_stable_secondaries(primary_nav="qa_continue"),
            )
            changed = True
        elif rec.primary_nav == "tutor_resume":
            out = replace(
                out,
                primary_nav="safe_tutor_5min",
                primary_label_ru="Короткий чат без давления",
                why_now_ru=(
                    rec.why_now_ru
                    + " Мягкий режим: не форсируем длинное продолжение прошлой сессии — короткий шаг в тьюторе."
                ),
                secondaries=_stable_secondaries(primary_nav="safe_tutor_5min"),
            )
            changed = True
        elif rec.primary_nav == "plan_block_tutor":
            out = replace(
                out,
                primary_nav="qa_continue",
                primary_label_ru="Сверить материал перед шагом плана",
                why_now_ru=(
                    rec.why_now_ru
                    + " Мягкий режим: сначала кратко откройте выдержки, затем вернитесь к шагу плана."
                ),
                secondaries=_stable_secondaries(primary_nav="qa_continue"),
            )
            changed = True
        elif rec.primary_nav == "qa_continue" and hk == "answer_ready":
            out = replace(
                out,
                primary_nav="safe_tutor_5min",
                primary_label_ru="Короткая сессия с тьютором",
                why_now_ru=(
                    rec.why_now_ru
                    + " Мягкий режим: вместо немедленного переноса в drill — спокойный пятиминутный вход в чат."
                ),
                secondaries=_stable_secondaries(primary_nav="safe_tutor_5min"),
            )
            changed = True

    trade_retention = (
        " Ваш выбор «сначала новое» уступает сейчас долгу удержания или разбору проверки — первичный шаг остаётся про закрепление."
    )
    trade_weak = (
        " Ваш акцент на новую тему ждёт: сейчас приоритетнее закрыть пробел по освоению, чтобы не наращивать ошибку."
    )

    if s == "new_topic":
        if hk in ("cards_due", "sm2_due", "quiz_failed"):
            if trade_retention.strip() not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + trade_retention)
                changed = True
        elif hk == "mastery_stale":
            if trade_weak.strip() not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + trade_weak)
                changed = True
        elif hk == "answer_ready":
            ack = " Совпадает с вашим акцентом на новое обучение."
            if ack.strip() not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + ack)
                changed = True

    if s == "review_first":
        if hk in ("cards_due", "sm2_due"):
            ack = " Это согласуется с вашим выбором «сначала повтор»."
            if ack not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + ack)
                changed = True
        elif hk == "answer_ready":
            expl = (
                " Вы просили «сначала повтор»; срочной очереди повторений и карточек сейчас нет — шаг опирается на готовый быстрый ответ."
            )
            if expl not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + expl)
                changed = True
        elif hk == "safe_default":
            expl = (
                " Вы просили «сначала повтор»; срочной очереди повторений и карточек сейчас нет — безопасный вход в чат остаётся уместным."
            )
            if expl not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + expl)
                changed = True
        elif hk == "mastery_stale":
            ack = " Согласуется с акцентом на повторение и закрепление материала."
            if ack not in out.why_now_ru:
                out = replace(out, why_now_ru=out.why_now_ru + ack)
                changed = True


    return out, changed
