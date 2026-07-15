"""Home-page hub: onboarding, entry navigation, quiz hero card, helpers."""

import uuid
from typing import Any

import streamlit as st

from app.flashcard_service import flashcard_home_effort_hint_lines
from app.ui.continuity_bridge import (
    continuity_next_step_line_ru,
    course_scope_chip_ru,
    guided_primary_home_cta_ru,
    guided_primary_reason_line_ru,
    home_sync_transfer_hint_ru,
    load_qa_tutor_handoff_context,
    restore_course_cta_ru,
    tutor_reason_line_ru,
)
from app.ui.study_scope import (
    deactivate_scope,
    get_active_scope,
    get_last_deactivated_scope,
    restore_scope,
)
from app.ui.answer_helpers import source_paths_from_answer as _source_paths_from_answer
from app.ui.adaptive_plan_card import render_adaptive_plan_hub
from app.ui.helpers import (
    esc_html as _esc_html,
    format_request_error as _format_request_error,
    home_mode_best_for_line,
    home_mode_intent_row_orders,
    home_mode_preview_lines,
)
from app.ui.tutorial_guide import (
    render_tutorial_entry as _render_tutorial_entry,
    start_tutorial as _start_tutorial,
    tutorial_progress_payload as _tutorial_progress_payload,
)
from app.ui.session_state import (
    clear_tutor_goal_and_snapshot as _clear_tutor_goal_and_snapshot,
    persist_tutor_goal_snapshot_from_session as _persist_tutor_goal_snapshot_from_session,
)
from app.ui.topics_catalog import load_topics_catalog as _load_topics_catalog
from app.ui_client import fetch_json as _fetch_json


# ---------------------------------------------------------------------------
# Mastery dashboard cache (prevents 30+ calls per session)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=30)
def _fetch_mastery_dashboard(_singleton: str = "v1") -> dict[str, Any]:
    """Cached mastery dashboard call with 30s TTL to debounce excessive polling."""
    _ = _singleton
    try:
        return _fetch_json("GET", "/dashboard/mastery", timeout=10)
    except Exception:  # noqa: BLE001
        return {"due_count": 0, "next_recommendation": {}}


# ---------------------------------------------------------------------------
# Home-page functions
# ---------------------------------------------------------------------------


def _render_onboarding() -> None:
    """Первый запуск: короткий выбор уровня интерфейса; ценность сначала."""
    from app.ui_events import track_event
    from app.ui.breadcrumb import HOME_VIEW
    from app.ui_preferences import LEVEL_DIAGNOSTIC, LEVEL_FULL, LEVEL_STUDY, set_ui_level
    from app.user_state import set_kv

    st.markdown(
        "<h1 style='text-align:center;background:linear-gradient(90deg,#667eea,#764ba2);"
        "-webkit-background-clip:text;background-clip:text;color:transparent;'>"
        "🎓 Hometutor</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "Локальный ИИ-тьютор над вашими файлами. "
        "Загрузите конспекты, лекции или учебники — "
        "и получайте ответы с источниками, объяснения, тесты "
        "и персональный план повторения."
    )
    st.markdown("### Добро пожаловать! Сначала дадим первый ответ")
    st.caption("Цель обучения можно будет настроить после первого ответа, когда уже будет понятно, что подстраивать.")
    ui_mode_label = st.radio(
        "Какой интерфейс показать?",
        ["Учёба", "Полный (курсы и план)", "Диагностика (метрики и trace)"],
        index=0,
    )
    launch_tour = st.checkbox("Запустить интерактивный тур", value=True)
    st.caption(
        "Маршрут по умолчанию: объяснение → две мини-проверки → повторение (ориентир 15–30 мин). "
        "Активация курса сама открывает режим «Полный», если сейчас выбрана «Учёба»."
    )
    if st.button("Начать", type="primary", width='stretch', key="onboarding_start"):
        ui_level_map = {
            "Учёба": LEVEL_STUDY,
            "Полный (курсы и план)": LEVEL_FULL,
            "Диагностика (метрики и trace)": LEVEL_DIAGNOSTIC,
        }
        set_ui_level(ui_level_map[ui_mode_label])
        set_kv("onboarding_v1_done", "1")
        st.session_state["current_view"] = HOME_VIEW
        if launch_tour:
            _start_tutorial(0)
        try:
            track_event("onboarding_completed", {"goal": None, "ui_level": ui_level_map[ui_mode_label]})
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            pass
        st.rerun()


