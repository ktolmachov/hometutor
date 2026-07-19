"""Progress tab sub-sections: «Главное» (home-focused) and extended extras (ex-orphan).

Split into helpers under 80 lines each to stay within the architecture size budget.
"""

from __future__ import annotations

from typing import Any
import streamlit as st

from app.ui.continuity_bridge import (
    continuity_next_step_line_ru,
    guided_primary_home_cta_ru,
    guided_primary_reason_line_ru,
    load_qa_tutor_handoff_context,
    tutor_reason_line_ru,
)
from app.ui.learner_profile_panel import render_personalized_learner_panel
from app.ui.adaptive_plan_widgets import render_adaptive_daily_plan_section
from app.ui.progress_visuals import (
    build_emotional_heatmap_figure,
    build_personalized_subgraph_elements,
    build_quiz_activity_timeline,
)


# ---------------------------------------------------------------------------
# «Главное» tab helpers
# ---------------------------------------------------------------------------


def _render_home_mastery_one_number(md: dict[str, Any]) -> None:
    """B3: Один процент mastery (PLM-вектор) с подписью источника."""
    _mv = md.get("mastery_vector") or {}
    _avg_quiz = round(float(_mv.get("avg") or 0.0) * 100.0, 1)
    _quiz_rows_n = len(md.get("quiz_mastery_rows") or [])
    with st.container(border=True):
        st.markdown("**Mastery** — на основе проверок знаний")
        st.metric("PLM-вектор (adaptive quiz)", f"{_avg_quiz}%",
                  help="Среднее по уровням Recognition / Recall / Transfer. Обновляется после каждого мини-квиза.")
        if _quiz_rows_n == 0:
            st.caption("Записей пока нет — заполнится после мини-квизов (вкладка «Расширенные»).")
        else:
            st.caption(f"По {_quiz_rows_n} концептам. Покрытие графа и другие проценты — «Расширенные».")


def _render_home_my_trail() -> None:
    """B1 «Мой след»: XP-календарь 7 дней + flashcard counters."""
    from app.gamification_service import get_xp_history
    from app.user_state import get_flashcard_progress_stats as _fc_stats
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    with st.container(border=True):
        st.markdown("**Мой след** — активность, карточки")
        hist = get_xp_history(days=7)
        if hist:
            days_html = "".join(
                f"<td style='text-align:center;padding:2px 5px;font-size:0.75rem;"
                f"background:{'#e8f5e9' if d.get('xp',0)>0 else '#fafafa'};border-radius:4px;'>"
                f"<div>{d['date'][-5:]}</div>"
                f"<div style='font-weight:600;color:{'#2e7d32' if d.get('xp',0)>0 else '#9e9e9e'}'>"
                f"{d.get('xp',0)}</div></td>"
                for d in hist
            )
            st.markdown(f"<table style='border-spacing:2px'><tr>{days_html}</tr></table>",
                        unsafe_allow_html=True)
            st.caption("XP по дням (UTC, 7 дней).")
        try:
            fc = _fc_stats()
        except Exception:  # noqa: BLE001 - flashcard stats are optional; progress tab must not break
            fc = {"total": 0, "mastered": 0, "due": 0}
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("🎴 Карточки", fc.get("total", 0))
        with c2:
            st.metric("✅ Освоено", fc.get("mastered", 0))
        with c3:
            st.metric("📋 К повтору", fc.get("due", 0))
        if st.button("Открыть Flashcards", key="home_trail_fc_btn", width="stretch"):
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
            st.rerun()


def _render_home_my_path(md: dict[str, Any]) -> None:
    """B2 «Мой путь»: позиция на маршруте курса из reading_status."""
    from app.user_state_reading import get_latest_learning_plan_resume

    plan = get_latest_learning_plan_resume()
    if not plan:
        return
    with st.container(border=True):
        st.markdown("**Мой путь** — позиция на маршруте курса")
        step_label = str(plan.get("step_label") or "").strip()
        step_idx_raw = plan.get("step_index")
        step_idx = int(step_idx_raw) + 1 if step_idx_raw is not None else None
        title = str(plan.get("display_title") or plan.get("resource_id") or "").strip()
        progress_raw = float(plan.get("progress") or 0)
        progress = max(0.0, min(1.0, progress_raw))
        if step_label and step_idx is not None:
            st.markdown(f"📖 **Курс:** {title} · шаг {step_idx} «{step_label}»")
        elif title:
            st.markdown(f"📖 **Курс:** {title}")
        else:
            st.markdown("📖 **Курс:** (без названия)")
        if progress > 0:
            st.progress(progress, text=f"Прогресс: {int(progress * 100)}%")
        else:
            st.caption("Ещё не начат")


