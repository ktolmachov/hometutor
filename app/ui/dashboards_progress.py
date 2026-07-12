"""Learning progress tab and personalization settings dashboards."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app.course_metrics import collect_course_progress, record_course_workflow_event
from app import quiz_service
from app.ui.answer_helpers import run_synthesis_for_paths as _run_synthesis_for_paths
from app.ui.helpers import format_request_error as _format_request_error
from app.ui.home_hub import (
    _find_topic_for_concept,
    _topic_documents_index,
)
from app.ui.progress_visuals import build_course_filter_label as _build_course_filter_label
from app.ui.scoped_quiz import render_scoped_self_check_quiz as _render_scoped_self_check_quiz
from app.ui.topics_catalog import load_topics_catalog as _load_topics_catalog
from app.ui.tutor_mastery_forecast_panel import (
    render_tutor_orchestration_snapshot_expander as _render_tutor_orchestration_snapshot_expander,
)
from app.ui.widgets import (
    render_chip_row as _render_chip_row,
    render_panel_header as _render_panel_header,
)
from app.ui_client import fetch_json as _fetch_json


def _render_course_progress_panel(scope: dict[str, Any]) -> None:
    last_topic = str(
        st.session_state.get("tutor_goal_subtopic")
        or st.session_state.get("current_topic")
        or ""
    ).strip()
    summary = collect_course_progress(scope, last_topic=last_topic)
    event_key = f"course_progress_panel_seen_{summary.get('course_id') or scope.get('id')}"
    if not st.session_state.get(event_key):
        record_course_workflow_event(
            "progress_panel_view",
            scope,
            scenario="progress_panel",
            payload={
                "documents": summary["documents"],
                "cards_total": summary["cards_total"],
                "due_today": summary["due_today"],
            },
        )
        st.session_state[event_key] = True

    with st.container(border=True):
        st.markdown(f"**Активный курс:** {summary['course_title']}")
        st.caption(
            f"Метрики этого блока пишутся с label `{summary['metrics_label']}`. "
            "Общий прогресс ниже не смешивается с курсом, пока включен фильтр."
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Документы", str(summary["documents"]))
        with c2:
            st.metric("Карточки", str(summary["cards_total"]))
        with c3:
            st.metric("Due today", str(summary["due_today"]))
        with c4:
            st.metric("Освоено", str(summary["cards_mastered"]))

        if summary["last_topic"]:
            st.caption(f"Последняя тема Tutor: **{summary['last_topic']}**")
        else:
            st.caption("Последняя тема Tutor появится после перехода из карточки или занятия.")

        gaps = summary.get("gaps") or []
        if gaps:
            st.markdown("**Ближайшие пробелы**")
            for gap in gaps:
                st.caption(f"- {gap}")
        elif summary["due_today"]:
            st.caption("Есть карточки к повторению; открой Flashcards, чтобы разобрать очередь.")
        else:
            st.caption("На сегодня нет due-карточек по активному курсу.")


def _render_personalization_settings() -> None:
    """Предпочтения стиля и weekly goals (SQLite app_kv)."""
    from app.user_state import (
        get_preferred_style,
        get_weekly_goals_state,
        increment_weekly_progress,
        set_kv,
        set_preferred_style,
    )

    st.subheader("Персонализация")
    st.caption("Стиль влияет на промпт тьютора и подсказки после micro-quiz; цели — на календарную неделю (UTC).")
    cur = get_preferred_style()
    opts = ["balanced", "examples", "theory", "practice"]
    labels = {
        "balanced": "Сбалансированно",
        "examples": "Через примеры",
        "theory": "Через теорию",
        "practice": "Через практику",
    }
    try:
        idx = opts.index(cur)
    except ValueError:
        idx = 0
    style = st.selectbox(
        "Как ты лучше всего учишься?",
        opts,
        index=idx,
        format_func=lambda x: labels.get(x, x),
        key="personalization_style_select",
    )
    if st.button("Сохранить стиль", key="personalization_style_save"):
        set_preferred_style(style)
        st.success("Стиль сохранён.")
        st.rerun()

    st.subheader("Цели на неделю")
    state = get_weekly_goals_state()
    targets = state.get("targets") or {}
    done = state.get("done") or {}
    week_id = state.get("week_id") or "—"
    st.caption(f"Неделя: **{week_id}**")
    for key in ("new_topics", "reviews", "quizzes"):
        t = int(targets.get(key, 1))
        d = int(done.get(key, 0))
        pct = min(1.0, d / t) if t > 0 else 0.0
        titles = {
            "new_topics": "Новые темы",
            "reviews": "Повторения",
            "quizzes": "Мини-квизы",
        }
        st.progress(pct, text=f"{titles.get(key, key)}: {d} / {t}")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Отметить новую тему", key="weekly_bump_topic"):
            increment_weekly_progress("new_topics", 1)
            st.rerun()
    with b2:
        if st.button("Отметить повторение", key="weekly_bump_review"):
            increment_weekly_progress("reviews", 1)
            st.rerun()

    if st.button("Показать мастер настройки снова", key="onboarding_reset_v1"):
        set_kv("onboarding_v1_done", "0")
        st.rerun()


def _consume_progress_focus_section(session: dict) -> tuple[bool, str | None]:
    """Pop deferred Progress anchor flag; return (expand personalization, focus value)."""
    from app.ui.session_state import PROGRESS_FOCUS_SECTION_KEY, PROGRESS_FOCUS_STREAK_WEEKLY

    focus = session.pop(PROGRESS_FOCUS_SECTION_KEY, None)
    expand = focus == PROGRESS_FOCUS_STREAK_WEEKLY
    return expand, focus if expand else None


def _render_learning_progress_tab() -> None:
    """Дашборд: gauge, radar, treemap, timeline, heatmap, streak, quiz_ui_stats."""
    from app.knowledge_service import knowledge_graph
    from app.quiz_stats import load_quiz_ui_stats
    from app.ui.session_state import PROGRESS_FOCUS_STREAK_WEEKLY
    from app.ui.study_scope import get_active_scope
    from app.visualization_service import vis_service

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header(
        "Прогресс обучения",
        "Mastery (gauge), распределение по level (radar + treemap), timeline, heatmap, streak и квизы (UI)",
    )
    expand_personalization, focus_section = _consume_progress_focus_section(st.session_state)
    with st.expander("Персонализация и цели недели", expanded=expand_personalization):
        if focus_section == PROGRESS_FOCUS_STREAK_WEEKLY:
            st.markdown(
                '<div data-testid="e2e-progress-focus-streak-weekly"></div>',
                unsafe_allow_html=True,
            )
        _render_personalization_settings()

    _render_tutor_orchestration_snapshot_expander(key_prefix="learning_progress", show_focus_concept=False)

    from app.ui.tutor_mastery_forecast_panel import render_learner_profile_migration_badge

    render_learner_profile_migration_badge()
    active_scope = get_active_scope()
    course_only = False
    if active_scope:
        course_only = st.checkbox(
            _build_course_filter_label(active_scope),
            value=True,
            key="learning_progress_active_course_only",
            help="Показывает отдельную сводку по документам и карточкам текущего StudyScope.",
        )
        if course_only:
            _render_course_progress_panel(active_scope)

    try:
        import plotly.express as px
    except ImportError:
        st.warning("Установите plotly: pip install plotly (см. requirements.txt).")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    stats = knowledge_graph.get_progress_stats()
    qs = load_quiz_ui_stats()
    try:
        from app.user_state import get_flashcard_progress_stats
    except Exception:
        pass

    # C1: Student-facing agent runs history (compact, after A2 router)
    try:
        runs = _fetch_json("GET", "/agent/runs?limit=5") or []
        if runs:
            with st.expander("🤖 Что агент собирал для вас", expanded=False):
                st.caption("Последние учебные сессии, собранные агентом (только чтение).")
                for r in runs[:5]:
                    rid = str(r.get("run_id", ""))[:8]
                    q = str(r.get("question") or "")[:80]
                    status = r.get("answer_status") or r.get("stop_reason") or ""
                    st.markdown(f"- **{q}** · `{status}` · run `{rid}`")
                st.caption("Полная история и детали — через API /agent/runs (для команды).")
    except Exception:
        pass  # best effort, don't break progress tab


        _fc_prog = get_flashcard_progress_stats()
    except Exception as _exc:  # noqa: BLE001 - robust visualization fallback if flashcards database lock occurs
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        _fc_prog = {"total": 0, "mastered": 0, "due": 0}
    from app.ui.adaptive_plan_card import adaptive_plan_progress_teaser_caption as _adp_progress_teaser
    from app.visualization_service import dashboard as _mastery_dashboard

    md = _mastery_dashboard.get_mastery_data()
    _gam = md.get("gamification") or {}
    _wg = md.get("weekly_goals") or {}
    _pg = md.get("prerequisite_graph") or {}
    _mv = md.get("mastery_vector") or {}
    _avg_quiz = round(float(_mv.get("avg") or 0.0) * 100.0, 1)
    _n_kg = len(_pg.get("nodes") or [])
    _e_kg = len(_pg.get("edges") or [])
    _quiz_rows_n = len(md.get("quiz_mastery_rows") or [])
    _due_n_progress = int(md.get("due_count") or 0)

    with st.container(border=True):
        st.markdown(
            "**Сводка прогресса** — покрытие графа, цели недели, очередь повторений, "
            "ежедневная активность и стрик квиза (разные метрики)."
        )
        u1, u2, u3 = st.columns(3)
        with u1:
            st.metric(
                "Покрытие графа (KG)",
                f"{stats['mastery_percent']}%",
                f"{stats['learned']}/{stats['total_concepts']} изуч.",
                help="Доля концептов с learned в активном concept_graph.json.",
            )
        with u2:
            st.metric(
                "Mastery по quiz (вектор)",
                f"{_avg_quiz}%",
                f"{_quiz_rows_n} концепт(ов) в quiz_mastery",
                help="Среднее по уровням adaptive quiz для концептов графа (или всех строк, если граф пуст).",
            )
        with u3:
            st.metric(
                "Повторения по расписанию",
                str(_due_n_progress),
                help="Количество просроченных/созревших повторений по концептам активного графа.",
            )
        st.caption(
            "Краткий чек «до/после» выбранного шага опирается на те же локальные очереди "
            "flashcards и повторений по графу, что и подсказка выше на этой вкладке."
        )
        u4, u5, u6 = st.columns(3)
        with u4:
            st.metric(
                "Ежедневный стрик",
                f"{int(_gam.get('daily_streak') or 0)} дн.",
                help="Подряд дней с активностью в приложении (XP/план). Не то же самое, что стрик квиза в UI.",
            )
        with u5:
            st.metric(
                "Стрик квиза (UI)",
                f"{qs['streak_days']} дн.",
                help="Подряд дней, когда отмечена активность в UI квизов (quiz_stats).",
            )
        with u6:
            st.metric("Вопросов в квизах (UI)", str(qs["total_questions_answered"]))

        u7, u8, u9 = st.columns(3)
        with u7:
            st.metric(
                "Flashcards — всего",
                str(int(_fc_prog.get("total") or 0)),
                help="Карточки во всех колодах (SQLite).",
            )
        with u8:
            st.metric(
                "Flashcards — освоено",
                str(int(_fc_prog.get("mastered") or 0)),
                help="Интервал повторения > 21 день (карточка «в долгой» памяти).",
            )
        with u9:
            st.metric(
                "Flashcards — к повтору",
                str(int(_fc_prog.get("due") or 0)),
                help="Карточки с next_review ≤ сейчас или без расписания (новые).",
            )

        st.markdown("**Цели недели** (UTC)")
        _targets = _wg.get("targets") or {}
        _done = _wg.get("done") or {}
        _week_id = _wg.get("week_id") or "—"
        st.caption(f"Неделя: **{_week_id}** — настройка в блоке «Персонализация и цели недели» ниже.")
        _wg_titles = {
            "new_topics": "Новые темы",
            "reviews": "Повторения",
            "quizzes": "Мини-квизы",
        }
        for _key in ("new_topics", "reviews", "quizzes"):
            _t = int(_targets.get(_key, 1))
            _d = int(_done.get(_key, 0))
            _pct = min(1.0, _d / _t) if _t > 0 else 0.0
            st.progress(_pct, text=f"{_wg_titles.get(_key, _key)}: {_d} / {_t}")

        st.markdown("**Снимок графа (prerequisites)**")
        if _n_kg > 0:
            st.caption(
                f"Концептов в графе: **{_n_kg}** · связей prerequisite→концепт: **{_e_kg}** · "
                "полный интерактивный граф — вкладка «Knowledge Graph»."
            )
        else:
            st.info(
                "В `concept_graph.json` пока нет концептов — снимок prerequisites пуст. "
                "После ingest или прогресса в квизах узлы могут появиться из quiz_mastery на вкладке KG."
            )
        if _quiz_rows_n == 0:
            st.caption(
                "Строк **quiz_mastery** пока нет — адаптивный вектор и счётчики recognition/recall/transfer "
                "заполнятся после мини-квизов."
            )

        _plan_teaser = _adp_progress_teaser()
        if _plan_teaser:
            st.caption(_plan_teaser)
        st.caption(
            f"Завершённых сессий квиза (UI): **{qs['quiz_sessions_completed']}** · "
            "Gauge / radar / heatmap — ниже на этой вкладке."
        )

    st.subheader("Быстрый тест по теме каталога")
    tc_lp = _load_topics_catalog(force=False)
    topics_lp = (tc_lp or {}).get("topics") or []
    if topics_lp:
        _tid_opts = {t["topic_id"]: (t.get("topic_name") or t["topic_id"]) for t in topics_lp if t.get("topic_id")}
        _pick_tid = st.selectbox(
            "Тема для теста",
            list(_tid_opts.keys()),
            format_func=lambda x: _tid_opts.get(x, x),
            key="learning_progress_topic_quiz_pick",
        )
        pct_est = quiz_service.estimate_mastery_percent(str(_pick_tid))
        st.caption(f"Оценка mastery по прогрессу: **{pct_est}%**")
        from app.ui.quiz_learning_mode_widgets import (
            render_scoped_quiz_learning_mode_select as _render_lp_quiz_lm,
            scoped_quiz_learning_mode_value as _lp_quiz_lm_value,
        )

        _render_lp_quiz_lm(session_key="learning_progress_scoped_quiz_lm")
        _lp_lm = _lp_quiz_lm_value("learning_progress_scoped_quiz_lm")
        if st.button("Начать тест", key="learning_progress_topic_quiz_run"):
            try:
                data = _fetch_json(
                    "POST",
                    "/quiz/generate",
                    timeout=120,
                    json={
                        "scope": "topic",
                        "identifier": _pick_tid,
                        "num_questions": 6,
                        "difficulty": "adaptive",
                        "learning_mode": _lp_lm,
                    },
                )
                st.session_state["learning_progress_quiz_payload"] = data.get("quiz") or {}
                st.session_state.pop("learning_progress_quiz_err", None)
            except Exception as e:  # noqa: BLE001 - robust UI action, catch quiz generation failure
                st.session_state["learning_progress_quiz_err"] = _format_request_error(e)
            st.rerun()
        _lq_err = st.session_state.pop("learning_progress_quiz_err", None)
        if _lq_err:
            st.warning(_lq_err)
        _lq = st.session_state.get("learning_progress_quiz_payload")
        if isinstance(_lq, dict) and _lq.get("questions"):
            _render_scoped_self_check_quiz(
                _lq["questions"],
                source_key="learning_progress_quiz",
                quiz_meta=_lq,
            )
    else:
        st.caption("Каталог тем пока пуст — после индексации откройте вкладку «Темы».")

    concepts = knowledge_graph.get_concepts()
    learned_with_date = sum(
        1
        for c in concepts.values()
        if isinstance(c, dict) and c.get("learned") and c.get("learned_at")
    )
    st.success(
        f"С датой изучения (learned_at): **{learned_with_date}** концепт(ов) • "
        f"Ежедневный стрик: **{int((md.get('gamification') or {}).get('daily_streak') or 0)}** дн. · "
        f"Стрик квиза (UI): **{qs['streak_days']}** дн."
    )

    tot = stats["total_concepts"]
    if tot == 0:
        st.info("В графе нет концептов — добавьте concept_graph.json или концепты через ingest.")
    else:
        col_g, col_r = st.columns([2, 3])
        with col_g:
            gauge_fig = vis_service.create_mastery_gauge(float(stats["mastery_percent"]))
            st.plotly_chart(gauge_fig, width='stretch')
        with col_r:
            ld = stats["level_distribution"]
            st.plotly_chart(
                vis_service.create_radar_chart(ld),
                width='stretch',
            )
            st.plotly_chart(
                vis_service.create_treemap(ld),
                width='stretch',
            )

    st.subheader("Недавно изученное")
    tl = stats["recent_timeline"]
    if tl:
        df_tl = pd.DataFrame(
            [{"Дата": str(d).split("T")[0], "Концепт": n} for d, n in tl]
        )
        st.dataframe(df_tl, width='stretch', hide_index=True)
    else:
        st.info("Пока нет записей с learned_at у изученных концептов.")

    st.subheader("Heatmap прогресса")
    names = list(concepts.keys())[:40]
    if names:
        vals = [
            1.0
            if (isinstance(concepts[n], dict) and concepts[n].get("learned"))
            else 0.0
            for n in names
        ]
        fig_heat = px.imshow(
            [vals],
            x=names,
            y=["Прогресс"],
            color_continuous_scale="RdYlGn",
            zmin=0,
            zmax=1,
        )
        st.plotly_chart(fig_heat, width='stretch')
    else:
        st.caption("В графе нет концептов.")

    from app.ui.weekly_study_narrative_ui import render_weekly_study_narrative_block

    render_weekly_study_narrative_block(key_prefix="learning_progress")

    st.markdown("</div>", unsafe_allow_html=True)
