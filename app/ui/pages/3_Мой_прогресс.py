"""Вкладка «Мой прогресс»: PLM 19.5, Emotional Heatmap, подграф KG, quiz mastery, spaced repetition."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import plotly.express as px
import streamlit as st

from app.knowledge_service import get_personalized_subgraph, knowledge_graph as kg
from app.learner_model_service import get_personalized_learner_profile
from app.learning_plan_service import plan_service
from app.quiz_service import weak_spot_scoped_quiz_params
from app.quiz_stats import load_quiz_ui_stats
from app.ui.adaptive_plan_widgets import render_adaptive_daily_plan_section
from app.ui.learner_profile_panel import render_personalized_learner_panel
from app.ui.progress_visuals import (
    build_emotional_heatmap_figure,
    build_personalized_subgraph_elements,
    build_quiz_activity_timeline,
)
from app.ui.continuity_bridge import (
    continuity_next_step_line_ru,
    guided_primary_home_cta_ru,
    guided_primary_reason_line_ru,
    load_qa_tutor_handoff_context,
    tutor_reason_line_ru,
)
from app.ui.auth_gate import require_ui_auth_or_stop
from app.visualization_service import dashboard, vis_service

st.set_page_config(page_title="Мой прогресс", layout="wide")
require_ui_auth_or_stop()

st.title("Мой прогресс")

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
        st.session_state["current_view"] = _target
        st.rerun()

from app.ui.weekly_study_narrative_ui import render_weekly_study_narrative_block

render_weekly_study_narrative_block(key_prefix="progress_page")

_user_id = "local"
_sid = str(st.session_state.get("tutor_session_id") or "").strip() or None
profile = get_personalized_learner_profile(_user_id, session_id=_sid)
data = dashboard.get_mastery_data()
_qs = load_quiz_ui_stats()
_pg = data.get("prerequisite_graph") or {}
_n_kg = len(_pg.get("nodes") or [])
_e_kg = len(_pg.get("edges") or [])
_mv = data.get("mastery_vector") or {}
_avg_m = round(float(_mv.get("avg") or 0.0) * 100.0, 1)
_quiz_rows_n = len(data.get("quiz_mastery_rows") or [])
_wg = data.get("weekly_goals") or {}
_gam_prev = data.get("gamification") or {}

st.subheader("Сводка Progress")
with st.container(border=True):
    st.caption(
        "Один срез: mastery, цели недели (UTC), очередь повторений, снимок prerequisites, "
        "ежедневный стрик геймификации и стрик дней в UI-квизах — разные метрики."
    )
    r1, r2, r3 = st.columns(3)
    with r1:
        st.metric(
            "Mastery (вектор, среднее)",
            f"{_avg_m}%",
            f"{_quiz_rows_n} строк quiz_mastery",
            help="Среднее по adaptive quiz для концептов графа (или всех строк, если граф пуст).",
        )
    with r2:
        st.metric(
            "Повторения по расписанию",
            str(int(data.get("due_count") or 0)),
            help="Просроченные/созревшие повторения по концептам активного графа.",
        )
    with r3:
        _stats = kg.get_progress_stats()
        st.metric(
            "Покрытие графа (KG)",
            f"{_stats['mastery_percent']}%",
            f"{_stats['learned']}/{_stats['total_concepts']} изуч.",
            help="Доля концептов с learned в активном concept_graph.json.",
        )
    r4, r5, r6 = st.columns(3)
    with r4:
        st.metric(
            "Ежедневный стрик (геймификация)",
            f"{int(_gam_prev.get('daily_streak') or 0)} дн.",
            help="Подряд дней с активностью в приложении (XP/план). Не стрик UI-квизов.",
        )
    with r5:
        st.metric(
            "Стрик дней (UI-квизы)",
            f"{int(_qs.get('streak_days') or 0)} дн.",
            help="Подряд дней с завершённой активностью в UI-квизах (quiz_ui_stats.json).",
        )
    with r6:
        st.metric(
            "Стрик успешных ответов (геймификация)",
            str(int(_gam_prev.get("quiz_streak") or 0)),
            help="Подряд успешных квизов (≥70%) в счётчике геймификации — не дни и не UI-streak.",
        )

    st.markdown("**Цели недели** (UTC)")
    _targets = _wg.get("targets") or {}
    _done = _wg.get("done") or {}
    _week_id = _wg.get("week_id") or "—"
    st.caption(f"Неделя: **{_week_id}** (хранение в app_kv / настройки персонализации на главном экране).")
    _wg_titles = {"new_topics": "Новые темы", "reviews": "Повторения", "quizzes": "Мини-квизы"}
    for _key in ("new_topics", "reviews", "quizzes"):
        _t = int(_targets.get(_key, 1))
        _d = int(_done.get(_key, 0))
        _pct = min(1.0, _d / _t) if _t > 0 else 0.0
        st.progress(_pct, text=f"{_wg_titles.get(_key, _key)}: {_d} / {_t}")

    st.markdown("**Снимок prerequisites (KG)**")
    if _n_kg > 0:
        st.caption(
            f"Узлов: **{_n_kg}** · рёбер prerequisite→концепт: **{_e_kg}** · "
            "полный граф — раздел Knowledge Graph ниже или отдельная вкладка."
        )
    else:
        st.info(
            "В `concept_graph.json` пока нет концептов — снимок prerequisites пуст. "
            "После ingest или прогресса узлы могут появиться из quiz_mastery."
        )
    if _quiz_rows_n == 0:
        st.caption(
            "Строк **quiz_mastery** пока нет — уровни recognition/recall/transfer заполнятся после мини-квизов."
        )

render_personalized_learner_panel(session_id=_sid, variant="full")

plan = plan_service.generate_personalized_plan(days=7, user_progress=True)
adp = plan.get("adaptive_daily_plan") if isinstance(plan.get("adaptive_daily_plan"), dict) else {}
render_adaptive_daily_plan_section(
    plan_override=plan.get("adaptive_daily_plan"),
    key_prefix="progress_adp",
)

st.subheader("Quiz mastery (сводка)")
c1, c2, c3 = st.columns(3)
cm = data["concepts_mastered"]
with c1:
    st.metric("Recognition", cm.get("recognition", 0))
with c2:
    st.metric("Recall", cm.get("recall", 0))
with c3:
    st.metric("Transfer", cm.get("transfer", 0))
st.caption(
    "Счётчики по строкам в quiz_mastery (концепты с хотя бы одной записью в адаптивном quiz)."
)

# --- Emotional Heatmap + подграф (PLM 19.5 + снимки из KV) ---
rec = data.get("next_recommendation") or {}
rec_topic = str(rec.get("topic") or "").strip() or None
weak = plan.get("weak_spots") or []

_sub = get_personalized_subgraph(seed_topic=rec_topic, limit=14, kg=kg)
_seed_concepts = [str(n.get("id") or "").strip() for n in (_sub.get("nodes") or []) if str(n.get("id") or "").strip()]
if not _seed_concepts and weak:
    _seed_concepts = list(weak[:8])

st.subheader("Emotional Heatmap")
fig_heat, heatmap_synthetic = build_emotional_heatmap_figure(
    profile=profile,
    seed_concepts=_seed_concepts,
    last_days=30,
)
st.plotly_chart(fig_heat, width='stretch')
if heatmap_synthetic:
    st.caption(
        "История эмоций появится после ответов тьютора и квизов (снимки пишутся в KV). "
        "Сейчас показан срез по текущему emotional_state модели 19.5."
    )

st.subheader("Mastery radar")
st.plotly_chart(
    vis_service.create_mastery_vector_radar(profile.mastery_vector, top_n=10),
    width='stretch',
)

st.info(
    f"**Рекомендация (PLM 19.5, emotional_state: {profile.emotional_state})** — "
    f"{adp.get('motivation_message') or plan.get('motivation_tip') or 'Продолжайте по плану и возвращайтесь к слабым концептам.'}"
)

_timeline = build_quiz_activity_timeline(data.get("quiz_mastery_rows"))
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
            "Цвет узла: освоение (зелёный / жёлтый / красный). Эмодзи: последний снимок emotional_state по концепту или глобальный профиль."
        )

gam = data.get("gamification") or {}
if gam:
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
            help="Подряд успешных квизов ≥70% в геймификации; см. также «Стрик дней (UI-квизы)» в сводке выше.",
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

st.subheader("AI Coach")
st.write(plan.get("motivation_tip") or "")
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

if data.get("due_reviews"):
    st.warning(f"Пора повторить: **{data['due_count']}** тем по расписанию.")
    with st.expander("Список просроченных повторений", expanded=False):
        st.dataframe(data["due_reviews"], width='stretch', hide_index=True)
else:
    st.info("Нет просроченных повторений — всё по расписанию.")

topic = rec.get("topic")
reason = rec.get("reason")
msg = rec.get("message")
if topic:
    reason_ru = {
        "spaced_repetition_due": "сначала повторите по расписанию",
        "quiz_mastery_path": "следующий шаг по уровню освоения и топологии графа",
        "reading_incomplete": "есть незавершённое чтение по теме",
    }.get(str(reason), str(reason))
    st.success(f"**Следующая тема:** `{topic}` — {reason_ru}")
elif msg:
    st.success(msg)
else:
    st.info("Нет рекомендации (пустой граф или нет данных).")

st.subheader("Распределение по уровням (quiz)")
labels = ["Recognition", "Recall", "Transfer"]
values = [cm.get("recognition", 0), cm.get("recall", 0), cm.get("transfer", 0)]
if sum(values) == 0:
    st.caption("Пока нет записей в quiz_mastery.")
else:
    fig = px.pie(
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
    fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), showlegend=True)
    st.plotly_chart(fig, width='stretch')

st.subheader("Граф зависимостей (mastery + due)")
pg = data.get("prerequisite_graph") or {}
overlay = pg.get("mastery_overlay") or {}

try:
    from streamlit_agraph import Config, agraph
except ImportError:
    st.warning("Установите streamlit-agraph (см. requirements.txt).")
    st.json(pg)
else:
    nodes, edges = vis_service.get_mastery_nodes_edges(kg, overlay)
    if not nodes:
        st.info("В графе нет узлов — проверьте data/concept_graph.json.")
        with st.expander("Сырые данные (JSON)"):
            st.json(pg)
    else:
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

if data.get("reading_topics"):
    st.subheader("Чтение по темам (reading_status)")
    st.dataframe(data["reading_topics"], width='stretch', hide_index=True)