def _render_home_handoff_context_and_cta() -> None:
    """Handoff context + primary CTA (next step button)."""
    from app.gamification_service import get_snapshot as _get_gamification_snapshot
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    _handoff = load_qa_tutor_handoff_context(st.session_state)
    if isinstance(_handoff, dict):
        _topic = str(_handoff.get("topic") or "").strip()
        with st.container(border=True):
            st.caption("Текущий учебный контекст")
            if _topic:
                st.markdown(f"Тема: **{_topic}**")
            st.caption(f"Почему это подходит: {tutor_reason_line_ru()}")
            st.caption(continuity_next_step_line_ru(topic=_topic))

    _fc_due = int(st.session_state.get("flashcards_due_count") or 0)
    _due_n = int(st.session_state.get("progress_due_count_hint") or 0)
    _has_resume = bool(st.session_state.get("tutor_session_id"))
    _has_gap = bool(st.session_state.get("progress_has_mastery_gap"))
    _cta_label, _cta_kind = guided_primary_home_cta_ru(
        flashcard_due_n=_fc_due,
        has_tutor_resume=_has_resume,
        due_n=_due_n,
        has_mastery_gap=_has_gap,
    )
    with st.container(border=True):
        st.caption("Следующий шаг")
        st.caption(guided_primary_reason_line_ru(_cta_kind))
        st.caption(continuity_next_step_line_ru(topic=str((_handoff or {}).get("topic") or "")))
        if st.button(_cta_label, key="progress_guided_primary_cta", type="primary", width='stretch'):
            _target = "Чат с тьютором"
            if _cta_kind == "flashcard_due":
                _target = "Flashcards"
            elif _cta_kind == "due_review":
                _target = "Прогресс обучения"
            elif _cta_kind == "mastery_gap":
                _target = "Темы"
            st.session_state[PENDING_CURRENT_VIEW_KEY] = _target
            st.rerun()

    _gam = _get_gamification_snapshot()
    if _gam:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("🔥 Стрик", f"{_gam.get('daily_streak', 0)} дн.")
        with c2:
            st.metric("Уровень", str(_gam.get('level_title') or '?'))
        with c3:
            st.metric("XP", _gam.get('total_xp', 0))


def _render_home_heatmap_and_radar(md: dict[str, Any]) -> None:
    """Emotional heatmap + mastery radar + next recommendation."""
    from app.learner_model_service import get_personalized_learner_profile
    from app.visualization_service import vis_service

    _sid = str(st.session_state.get("tutor_session_id") or "").strip() or None
    _user_id = str(st.session_state.get("user_id") or "local").strip() or "local"
    profile = get_personalized_learner_profile(_user_id, session_id=_sid)

    st.subheader("Emotional Heatmap")
    fig_heat, heatmap_synthetic = build_emotional_heatmap_figure(
        profile=profile,
        seed_concepts=[],
        last_days=30,
    )
    st.plotly_chart(fig_heat, width='stretch')
    if heatmap_synthetic:
        st.caption(
            "История эмоций появится после ответов тьютора и квизов (снимки пишутся в KV). "
            "Сейчас показан срез по текущему emotional_state модели 19.5."
        )

    st.subheader("Mastery Radar")
    st.plotly_chart(
        vis_service.create_mastery_vector_radar(profile.mastery_vector, top_n=10),
        width='stretch',
    )

    rec = md.get("next_recommendation") or {}
    rec_topic = str(rec.get("topic") or "").strip() or None
    rec_msg = rec.get("message")
    if rec_topic:
        reason_ru = {
            "spaced_repetition_due": "сначала повторите по расписанию",
            "quiz_mastery_path": "следующий шаг по уровню освоения и топологии графа",
            "reading_incomplete": "есть незавершённое чтение по теме",
        }.get(str(rec.get("reason")), str(rec.get("reason")))
        st.success(f"**Следующая тема:** `{rec_topic}` — {reason_ru}")
    elif rec_msg:
        st.success(rec_msg)
    else:
        st.info("Нет рекомендации (пустой граф или нет данных).")