def render_post_first_answer_goal_prompt() -> None:
    """One-shot goal prompt after the first successful Q&A answer."""
    from app.user_state import get_kv, set_kv, set_preferred_style

    if not st.session_state.get("last_answer"):
        return
    try:
        if get_kv("goal_prompt_done") == "1":
            return
    except Exception:  # noqa: BLE001
        return

    with st.expander("🎯 Подстроить объяснения под вас? (30 секунд)", expanded=False):
        goal_label = st.selectbox(
            "Какая у вас цель сейчас?",
            [
                "Понять новую тему",
                "Подготовиться к экзамену",
                "Разобрать домашнее задание",
                "Быстро повторить слабые места",
            ],
            key="post_first_answer_goal_label",
        )
        duration = st.slider("Сколько времени готовы потратить (минут)?", 15, 60, 25, step=5, key="post_first_answer_duration")
        actions = st.columns([1, 1, 2])
        with actions[0]:
            if st.button("Сохранить", key="post_first_answer_goal_save", type="primary"):
                goal_map = {
                    "Понять новую тему": ("understand_topic", "examples"),
                    "Подготовиться к экзамену": ("exam_prep", "deep"),
                    "Разобрать домашнее задание": ("solve_homework", "examples"),
                    "Быстро повторить слабые места": ("understand_topic", "short"),
                }
                learning_goal, depth = goal_map[goal_label]
                st.session_state["learning_goal"] = learning_goal
                st.session_state["tutor_answer_depth"] = depth
                st.session_state["estimated_minutes"] = int(duration)
                st.session_state["onboarding_goal_label"] = goal_label
                set_preferred_style("balanced")
                _persist_tutor_goal_snapshot_from_session()
                set_kv("goal_prompt_done", "1")
                st.rerun()
        with actions[1]:
            if st.button("Не сейчас", key="post_first_answer_goal_skip"):
                set_kv("goal_prompt_done", "1")
                st.rerun()


