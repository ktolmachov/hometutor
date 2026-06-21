"""E9.7: чистые строки для continuity / learn bridge (pytest без Streamlit)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, MutableMapping

# E11 / US-14.1: единственный primary CTA на главной (детерминированный набор подписей).
GUIDED_PRIMARY_HOME_CTA_LABELS = frozenset(
    {
        "Продолжить",
        "Повторить",
        "Учить эту тему 5 минут",
        "Освоить следующий концепт",
    }
)

GuidedPrimaryHomeCtaKind = Literal[
    "flashcard_due", "resume", "due_review", "mastery_gap", "safe_starter"
]


def guided_primary_home_cta_ru(
    *,
    flashcard_due_n: int = 0,
    has_tutor_resume: bool,
    due_n: int,
    has_mastery_gap: bool,
) -> tuple[str, GuidedPrimaryHomeCtaKind]:
    """
    Один главный CTA для home/progress entry (CJM: First Answer / Resume / Progress).

    Приоритет: flashcard due > концепты SM-2 (due) > resume тьютора > mastery gap > safe starter.
    Разрежённое состояние (нет сигналов) → «Учить эту тему 5 минут».
    """
    if flashcard_due_n > 0:
        return ("Повторить", "flashcard_due")
    if due_n > 0:
        return ("Повторить", "due_review")
    if has_tutor_resume:
        return ("Продолжить", "resume")
    if has_mastery_gap:
        return ("Освоить следующий концепт", "mastery_gap")
    return ("Учить эту тему 5 минут", "safe_starter")


def guided_primary_reason_line_ru(kind: GuidedPrimaryHomeCtaKind) -> str:
    if kind in {"flashcard_due", "due_review"}:
        return "Почему сейчас: Сейчас повторение, потому что тему важно удержать в памяти."
    if kind == "mastery_gap":
        return "Почему сейчас: Сейчас объяснение, чтобы выстроить ясную основу по теме."
    if kind == "resume":
        return "Почему сейчас: Сейчас продолжаем начатый разбор без потери контекста."
    return "Почему сейчас: Сейчас короткий старт, чтобы быстро войти в тему."


def home_continue_priority_lines_ru(
    *,
    due_n: int,
    tutor_topic: str | None,
    has_last_qa: bool,
    has_reading: bool,
) -> tuple[str, str | None]:
    """
    Одна главная строка «что важнее сейчас» + опциональная вторая без дублирения фактов.
    При активном тьюторе — сначала resume; иначе очередь повторений → Q&A → reading → cold start.
    """
    sec_bits: list[str] = []
    if tutor_topic and due_n > 0:
        sec_bits.append(f"в очереди ещё **{due_n}** тем по расписанию")
    if has_last_qa and (due_n > 0 or tutor_topic):
        sec_bits.append("есть последний ответ в «Быстром ответе»")
    if has_reading and not tutor_topic:
        sec_bits.append("есть сохранённый прогресс по теме/плану")

    if tutor_topic:
        main = f"Продолжите диалог тьютора: **{tutor_topic}**."
    elif due_n >= 3:
        main = f"Сначала очередь повторений: **{due_n}** тем по расписанию."
    elif due_n > 0:
        main = f"В очереди на повторение: **{due_n}** тем."
    elif has_last_qa:
        main = "Есть свежий **ответ по базе** — откройте «Быстрый ответ» или перенесите тему в чат тьютора."
    elif has_reading:
        main = "Есть сохранённый **прогресс по теме или плану** — продолжите во вкладке «Темы»."
    else:
        main = (
            "Начните с примера вопроса выше, **Быстрого ответа** или **чата с тьютором** — "
            "так быстрее появится ясность по теме."
        )

    secondary = " · ".join(sec_bits) if sec_bits else None
    return main, secondary


def due_reviews_home_teaser_ru(due_n: int) -> str | None:
    if due_n <= 0:
        return None
    return f"🔥 **{due_n}** тем на повторение — список удобнее смотреть **справа**."


def qa_fast_answer_top_caption_ru() -> str:
    """E11-B: первая строка вкладки — что сделать и зачем (без технических терминов)."""
    return (
        "**Спросите по базе** — короткий ответ с опорой на ваши материалы. "
        "Так можно быстро проверить формулировку и перейти к разбору в чате тьютора."
    )


def qa_fast_answer_panel_subtitle_ru() -> str:
    return "Вопрос → ответ → источники в ваших файлах"


def qa_fast_answer_question_placeholder_ru() -> str:
    return "Например: в чём суть темы по вашим конспектам?"


def qa_tab_after_answer_debug_intro_caption_ru() -> str:
    """Подпись над сводкой обработки запроса (рядом с техническими деталями ниже)."""
    return "Кратко: как вопрос сопоставлен с материалами и какие фрагменты пошли в ответ."


def qa_tab_focus_view_caption_ru() -> str:
    return (
        "Режим чтения: боковая панель со списком источников скрыта — проще сосредоточиться на тексте."
    )


def qa_tab_sources_column_intro_caption_ru() -> str:
    return (
        "Фрагменты подобраны по смыслу к вопросу; подробности подбора, оценок и времени — в блоке ниже."
    )


def qa_tab_empty_state_callout_html_ru() -> str:
    """Правая колонка без последнего ответа: один акцент и короткая польза."""
    return """
                <div class="callout">
                    <div class="panel-title">С чего начать</div>
                    <div class="panel-subtitle">Задайте вопрос слева или откройте чат тьютора — так быстрее разберёте тему и закрепите материал.</div>
                </div>
                """


def sidebar_fast_filters_caption_ru() -> str:
    return "Быстрые фильтры задают тему и папку для следующего вопроса."


def sidebar_focus_view_help_ru() -> str:
    return (
        "Скрывает соседние панели со списком источников и служебными подробностями там, "
        "где вы читаете длинный ответ, конспект или план."
    )


def expert_controls_expander_label_ru() -> str:
    """E11-C / US-14.3: один заголовок advanced-слоя в сайдбаре и на вкладке Q&A."""
    return "Расширенное управление (эксперт)"


def expert_controls_sidebar_blurb_ru() -> str:
    return (
        "Фильтры области вопроса и голос — без изменения основного сценария «вопрос → ответ». "
        "Резервное копирование и восстановление — в отдельном блоке **Перенос прогресса** в сайдбаре выше."
    )


def tutor_expert_controls_intro_ru() -> str:
    return (
        "Прозрачность сессии тьютора: что уже известно о маршруте, откуда пришёл контекст "
        "и какие действия безопасно сделать без ручной настройки policy."
    )


def flashcards_expert_controls_intro_ru() -> str:
    return (
        "Прозрачность очереди повторения: текущий scope, прогресс сессии и сигналы SM-2 "
        "без ручной перенастройки алгоритма."
    )


def quiz_expert_controls_intro_ru() -> str:
    return (
        "Прозрачность генерации quiz: источник контекста, состав вопросов и текущий результат "
        "без ручной настройки промпта."
    )


def adaptive_plan_expert_controls_intro_ru() -> str:
    return (
        "Просмотр баланса review/gap/new, входного состояния маршрута, компактного снимка профиля "
        "и истории версий плана (KV) без ручного редактирования весов."
    )


def sync_transfer_sidebar_expander_label_ru() -> str:
    """E27-A / US-10.2: видимая точка входа без вложенности «эксперт → голос»."""
    return "Перенос прогресса (backup / восстановление)"


def sync_transfer_sidebar_intro_caption_ru() -> str:
    return (
        "Скачайте JSON backup или восстановите прогресс с другого устройства: сначала предпросмотр, затем подтверждение импорта."
    )


def home_sync_transfer_hint_ru() -> str:
    """Один указатель с главного экрана без второго мастера восстановления."""
    return (
        "**Перенос с другого ПК:** левый сайдбар → раздел «Перенос прогресса (backup / восстановление)»."
    )


def qa_tab_expert_pointer_caption_ru() -> str:
    """Короткая подсказка без технических терминов; детали — только внутри расширенного блока ниже."""
    return (
        "Тип вопроса, режим подбора фрагментов и подробный журнал — в блоке «Расширенное управление (эксперт)» ниже."
    )


def qa_to_tutor_bridge_caption_ru() -> str:
    return (
        "В чате тьютора откроется **тот же черновик**: ваш вопрос и тема; "
        "тьютор начнёт с объяснения и уточнений по этой теме (без нового поиска по базе)."
    )


def qa_five_min_tutor_bridge_caption_ru() -> str:
    """E11-D / US-14.4: что произойдёт после «Учить эту тему 5 минут» из Q&A."""
    return (
        "Короткий цикл: **ответ тьютора** → **мини-проверка** → разбор → сигнал прогресса и следующий шаг "
        "(или «готово на сегодня»)."
    )


def last_assistant_message_index(msgs: list[Any]) -> int:
    """Индекс последнего сообщения с ролью assistant (для привязки micro-quiz к ответу)."""
    for i in range(len(msgs) - 1, -1, -1):
        if getattr(msgs[i], "role", None) == "assistant":
            return i
    return max(0, len(msgs) - 1)


def e24_goal_closure_goal_phrase_ru(
    *,
    desired_outcome: str | None,
    topic: str | None,
) -> str | None:
    """Короткая привязка к активной цели (E24-A). ``None``, если нечего показать."""
    t = (desired_outcome or "").strip()
    if t:
        if len(t) > 120:
            t = t[:117] + "…"
        return f"Связь с целью: **{t}**."
    ctop = (topic or "").strip()
    if ctop:
        if len(ctop) > 80:
            ctop = ctop[:77] + "…"
        return f"Тема сессии: **{ctop}**."
    return None


def e24_five_min_closure_combined_ru(
    weekly_goals_snapshot: dict[str, Any] | None,
    *,
    tutor_goal_desired_outcome: str | None = None,
    current_topic: str | None = None,
) -> str:
    """E11 closure + опциональная строка про цель (E24-A)."""
    base = e11_five_min_closure_hint_ru(weekly_goals_snapshot)
    suf = e24_goal_closure_goal_phrase_ru(
        desired_outcome=tutor_goal_desired_outcome,
        topic=current_topic,
    )
    if not suf:
        return base
    return f"{base}\n\n{suf}"


def e24_active_goal_line_ru(
    *,
    current_topic: str | None,
    tutor_goal_desired_outcome: str | None,
    tutor_goal_subtopic: str | None,
    tutor_goal_target_level: str | None,
    tutor_goal_time_budget_min: int | None,
) -> str | None:
    """Одна компактная строка «Сейчас: …» для заголовка чата тьютора (E24-A)."""
    bits: list[str] = []
    outcome = (tutor_goal_desired_outcome or "").strip()
    sub = (tutor_goal_subtopic or "").strip()
    focus = sub or (current_topic or "").strip()
    if outcome:
        oc = outcome[:120] + ("…" if len(outcome) > 120 else "")
        bits.append(f"цель: {oc}")
    elif focus:
        fb = focus[:80] + ("…" if len(focus) > 80 else "")
        bits.append(f"тема: {fb}")
    if tutor_goal_time_budget_min is not None:
        try:
            tb = int(tutor_goal_time_budget_min)
            if 1 <= tb <= 240:
                bits.append(f"~{tb} мин")
        except (TypeError, ValueError):
            pass
    tl = (tutor_goal_target_level or "").strip()
    if tl:
        bits.append(f"уровень: {tl[:32]}")
    if not bits:
        return None
    return "Сейчас: " + "; ".join(bits) + "."


def e11_five_min_closure_hint_ru(weekly_goals_snapshot: dict[str, Any] | None) -> str:
    """
    Текст после завершения мини-проверки в 5-минутном цикле: «готово на сегодня» или мягкая пауза.
    ``weekly_goals_snapshot`` — как из ``get_weekly_goals_state()`` (targets + done).
    """
    wg = weekly_goals_snapshot or {}
    done = wg.get("done") if isinstance(wg.get("done"), dict) else {}
    tgt = wg.get("targets") if isinstance(wg.get("targets"), dict) else {}
    try:
        dq = int(done.get("quizzes") or 0)
        tq = max(1, int(tgt.get("quizzes") or 1))
    except (TypeError, ValueError):
        dq, tq = 0, 1
    if dq >= tq:
        return (
            "**Готово на сегодня** — недельная цель по мини-проверкам выполнена. "
            "Загляните в «Мой прогресс», когда будет удобно."
        )
    return (
        "Если на сегодня достаточно — сделайте паузу; иначе используйте **следующий шаг** выше "
        "или откройте «Мой прогресс»."
    )


def ask_failure_recovery_hint_ru(error_text: str) -> str:
    """Одна строка после сбоя /ask (локальная эвристика по тексту ошибки)."""
    t = (error_text or "").lower()
    if "401" in t or "403" in t or "unauthorized" in t or "api key" in t or "ключ" in t:
        return "Проверьте **OPENAI_API_KEY** в `.env` и перезапустите приложение."
    if "timeout" in t or "timed out" in t or "таймаут" in t:
        return "Похоже на **таймаут** — сузьте область (папка/файл/тема) и **повторите** запрос."
    if "connection" in t or "connect" in t or "refused" in t or "econn" in t:
        return "Нет связи с API — проверьте сеть и что backend запущен; затем **повторите**."
    if "rate" in t and "limit" in t:
        return "Сработал **лимит запросов** — подождите минуту и **повторите**."
    return "Сузьте область поиска, проверьте ключ API и **повторите** запрос."


QA_TUTOR_HANDOFF_KEY = "qa_tutor_handoff_context"


def _compact_text(text: str | None, *, limit: int) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def build_qa_tutor_handoff_context(
    *,
    topic: str | None,
    last_question: str | None,
    answer_summary: str | None = None,
    source: str = "quick_answer",
    created_at: str | None = None,
) -> dict[str, str] | None:
    """
    Нормализует payload handoff из Quick Answer в Tutor.
    Возвращает ``None`` для невалидного контракта (например, пустой вопрос).
    """
    question_norm = _compact_text(last_question, limit=600)
    if not question_norm:
        return None
    topic_norm = _compact_text(topic, limit=120) or _compact_text(question_norm, limit=80)
    if not topic_norm:
        return None
    summary_norm = _compact_text(answer_summary, limit=500)
    source_norm = _compact_text(source, limit=40) or "quick_answer"
    stamp = (created_at or "").strip() or datetime.now(timezone.utc).isoformat()
    return {
        "topic": topic_norm,
        "last_question": question_norm,
        "answer_summary": summary_norm,
        "source": source_norm,
        "created_at": stamp,
    }


def store_qa_tutor_handoff_context(
    state: MutableMapping[str, Any],
    *,
    topic: str | None,
    last_question: str | None,
    answer_summary: str | None = None,
    source: str = "quick_answer",
    created_at: str | None = None,
) -> bool:
    payload = build_qa_tutor_handoff_context(
        topic=topic,
        last_question=last_question,
        answer_summary=answer_summary,
        source=source,
        created_at=created_at,
    )
    if not payload:
        return False
    state[QA_TUTOR_HANDOFF_KEY] = payload
    return True


def load_qa_tutor_handoff_context(state: MutableMapping[str, Any]) -> dict[str, str] | None:
    raw = state.get(QA_TUTOR_HANDOFF_KEY)
    if not isinstance(raw, dict):
        return None
    return build_qa_tutor_handoff_context(
        topic=raw.get("topic"),
        last_question=raw.get("last_question"),
        answer_summary=raw.get("answer_summary"),
        source=raw.get("source") or "quick_answer",
        created_at=raw.get("created_at"),
    )


def clear_qa_tutor_handoff_context(state: MutableMapping[str, Any]) -> None:
    state.pop(QA_TUTOR_HANDOFF_KEY, None)


# ---------------------------------------------------------------------------
# Course Workspace copy strings (Package AB / US-16.x)
# ---------------------------------------------------------------------------

def course_scope_chip_ru(course_title: str) -> str:
    return f"🎯 Поиск только в: «{course_title}»"


def course_scope_tutor_context_line_ru(course_title: str) -> str:
    return f"Учебный контекст: {course_title}"


def flashcard_gap_to_tutor_cta_ru() -> str:
    return "Не знаю — объясни"


def tutor_back_to_flashcards_ru() -> str:
    return "← Вернуться к карточкам"


def tutor_reason_line_ru(
    *,
    policy_clamp_reasons: list[str] | None = None,
    tutor_decision: dict[str, Any] | None = None,
) -> str:
    """
    Короткая user-facing причина шага тьютора без техтерминов.
    Приоритет: policy reasons -> tutor decision action -> нейтральный fallback.
    """
    reasons = [str(x).strip().lower() for x in (policy_clamp_reasons or []) if str(x).strip()]
    if any("review" in r or "due" in r for r in reasons):
        return "Сейчас повторение, потому что тему важно удержать в памяти."
    if any("quiz" in r for r in reasons):
        return "Сейчас мини-проверка, чтобы закрепить понимание."
    if any("mastery" in r or "gap" in r for r in reasons):
        return "Сейчас объяснение, потому что сначала нужна базовая опора по теме."
    action = ""
    if isinstance(tutor_decision, dict):
        action = str((tutor_decision.get("action") or {}).get("next_action") or "").strip().lower()
    if action in {"quiz", "micro_quiz"}:
        return "Сейчас мини-проверка, чтобы закрепить понимание."
    if action in {"review", "due_review"}:
        return "Сейчас повторение, потому что тему важно удержать в памяти."
    return "Сейчас объяснение, чтобы выстроить ясную основу по теме."


def continuity_next_step_line_ru(
    *,
    topic: str | None,
    tutor_decision: dict[str, Any] | None = None,
    policy_clamp_reasons: list[str] | None = None,
) -> str:
    """Один согласованный next-step текст для compact context block."""
    t = _compact_text(topic, limit=80)
    reason = tutor_reason_line_ru(
        policy_clamp_reasons=policy_clamp_reasons,
        tutor_decision=tutor_decision,
    ).lower()
    if "проверка" in reason:
        return f"Следующий шаг: короткая проверка по теме «{t}»." if t else "Следующий шаг: короткая проверка по теме."
    if "повторение" in reason:
        return f"Следующий шаг: повторение по теме «{t}»." if t else "Следующий шаг: повторение по теме."
    return f"Следующий шаг: продолжить разбор темы «{t}» в чате тьютора." if t else "Следующий шаг: продолжить разбор в чате тьютора."