def render_progress_home_tab_impl(md: dict[str, Any]) -> None:
    """Вкладка «Главное»: mastery, след, путь, следующий шаг, heatmap, radar, narrative."""
    from app.ui.weekly_study_narrative_ui import render_weekly_study_narrative_block

    _render_home_mastery_one_number(md)
    _render_home_my_trail()
    _render_home_my_path(md)
    _render_lecture_depth_metric()
    _render_home_handoff_context_and_cta()
    _render_home_heatmap_and_radar(md)
    render_weekly_study_narrative_block(key_prefix="progress_home")


def _render_lecture_depth_metric() -> None:
    """P1: show «глубина лекции с подтверждением» for konspekts with segment progress."""
    try:
        from app.user_state_lecture import get_lecture_depth_summary
        summaries = get_lecture_depth_summary()
    except Exception:  # noqa: BLE001 — progress metric is best-effort
        return
    if not summaries:
        return
    for s in summaries[:3]:
        fname = str(s.get("konspekt_path", "")).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if not fname:
            fname = "лекция"
        import streamlit as st
        st.html(
            f'<div style="font-size:0.82rem;opacity:0.85;margin:0.15rem 0;">'
            f"🎧 {fname}: {s['passed_count']}/{s['total_stored']} отрезков "
            f"({s['depth_pct']}%)</div>"
        )


# ---------------------------------------------------------------------------
# «Расширенные» extras helpers (ex-orphan)
# ---------------------------------------------------------------------------


def _render_extras_section_a(md: dict[str, Any]) -> tuple[dict[str, Any], Any, str | None]:
    """Learner panel + adaptive plan + quiz mastery + activity timeline."""
    from app.knowledge_service import get_personalized_subgraph, knowledge_graph as kg
    from app.learner_model_service import get_personalized_learner_profile

    _sid = str(st.session_state.get("tutor_session_id") or "").strip() or None
    _user_id = str(st.session_state.get("user_id") or "local").strip() or "local"
    profile = get_personalized_learner_profile(_user_id, session_id=_sid)

    render_personalized_learner_panel(session_id=_sid, variant="full")

    from app.learning_plan_service import plan_service

    plan = plan_service.generate_personalized_plan(days=7, user_progress=True)
    render_adaptive_daily_plan_section(
        plan_override=plan.get("adaptive_daily_plan"),
        key_prefix="progress_adp",
    )
    return plan, profile, _sid


def _render_extras_section_b(md: dict[str, Any], profile: Any) -> None:
    """Quiz mastery summary + activity timeline + KG personalized subgraph."""
    from app.knowledge_service import knowledge_graph as kg

    st.subheader("Quiz mastery (сводка)")
    cm = md["concepts_mastered"]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Recognition", cm.get("recognition", 0))
    with c2:
        st.metric("Recall", cm.get("recall", 0))
    with c3:
        st.metric("Transfer", cm.get("transfer", 0))
    st.caption(
        "Счётчики по строкам в quiz_mastery (концепты с хотя бы одной записью в адаптивном quiz)."
    )

    rec = md.get("next_recommendation") or {}
    rec_topic = str(rec.get("topic") or "").strip() or None

    _timeline = build_quiz_activity_timeline(md.get("quiz_mastery_rows"))
    if _timeline is not None:
        st.subheader("Активность по quiz")
        st.plotly_chart(_timeline, width='stretch')

    st.subheader("Knowledge Graph: персональный подграф + mastery + эмоции")
    try:
        from streamlit_agraph import Config, agraph as _agraph
    except ImportError:
        st.warning("Установите streamlit-agraph (см. requirements.txt).")
    else:
        _nodes, _edges = build_personalized_subgraph_elements(
            kg,
            seed_topic=rec_topic,
            profile=profile,
            limit=20,
        )
        if not _nodes:
            st.info("Нет узлов подграфа — проверьте data/concept_graph.json и quiz_mastery.")
        else:
            _cfg = Config(
                width=1200,
                height=560,
                directed=True,
                physics=True,
                nodeHighlightBehavior=True,
                highlightColor="#FF5722",
                collapsible=True,
            )
            _agraph(nodes=_nodes, edges=_edges, config=_cfg)
            st.caption(
                "Цвет узла: освоение (зелёный / жёлтый / красный). "
                "Эмодзи: последний снимок emotional_state по концепту или глобальный профиль."
            )