def _render_entry_navigation() -> None:
    """Три сценария входа (Phase 4) + прогресс; цель и глубина уходят в QueryOptions → промпт."""
    st.divider()
    lg = st.session_state.get("learning_goal")
    if lg:
        lg_labels = {
            "understand_topic": "Понять тему",
            "exam_prep": "Подготовка к экзамену",
            "solve_homework": "Разобрать задание",
        }
        ad = st.session_state.get("tutor_answer_depth", "examples")
        ad_labels = {"short": "Коротко", "examples": "С примерами", "deep": "Глубоко"}
        ogl = st.session_state.get("onboarding_goal_label")
        est = st.session_state.get("estimated_minutes")
        goal_line = (
            f"**{ogl}**"
            if ogl
            else f"**{lg_labels.get(lg, lg)}**"
        )
        depth_line = f"глубина ответа: **{ad_labels.get(ad, ad)}**"
        if est is not None:
            st.success(f"🎯 Цель: {goal_line} · {depth_line} · ~**{est}** мин")
        else:
            st.success(f"Цель: {goal_line} · {depth_line}")
    st.subheader("Какой у тебя сегодня запрос?")
    st.caption(
        "Для обучения лучше начинать с одного из сценариев ниже: они сразу откроют чат с тьютором "
        "с подходящей целью и глубиной ответа."
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("📚 Понять тему", key="home_entry_understand", width='stretch', type="primary"):
            if "tutor_session_id" not in st.session_state:
                st.session_state["tutor_session_id"] = str(uuid.uuid4())
            st.session_state["learning_goal"] = "understand_topic"
            st.session_state["tutor_answer_depth"] = "examples"
            st.session_state["current_view"] = "Чат с тьютором"
            _persist_tutor_goal_snapshot_from_session()
            st.rerun()
    with c2:
        if st.button("📝 Подготовиться к экзамену", key="home_entry_exam", width='stretch'):
            if "tutor_session_id" not in st.session_state:
                st.session_state["tutor_session_id"] = str(uuid.uuid4())
            st.session_state["learning_goal"] = "exam_prep"
            st.session_state["tutor_answer_depth"] = "deep"
            st.session_state["current_view"] = "Чат с тьютором"
            _persist_tutor_goal_snapshot_from_session()
            st.rerun()
    with c3:
        if st.button("🔧 Разобрать задание", key="home_entry_hw", width='stretch'):
            if "tutor_session_id" not in st.session_state:
                st.session_state["tutor_session_id"] = str(uuid.uuid4())
            st.session_state["learning_goal"] = "solve_homework"
            st.session_state["tutor_answer_depth"] = "examples"
            st.session_state["current_view"] = "Чат с тьютором"
            _persist_tutor_goal_snapshot_from_session()
            st.rerun()
    with c4:
        if st.button("📊 Мой прогресс", key="home_nav_progress", width='stretch'):
            st.session_state["current_view"] = "Прогресс обучения"
            st.rerun()
    if st.button("Сбросить цель сессии", key="home_entry_clear_goal"):
        _clear_tutor_goal_and_snapshot()
        st.rerun()


def _render_quiz_hero_card() -> None:
    last_doc = str(st.session_state.get("last_studied_document") or "").strip()
    if not last_doc:
        last_answer = st.session_state.get("last_answer") if isinstance(st.session_state.get("last_answer"), dict) else {}
        source_paths = _source_paths_from_answer(last_answer)
        last_doc = source_paths[0] if source_paths else ""
    active_topic_id = str(st.session_state.get("active_topic_id") or "").strip()
    topic_label = active_topic_id
    if active_topic_id:
        topics_catalog = _load_topics_catalog(force=False)
        for topic in (topics_catalog or {}).get("topics", []):
            if topic.get("topic_id") == active_topic_id:
                topic_label = str(topic.get("topic_name") or active_topic_id)
                break
    try:
        from app.gamification_service import get_snapshot

        gam = get_snapshot()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        gam = {}

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-continue"><h3>🧠 Готовы проверить знания?</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    st.markdown(
        "Быстрый вход в режим проверки: по последнему документу, по текущей теме или сразу в микро-квиз с тьютором."
    )
    if gam:
        delta = _hero_gamification_delta(gam)
        total_xp = int(gam.get("total_xp") or 0)
        level = int(gam.get("level") or 1)
        level_title = str(gam.get("level_title") or "?")
        daily_streak = int(gam.get("daily_streak") or 0)
        quiz_streak = int(gam.get("quiz_streak") or 0)
        xp_in_level = int(gam.get("xp_in_level") or 0)
        xp_span = max(1, int(gam.get("xp_for_level_span") or 100))
        xp_ratio = max(0.0, min(1.0, xp_in_level / xp_span))
        if delta:
            reward_bits: list[str] = []
            if delta.get("level"):
                reward_bits.append(f"уровень +{delta['level']}")
            if delta.get("total_xp"):
                reward_bits.append(f"XP +{delta['total_xp']}")
            if delta.get("daily_streak"):
                reward_bits.append(f"streak +{delta['daily_streak']} дн.")
            if delta.get("quiz_streak"):
                reward_bits.append(f"quiz-streak +{delta['quiz_streak']}")
            reward_line = " · ".join(reward_bits)
            st.markdown(
                f"""
                <div style="margin:0.15rem 0 0.65rem 0;padding:0.72rem 0.9rem;border-radius:14px;
                background:linear-gradient(135deg, rgba(246,173,85,0.18), rgba(72,187,120,0.16));
                border:1px solid rgba(72,187,120,0.20);font-weight:700;">
                    🎉 Прогресс обновился: {reward_line}
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown(
            f"""
            <div style="margin:0.25rem 0 0.55rem 0;padding:0.8rem 0.95rem;border-radius:14px;
            background:linear-gradient(135deg, rgba(47,133,90,0.10), rgba(43,108,176,0.12));
            border:1px solid rgba(43,108,176,0.10);">
                <div style="display:flex;justify-content:space-between;gap:0.75rem;flex-wrap:wrap;">
                    <span><strong>{level_title}</strong> · ур. {level}</span>
                    <span>XP <strong>{total_xp}</strong></span>
                    <span>streak <strong>{daily_streak}</strong> дн.</span>
                    <span>quiz-streak <strong>{quiz_streak}</strong></span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(
            xp_ratio,
            text=f"До следующего уровня: {xp_in_level}/{xp_span} XP в текущем уровне",
        )
        st.session_state["hero_prev_gamification"] = {
            "total_xp": total_xp,
            "daily_streak": daily_streak,
            "quiz_streak": quiz_streak,
            "level": level,
        }
    if last_doc:
        st.caption(f"Последний документ: **{_esc_html(last_doc)}**")
    else:
        st.caption("Последний документ ещё не определён: сначала откройте ответ с источниками или тему.")
    if active_topic_id:
        st.caption(f"Текущая тема: **{_esc_html(topic_label)}**")
    else:
        st.caption("Текущая тема не выбрана: можно начать с микро-квиза, а тему подобрать позже.")

    from app.ui.quiz_learning_mode_widgets import (
        render_scoped_quiz_learning_mode_select,
        scoped_quiz_learning_mode_value,
    )

    render_scoped_quiz_learning_mode_select(session_key="hero_scoped_quiz_learning_mode")
    _hero_lm = scoped_quiz_learning_mode_value("hero_scoped_quiz_learning_mode")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("По последнему документу", key="home_quiz_last_doc", width='stretch', type="primary"):
            if not last_doc:
                st.warning("Нет последнего документа для теста. Сначала получите ответ с источниками или откройте тему.")
            else:
                try:
                    data = _fetch_json(
                        "POST",
                        "/quiz/generate",
                        timeout=120,
                        json={
                            "scope": "document",
                            "relative_path": last_doc,
                            "num_questions": 6,
                            "difficulty": "adaptive",
                            "learning_mode": _hero_lm,
                        },
                    )
                    st.session_state["learning_progress_quiz_payload"] = data.get("quiz") or {}
                    st.session_state["current_view"] = "Прогресс обучения"
                    st.rerun()
                except Exception as e:  # noqa: BLE001 - optional request fallback renders a compact warning.
                    st.error(_format_request_error(e))
    with c2:
        if st.button("По текущей теме", key="home_quiz_current_topic", width='stretch'):
            if not active_topic_id:
                st.warning("Сейчас нет выбранной темы. Откройте вкладку «Темы» или начните с документа.")
            else:
                try:
                    data = _fetch_json(
                        "POST",
                        "/quiz/generate",
                        timeout=120,
                        json={
                            "scope": "topic",
                            "topic_id": active_topic_id,
                            "num_questions": 6,
                            "difficulty": "adaptive",
                            "learning_mode": _hero_lm,
                        },
                    )
                    st.session_state["learning_progress_quiz_payload"] = data.get("quiz") or {}
                    st.session_state["current_view"] = "Прогресс обучения"
                    st.rerun()
                except Exception as e:  # noqa: BLE001 - optional request fallback renders a compact warning.
                    st.error(_format_request_error(e))
    with c3:
        if st.button("Быстрый микро-квиз", key="home_quiz_micro", width='stretch'):
            if "tutor_session_id" not in st.session_state:
                st.session_state["tutor_session_id"] = str(uuid.uuid4())
            st.session_state["tutor_micro_quiz_start"] = {
                "sid": st.session_state["tutor_session_id"],
                "msg_idx": 0,
            }
            st.session_state["current_view"] = "Чат с тьютором"
            st.rerun()
    st.markdown("</div></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Mode selector (E13 Home Redesign)
# ---------------------------------------------------------------------------


def _mode_card(
    icon: str,
    title: str,
    desc: str,
    view: str,
    key: str,
    cta: str,
    *,
    badge: int = 0,
    mode_slot: str = "",
    effort_hints: list[str] | None = None,
    preview_lines: list[str] | None = None,
    preview_summary: str = "Что произойдёт и куда ведёт кнопка",
) -> None:
    """Рендерит одну карточку режима с badge и CTA-кнопкой."""
    badge_html = f'<div class="mode-badge">{badge}</div>' if badge > 0 else ""
    best_for = home_mode_best_for_line(mode_slot) if mode_slot else ""
    best_html = (
        f'<div class="mode-best-for">{_esc_html(best_for)}</div>' if best_for else ""
    )
    effort_html = ""
    if effort_hints:
        for line in effort_hints:
            effort_html += f'<div class="mode-effort-hint">{_esc_html(line)}</div>'
    preview_html = ""
    if preview_lines:
        inner = "".join(
            f'<p class="mode-preview-line">{_esc_html(line)}</p>' for line in preview_lines
        )
        preview_html = (
            '<details class="mode-preview-details">'
            f"<summary>{_esc_html(preview_summary)}</summary>"
            f'<div class="mode-preview-body">{inner}</div>'
            "</details>"
        )
    st.markdown(
        f'<div class="mode-card">{badge_html}'
        f'<div class="mode-icon">{icon}</div>'
        f'<div class="mode-title">{_esc_html(title)}</div>'
        f'<div class="mode-desc">{_esc_html(desc)}</div>'
        f"{best_html}"
        f"{effort_html}"
        f"{preview_html}"
        f"</div>",
        unsafe_allow_html=True,
    )
    if st.button(cta, key=key, width='stretch'):
        if mode_slot:
            st.session_state["home_last_primary_mode_slot"] = str(mode_slot).strip()
        st.session_state["current_view"] = view
        st.rerun()


def _render_primary_mode_slot(slot: str, *, fc_due: int) -> None:
    """Рендерит одну из шести основных карточек режима (порядок задаётся снаружи)."""
    if slot == "tutor":
        _mode_card(
            "\U0001f393",
            "Тьютор",
            "Объяснения, квизы и адаптивный план",
            "Чат с тьютором",
            "mode_tutor",
            "Начать диалог",
            mode_slot="tutor",
            preview_lines=home_mode_preview_lines("tutor"),
        )
    elif slot == "qa":
        _mode_card(
            "\u2753",
            "Быстрый ответ",
            "Ответ по документам с источниками",
            "Быстрый ответ",
            "mode_qa",
            "Задать вопрос",
            mode_slot="qa",
            preview_lines=home_mode_preview_lines("qa"),
        )
    elif slot == "quiz":
        _mode_card(
            "\U0001f9e0",
            "Quiz",
            "Проверка знаний по теме или документу",
            "Интерактивный Quiz",
            "mode_quiz",
            "Пройти тест",
            mode_slot="quiz",
            preview_lines=home_mode_preview_lines("quiz"),
        )
    elif slot == "flashcards":
        _mode_card(
            "\U0001f0cf",
            "Flashcards",
            "Карточки с интервальным повторением",
            "Flashcards",
            "mode_fc",
            "Повторить",
            badge=fc_due,
            mode_slot="flashcards",
            effort_hints=flashcard_home_effort_hint_lines(fc_due),
            preview_lines=home_mode_preview_lines("flashcards"),
        )
    elif slot == "topics":
        _mode_card(
            "\U0001f4da",
            "Темы",
            "Каталог тем, планы и синтез",
            "Темы",
            "mode_topics",
            "Обзор тем",
            mode_slot="topics",
            preview_lines=home_mode_preview_lines("topics"),
        )
    elif slot == "progress":
        _mode_card(
            "\U0001f4ca",
            "Прогресс",
            "Mastery, цели, streak и граф",
            "Прогресс обучения",
            "mode_progress",
            "Смотреть",
            mode_slot="progress",
            preview_lines=home_mode_preview_lines("progress"),
        )


def _render_active_course_card() -> None:
    """Show active course card or restore CTA (Package AB / US-16.1)."""
    scope = get_active_scope()
    if scope:
        title = scope.get("title") or scope.get("folder_rel") or "Курс"
        n_docs = len(scope.get("source_paths") or [])
        with st.container(border=True):
            st.caption("Активный курс")
            st.markdown(f"**{_esc_html(title)}**")
            st.caption(course_scope_chip_ru(title))
            if n_docs:
                st.caption(f"Документов в области: {n_docs}")
            st.caption(
                "Пошаговый плейбук для домашних заданий (шаги + самопроверка, без отдельной вкладки) — "
                "в **Course Cockpit**, пока курс активен."
            )
            deactivate_col, _ = st.columns([1, 2])
            with deactivate_col:
                if st.button("× Деактивировать курс", key="home_deactivate_scope", type="secondary", width="stretch"):
                    deactivate_scope()
                    st.rerun()
        return

    last_scope = get_last_deactivated_scope()
    if not last_scope:
        return
    title = last_scope.get("title") or last_scope.get("folder_rel") or "Курс"
    with st.container(border=True):
        st.caption("Недавно деактивированный курс")
        st.markdown(f"**{_esc_html(title)}**")
        st.caption("Можно вернуть прежнюю область поиска и Course Cockpit одной кнопкой.")
        if st.button(restore_course_cta_ru(title), key="home_restore_scope", type="secondary", width="stretch"):
            restore_scope()
            st.rerun()


def _render_more_tools_section() -> None:
    """Рендерит свёрнутую секцию дополнительных инструментов на главной."""
    with st.expander("Ещё инструменты", expanded=False):
        st.caption(home_sync_transfer_hint_ru())
        columns = st.columns(3, gap="medium")
        button_groups = [
            [
                ("\U0001f310 Knowledge Graph", "mode_kg", "Knowledge Graph"),
                ("\U0001f4cb История", "mode_history", "История"),
            ],
            [
                ("\U0001f50d Поиск материалов", "mode_search", "Найти материалы"),
                ("\U0001f4c8 Метрики", "mode_metrics", "Метрики"),
            ],
            [
                ("\U0001f4c4 Объяснить файл", "mode_explain", "Объяснить файл"),
                ("\U0001f5a8 Чистый вид", "mode_print", "Чистый вид"),
            ],
        ]
        for col, buttons in zip(columns, button_groups):
            with col:
                for label, key, target_view in buttons:
                    if st.button(label, key=key, width="stretch"):
                        st.session_state["current_view"] = target_view
                        st.rerun()


def render_mode_selector() -> None:
    from app.ui.mission_control import render_mission_control

    render_mission_control(st.session_state.get("_ui_index_stats_tab"))
    return

    """Сетка режимов работы — основной навигационный элемент главного экрана (E13)."""
    t_payload = _tutorial_progress_payload()
    if t_payload.get("active"):
        st.caption(
            f"Тур активен: глава {int(t_payload['chapter_index']) + 1} / {int(t_payload.get('total_chapters') or 0)} · шаг {int(t_payload['step_index']) + 1}"
        )
    _render_tutorial_entry()

    handoff = load_qa_tutor_handoff_context(st.session_state)
    handoff_topic = ""
    if isinstance(handoff, dict):
        handoff_topic = str(handoff.get("topic") or "").strip()
    if isinstance(handoff, dict):
        with st.container(border=True):
            st.caption("Текущий учебный контекст")
            if handoff_topic:
                st.markdown(f"Тема: **{_esc_html(handoff_topic)}**")
            st.caption(f"Почему это подходит: {tutor_reason_line_ru()}")
            st.caption(continuity_next_step_line_ru(topic=handoff_topic))

    fc_due = 0
    try:
        from app.ui.flashcards_read_cache import flashcards_due_count

        fc_due = int(flashcards_due_count(()))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass

    due_n = 0
    has_mastery_gap = False
    try:
        d = _fetch_mastery_dashboard()
        due_n = int(d.get("due_count") or 0)
        rec = d.get("next_recommendation") if isinstance(d.get("next_recommendation"), dict) else {}
        has_mastery_gap = bool((rec or {}).get("topic"))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass

    has_tutor_resume = bool(st.session_state.get("tutor_session_id"))
    cta_label, cta_kind = guided_primary_home_cta_ru(
        flashcard_due_n=fc_due,
        has_tutor_resume=has_tutor_resume,
        due_n=due_n,
        has_mastery_gap=has_mastery_gap,
    )
    last_raw = st.session_state.get("home_last_primary_mode_slot")
    last_primary = str(last_raw).strip() if last_raw else None

    row1_order, row2_order = home_mode_intent_row_orders(
        cta_kind=cta_kind,
        flashcard_due_n=fc_due,
        due_n=due_n,
        has_tutor_resume=has_tutor_resume,
        has_mastery_gap=has_mastery_gap,
        has_handoff_topic=bool(handoff_topic),
        last_primary_slot=last_primary,
    )
    with st.container(border=True):
        st.caption("Следующий шаг")
        st.caption(guided_primary_reason_line_ru(cta_kind))
        st.caption(continuity_next_step_line_ru(topic=handoff_topic or None))
        if st.button(cta_label, key="home_guided_primary_cta", type="primary", width='stretch'):
            target_view = "Чат с тьютором"
            if cta_kind in {"flashcard_due"}:
                target_view = "Flashcards"
            elif cta_kind == "due_review":
                target_view = "Прогресс обучения"
            elif cta_kind == "mastery_gap":
                target_view = "Темы"
            st.session_state["current_view"] = target_view
            st.rerun()

    _render_active_course_card()
    render_adaptive_plan_hub(key_prefix="home_adp")

    st.markdown(
        '<div class="mode-section-label">Изучать</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3, gap="medium")
    for col, slot in zip((c1, c2, c3), row1_order, strict=True):
        with col:
            _render_primary_mode_slot(slot, fc_due=fc_due)

    st.markdown(
        '<div class="mode-section-label">Тренировать и расти</div>',
        unsafe_allow_html=True,
    )
    c4, c5, c6 = st.columns(3, gap="medium")
    for col, slot in zip((c4, c5, c6), row2_order, strict=True):
        with col:
            _render_primary_mode_slot(slot, fc_due=fc_due)

    _render_more_tools_section()

def _hero_gamification_delta(current: dict[str, Any]) -> dict[str, int]:
    prev = st.session_state.get("hero_prev_gamification")
    if not isinstance(prev, dict):
        return {}
    keys = ("total_xp", "daily_streak", "quiz_streak", "level")
    out: dict[str, int] = {}
    for key in keys:
        cur_v = int(current.get(key) or 0)
        prev_v = int(prev.get(key) or 0)
        if cur_v > prev_v:
            out[key] = cur_v - prev_v
    return out


def _find_topic_for_concept(concept_name: str, topics_catalog: dict[str, Any] | None) -> dict[str, Any] | None:
    target = (concept_name or "").strip().lower()
    if not target or not isinstance(topics_catalog, dict):
        return None
    for topic in topics_catalog.get("topics") or []:
        tid = str(topic.get("topic_id") or "").strip().lower()
        tname = str(topic.get("topic_name") or "").strip().lower()
        key_concepts = [str(x).strip().lower() for x in (topic.get("key_concepts") or [])]
        if target == tid or target == tname or target in key_concepts:
            return topic
    return None


def _topic_documents_index(topics_catalog: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(topics_catalog, dict):
        return out
    for topic in topics_catalog.get("topics") or []:
        for doc in topic.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            key = str(doc.get("relative_path") or doc.get("file_name") or "").strip()
            if key and key not in out:
                out[key] = doc
    return out