def _render_extras_section_c(md: dict[str, Any]) -> None:
    """Gamification details (streak, level, XP, badges)."""
    gam = md.get("gamification") or {}
    if not gam:
        return
    st.subheader("Геймификация (детали)")
    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.metric(
            "Ежедневный стрик",
            f"{gam.get('daily_streak', 0)} дн.",
            help="Дни подряд с активностью в приложении (не стрик UI-квизов).",
        )
    with g2:
        st.metric("Уровень", str(gam.get("level_title") or "?"))
    with g3:
        st.metric("Всего XP", gam.get("total_xp", 0))
    with g4:
        st.metric(
            "Успехи подряд (квиз)",
            gam.get("quiz_streak", 0),
            help="Подряд успешных квизов ≥70% в геймификации.",
        )
    _cur = int(gam.get("xp_in_level") or 0)
    _sp = int(gam.get("xp_for_level_span") or 1000)
    st.caption(
        f"XP в текущем уровне: {_cur} / {_sp} · материалов ≥85%: {gam.get('mastered_documents_estimate', 0)}"
    )
    _badges = gam.get("badges") or []
    if _badges:
        from app.gamification_service import BADGE_DEFS

        _map = {bid: lab for bid, lab, _ in BADGE_DEFS}
        _labels = [_map.get(str(b), str(b)) for b in _badges]
        st.markdown("**Бейджи:** " + " · ".join(_labels))


def _render_extras_section_d(md: dict[str, Any], plan: dict) -> None:
    """AI Coach (motivation tip, retention forecast, next best actions, weak spots)."""
    from app.quiz_service import weak_spot_scoped_quiz_params

    st.subheader("AI Coach")
    plan_msg = plan.get("motivation_tip") or ""
    if plan_msg:
        st.write(plan_msg)
    rf = plan.get("retention_forecast") or {}
    wm = float(rf.get("weekly_mastery") or 0.0)
    st.caption("Индикатор прогресса по графу (эвристика, не медицинский прогноз)")
    st.progress(min(1.0, max(0.0, wm)))
    if plan.get("retention_insight"):
        st.caption(str(plan["retention_insight"]))
    te = plan.get("time_estimate") or {}
    if te.get("label_today"):
        st.caption(str(te.get("label_today")))
    nba = plan.get("next_best_actions") or []
    if nba:
        n0 = nba[0]
        if isinstance(n0, dict) and n0.get("concept"):
            st.info(
                f"Next best action: сначала **{n0['concept']}** "
                f"(оценка приоритета {n0.get('score', '')})."
            )
    weak = plan.get("weak_spots") or []
    if weak:
        st.caption("Слабые концепты (по quiz_mastery): " + ", ".join(weak[:6]))
        wp = weak_spot_scoped_quiz_params(weak)
        if wp and st.button("Целевой quiz по слабому месту", key="weak_spot_scoped_quiz"):
            st.session_state["coach_weak_spot_topic"] = wp.get("identifier")
            st.success("Тема передана. Откройте главный экран Home RAG — в боковой панели будет подсказка.")

    if md.get("due_reviews"):
        from app.ui_preferences import feature_visible_by_id

        st.warning(f"Пора повторить: **{md['due_count']}** тем по расписанию.")
        if feature_visible_by_id("panel:debug_summary"):
            with st.expander("Список просроченных повторений", expanded=False):
                st.dataframe(md["due_reviews"], width='stretch', hide_index=True)
    else:
        st.info("Нет просроченных повторений — всё по расписанию.")


def _render_extras_section_e(md: dict[str, Any]) -> None:
    """Quiz level distribution pie chart."""
    st.subheader("Распределение по уровням (quiz)")
    import plotly.express as px

    cm = md["concepts_mastered"]
    labels = ["Recognition", "Recall", "Transfer"]
    values = [cm.get("recognition", 0), cm.get("recall", 0), cm.get("transfer", 0)]
    if sum(values) == 0:
        st.caption("Пока нет записей в quiz_mastery.")
    else:
        fig_pie = px.pie(
            names=labels,
            values=values,
            color=labels,
            color_discrete_map={
                "Recognition": "#FFD700",
                "Recall": "#FF9800",
                "Transfer": "#27AE60",
            },
            hole=0.45,
        )
        fig_pie.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=True)
        st.plotly_chart(fig_pie, width='stretch')


def _render_extras_section_f(md: dict[str, Any]) -> None:
    """Prerequisite graph (mastery + due) with dual palette views."""
    from app.knowledge_service import knowledge_graph as kg
    from app.ui_preferences import feature_visible_by_id
    from app.visualization_service import vis_service

    st.subheader("Граф зависимостей (mastery + due)")
    pg = md.get("prerequisite_graph") or {}
    overlay = pg.get("mastery_overlay") or {}

    try:
        from streamlit_agraph import Config, agraph
    except ImportError:
        st.warning("Установите streamlit-agraph (см. requirements.txt).")
        if feature_visible_by_id("panel:debug_summary"):
            st.json(pg)
        return

    nodes, edges = vis_service.get_mastery_nodes_edges(kg, overlay)
    if not nodes:
        st.info("В графе нет узлов — проверьте data/concept_graph.json.")
        if feature_visible_by_id("panel:debug_summary"):
            with st.expander("Сырые данные (JSON)"):
                st.json(pg)
        return

    leg1, leg2, leg3, leg4 = st.columns(4)
    with leg1:
        st.markdown(
            '<span style="color:#FFD700;font-weight:700">●</span> recognition',
            unsafe_allow_html=True,
        )
    with leg2:
        st.markdown(
            '<span style="color:#FF9800;font-weight:700">●</span> recall',
            unsafe_allow_html=True,
        )
    with leg3:
        st.markdown(
            '<span style="color:#27AE60;font-weight:700">●</span> transfer',
            unsafe_allow_html=True,
        )
    with leg4:
        st.caption("Крупнее узел — есть просроченное повторение.")

    config = Config(
        width=1400,
        height=720,
        directed=True,
        physics=False,
        hierarchical=True,
        nodeHighlightBehavior=True,
        highlightColor="#FF5722",
        collapsible=True,
        labelProperty="label",
    )
    agraph(nodes=nodes, edges=edges, config=config)

    st.subheader("Карта знаний (слабый / в работе / mastered)")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.markdown(
            '<span style="color:#e53935;font-weight:700">●</span> recognition (слабый)',
            unsafe_allow_html=True,
        )
    with r2:
        st.markdown(
            '<span style="color:#fbc02d;font-weight:700">●</span> recall (в работе)',
            unsafe_allow_html=True,
        )
    with r3:
        st.markdown(
            '<span style="color:#2e7d32;font-weight:700">●</span> transfer (mastered)',
            unsafe_allow_html=True,
        )
    nodes_ryg, edges_ryg = vis_service.get_mastery_nodes_edges(kg, overlay, palette="ryg")
    if nodes_ryg:
        agraph(nodes=nodes_ryg, edges=edges_ryg, config=config)


def render_progress_extended_extras(md: dict[str, Any]) -> None:
    """Дополнительный контент из бывшей orphan page для вкладки «Расширенные»."""
    from app.ui_preferences import feature_visible_by_id

    plan, profile, _sid = _render_extras_section_a(md)
    _render_extras_section_b(md, profile)
    _render_extras_section_c(md)
    _render_extras_section_d(md, plan)
    _render_extras_section_e(md)
    _render_extras_section_f(md)

    if md.get("reading_topics") and feature_visible_by_id("panel:debug_summary"):
        st.subheader("Чтение по темам (reading_status)")
        st.dataframe(md["reading_topics"], width='stretch', hide_index=True)
