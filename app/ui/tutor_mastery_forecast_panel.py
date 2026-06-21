"""Панель emotional_state + XP forecast (PLM 19.5) — тяжёлые зависимости подгружаются внутри функции."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from app.gamification_service import get_daily_xp, get_total_xp, get_xp_history
from app.learning_plan_service import AdaptiveDailyPlan
from app.learner_model_service import get_personalized_learner_profile
from app.ui.learner_profile_panel import render_us_8_2_reindex_badge
from app.tutor_learner_contract import load_orchestration_state
from app.ui.adaptive_plan_card import get_adaptive_daily_plan, get_primary_plan_block, launch_tutor_for_plan_block

_EMO_FOR_ES = {
    "frustrated": "😫",
    "bored": "😐",
    "engaged": "🔥",
    "confident": "✨",
    "neutral": "😌",
}

_COLOR_FOR_ES = {
    "frustrated": "#ff4d4d",
    "bored": "#ffa500",
    "engaged": "#00cc66",
    "confident": "#3399ff",
    "neutral": "#888888",
}

# US-4.2 / E14-A: короткие русские подписи для полей оркестрации (без сырого snake_case в UI).
_TUTOR_PHASE_LABEL_RU: dict[str, str] = {
    "orchestrate": "выбор действия",
    "rag_prepare": "подбор контекста",
    "pre_generate": "перед ответом",
    "pedagogical_route": "педагогический маршрут",
}

_TUTOR_DECISION_SOURCE_LABEL_RU: dict[str, str] = {
    "llm": "модель",
    "rule": "правило",
    "rule_fallback": "запасное правило",
    "disabled": "выключено",
    "skipped_no_learner_profile": "без профиля обучающегося",
}

_TUTOR_AGENT_TITLE_RU: dict[str, str] = {
    "ConceptExplainer": "📖 Объясняю",
    "SocraticQuestioner": "🤔 Задаю вопросы",
    "ErrorDiagnoser": "🔍 Разбираю ошибку",
    "MicroQuizGenerator": "✅ Проверяю",
    "MotivationCoach": "💪 Поддерживаю",
}

_POLICY_CLAMP_REASON_LABEL_RU: dict[str, str] = {
    "due_review_forced_microquiz": "пора повторить (интервальное повторение)",
    "due_review_overrides_motivation_agent": "сейчас важнее повторение, чем мотивация",
    "homework_prefers_socratic_scaffold": "домашнее задание — лучше через наводящие вопросы",
    "weak_concepts_require_diagnosis": "есть слабые места — сначала разбор",
    # E11-R intent clamps (read-only labels; источник — tutor_personalization_policy)
    "intent_explicit_quiz_logic_error_diagnosis": "разбор логики после квиза",
    "intent_sm2_repeat_topic_command": "команда «повтори тему» (интервальное повторение)",
    "intent_post_explanation_why_question": "вопрос «почему» после объяснения",
    "intent_quiz_failure_recovery_meta_choice": "выбор следующего шага после неудачного квиза",
    "intent_long_session_consolidation_branch": "длинная сессия — закрепление объяснением",
    "intent_cold_start_mechanism_active_recall": "первый вопрос: сначала проверка вспоминания",
    "intent_anti_overhelp_solve_for_me": "анти-списывание: наводящие вопросы вместо готового ответа",
    "intent_counterfactual_challenge": "контрфакт / «что если»",
    "intent_implications_elicit_not_lecture": "последствия и выводы — через вопросы",
    "intent_explicit_drill_or_self_check": "явная самопроверка / короткий drill",
    "intent_misconception_signal": "похоже на заблуждение — разбираем аккуратно",
}


def _tutor_phase_label_ru(raw: str) -> str:
    k = str(raw or "").strip()
    if not k:
        return ""
    return _TUTOR_PHASE_LABEL_RU.get(k, k.replace("_", " ").strip())


def _tutor_decision_source_label_ru(raw: str) -> str:
    k = str(raw or "").strip()
    if not k:
        return ""
    return _TUTOR_DECISION_SOURCE_LABEL_RU.get(k, k.replace("_", " ").strip())


def _humanize_unknown_code(raw: str) -> str:
    """Неизвестный код: убираем snake_case, оставляем читаемую строку."""
    s = str(raw or "").strip()
    if not s:
        return ""
    return " ".join(s.replace("_", " ").split())


def policy_clamp_reason_label_ru(reason: str) -> str:
    """Короткая подпись причины policy clamp; для неизвестных — без snake_case."""
    r = str(reason or "").strip()
    if not r:
        return ""
    if r in _POLICY_CLAMP_REASON_LABEL_RU:
        return _POLICY_CLAMP_REASON_LABEL_RU[r]
    return _humanize_unknown_code(r)


def format_policy_clamp_reasons_ru(reasons: list[str] | None) -> str:
    """Склеивает причины clamp для подписей (через запятую)."""
    if not reasons:
        return ""
    bits = [policy_clamp_reason_label_ru(x) for x in reasons if str(x).strip()]
    return ", ".join(b for b in bits if b)


def _tutor_agent_title_ru(agent: str, phase_fallback: str) -> tuple[str, str]:
    """Заголовок бейджа и базовое пояснение по роли агента."""
    ag = str(agent or "").strip()
    titles = _TUTOR_AGENT_TITLE_RU
    bodies: dict[str, str] = {
        "ConceptExplainer": (
            "Тьютор объясняет концепт: уровень mastery пока недостаточен для проверки."
        ),
        "SocraticQuestioner": (
            "Тьютор ведёт через наводящие вопросы (метод Сократа), чтобы вы сами пришли к выводу."
        ),
        "ErrorDiagnoser": (
            "Тьютор разбирает ошибку, чтобы найти заблуждение и помочь его исправить."
        ),
        "MicroQuizGenerator": ("Тьютор проверяет понимание через короткий микро-квиз."),
        "MotivationCoach": ("Тьютор поддерживает и помогает не бросать обучение."),
    }
    if ag in titles:
        return titles[ag], bodies[ag]
    ph = str(phase_fallback or "").strip()
    if ph:
        pl = _tutor_phase_label_ru(ph)
        return "🎓 Шаг тьютора", f"Тьютор выполняет этап: {pl}."
    return "🎓 Шаг тьютора", "Тьютор продолжает диалог по выбранному маршруту."


def _resolve_user_id(explicit: str | None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return str(st.session_state.get("user_id") or "local").strip() or "local"


def render_tutor_orchestration_snapshot_expander(
    *,
    key_prefix: str,
    show_focus_concept: bool = False,
) -> None:
    """Expander: KV-снимок оркестрации + опционально current_concept + переход в чат тьютора."""
    # Локальный импорт: избегаем циклов при загрузке модуля (Streamlit / query_tab).
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    with st.expander("Оркестрация тьютора (снимок)", expanded=False):
        snap = load_orchestration_state()
        orch = format_stored_orchestration_caption(snap)
        if orch:
            st.caption(orch)
        else:
            st.caption(
                "Снимок появится после ответа в режиме tutor на вкладке «Чат с тьютором» "
                "(фаза пайплайна, источник решения, агент)."
            )
        if show_focus_concept and isinstance(snap, dict):
            cc = str(snap.get("current_concept") or "").strip()
            if cc and cc not in ("", "general"):
                st.caption(f"Фокус тьютора (концепт): **{cc}**")
        b_orch, _ = st.columns([1, 2])
        with b_orch:
            if st.button(
                "Открыть чат с тьютором",
                key=f"{key_prefix}_goto_tutor",
                type="secondary",
            ):
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
                st.rerun()


def format_stored_orchestration_caption(snap: dict[str, Any] | None) -> str | None:
    """Одна строка для dashboard из KV ``tutor_orchestration_state_v1`` (read-only, без orchestration core)."""
    if not isinstance(snap, dict):
        return None
    pipe_raw = snap.get("tutor_orchestration_pipeline")
    pipe = pipe_raw if isinstance(pipe_raw, dict) else {}
    ph = ds = ag = ""
    ph = str(pipe.get("phase") or "").strip()
    ds = str(pipe.get("decision_source") or "").strip()
    ag = str(pipe.get("selected_agent") or "").strip()
    if not ph:
        ph = str(snap.get("orchestration_phase") or "").strip()
    if not ds:
        ds = str(snap.get("orchestration_decision_source") or "").strip()
    if not ag:
        ag = str(snap.get("selected_agent") or "").strip()
    if "should_trigger_microquiz" in pipe:
        microquiz = bool(pipe.get("should_trigger_microquiz"))
    elif "should_trigger_microquiz" in snap:
        microquiz = bool(snap.get("should_trigger_microquiz"))
    else:
        microquiz = None
    if "policy_clamped" in pipe:
        policy_clamped = bool(pipe.get("policy_clamped"))
    elif "policy_clamped" in snap:
        policy_clamped = bool(snap.get("policy_clamped"))
    else:
        policy_clamped = None
    raw_reasons = pipe.get("policy_clamp_reasons")
    if not isinstance(raw_reasons, list):
        raw_reasons = snap.get("policy_clamp_reasons")
    clamp_reasons = (
        format_policy_clamp_reasons_ru([str(x).strip() for x in raw_reasons if str(x).strip()])
        if isinstance(raw_reasons, list)
        else ""
    )
    rec = str(snap.get("recommended_action") or "").strip()
    if not ph and not ds and not ag and not rec and microquiz is None and not policy_clamped:
        return None
    parts: list[str] = []
    if ph:
        parts.append(f"фаза: {_tutor_phase_label_ru(ph)}")
    if ds:
        parts.append(f"источник решения: {_tutor_decision_source_label_ru(ds)}")
    if ag:
        short = _TUTOR_AGENT_TITLE_RU.get(ag, ag.replace("_", " "))
        parts.append(f"роль: {short}")
    if rec:
        parts.append(f"след. шаг: {rec[:96]}")
    if microquiz is not None:
        parts.append("микро-квиз: да" if microquiz else "микро-квиз: нет")
    if policy_clamped:
        parts.append(f"политика: {clamp_reasons}" if clamp_reasons else "политика скорректировала шаг")
    return "Последний снимок тьютора: " + " · ".join(parts)


def tutor_orchestration_decision_one_liner(snap: dict[str, Any] | None) -> str | None:
    """E9.6 / US-4.2: компактно фаза · источник решения · clamp (без expander)."""
    if not isinstance(snap, dict):
        return None
    pipe_raw = snap.get("tutor_orchestration_pipeline")
    pipe = pipe_raw if isinstance(pipe_raw, dict) else {}
    ph = str(pipe.get("phase") or snap.get("orchestration_phase") or "").strip()
    ds = str(pipe.get("decision_source") or snap.get("orchestration_decision_source") or "").strip()
    if "policy_clamped" in pipe:
        policy_clamped = bool(pipe.get("policy_clamped"))
    elif "policy_clamped" in snap:
        policy_clamped = bool(snap.get("policy_clamped"))
    else:
        policy_clamped = False
    raw_reasons = pipe.get("policy_clamp_reasons")
    if not isinstance(raw_reasons, list):
        raw_reasons = snap.get("policy_clamp_reasons")
    clamp_bits = (
        format_policy_clamp_reasons_ru([str(x).strip() for x in raw_reasons if str(x).strip()])
        if isinstance(raw_reasons, list)
        else ""
    )
    parts: list[str] = []
    if ph:
        parts.append(f"Фаза: {_tutor_phase_label_ru(ph)}")
    if ds:
        parts.append(f"Решение: {_tutor_decision_source_label_ru(ds)}")
    if policy_clamped:
        parts.append(f"Политика: {clamp_bits}" if clamp_bits else "Политика скорректировала шаг")
    if not parts:
        return None
    return "Оркестратор · " + " · ".join(parts)


def render_tutor_transparency_badge() -> None:
    """Compact always-visible badge explaining what the tutor is doing and why (US-4.2)."""
    snap = load_orchestration_state()
    if not isinstance(snap, dict):
        return

    pipe = snap.get("tutor_orchestration_pipeline")
    pipe = pipe if isinstance(pipe, dict) else {}

    agent = str(pipe.get("selected_agent") or snap.get("selected_agent") or "").strip()
    phase = str(pipe.get("phase") or snap.get("orchestration_phase") or "").strip()
    ds = str(pipe.get("decision_source") or snap.get("orchestration_decision_source") or "").strip()
    if "should_trigger_microquiz" in pipe:
        microquiz = bool(pipe.get("should_trigger_microquiz"))
    elif "should_trigger_microquiz" in snap:
        microquiz = bool(snap.get("should_trigger_microquiz"))
    else:
        microquiz = None

    policy_clamped = bool(pipe.get("policy_clamped") or snap.get("policy_clamped"))
    raw_reasons = pipe.get("policy_clamp_reasons")
    if not isinstance(raw_reasons, list):
        raw_reasons = snap.get("policy_clamp_reasons")
    clamp_reasons = [str(x).strip() for x in (raw_reasons or []) if str(x).strip()]

    if not agent and not phase:
        return

    label, description = _tutor_agent_title_ru(agent, phase)

    meta_bits: list[str] = []
    if phase:
        meta_bits.append(_tutor_phase_label_ru(phase))
    if ds:
        meta_bits.append(f"источник: {_tutor_decision_source_label_ru(ds)}")
    if microquiz is not None:
        meta_bits.append("микро-квиз: да" if microquiz else "микро-квиз: нет")
    meta_line = " · ".join(meta_bits)

    policy_bits: list[str] = []
    if policy_clamped:
        friendly = format_policy_clamp_reasons_ru(clamp_reasons)
        if friendly:
            policy_bits.append(f"Политика персонализации уточнила шаг: {friendly}.")
        else:
            policy_bits.append("Сработала политика персонализации (коррекция следующего шага).")

    rec_action = str(snap.get("recommended_action") or "").strip()
    if rec_action:
        policy_bits.append(f"Следующий шаг: {rec_action[:220]}")

    desc_parts: list[str] = [description]
    desc_parts.extend(policy_bits)
    full_description = " ".join(desc_parts)

    title_html = f"<strong>{html.escape(label)}</strong>"
    if meta_line:
        title_html += f'<br/><span style="opacity:0.88;font-size:0.84rem;">{html.escape(meta_line)}</span>'

    st.markdown(
        f'<div style="background:var(--secondary-background-color,#f0f2f6);'
        f'border-left:4px solid #4A90D9;padding:0.6rem 1rem;border-radius:0 8px 8px 0;'
        f'margin-bottom:0.8rem;font-size:0.9rem;">'
        f"{title_html}<br/>"
        f'<span style="opacity:0.75;font-size:0.82rem;">{html.escape(full_description)}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_learner_profile_migration_badge(*, user_id: str | None = None) -> None:
    """Заметки о migration профиля: US-8.2 rehydrate — через learner_profile_panel; иначе — смена индекса без rehydrate из истории."""
    try:
        uid = _resolve_user_id(user_id)
        profile = get_personalized_learner_profile(uid, session_id=None)
        sm = getattr(profile, "state_migration", None)
        ix = getattr(profile, "index_context", None)
        if not isinstance(sm, dict):
            return
        if sm.get("history_rehydrated") is True:
            render_us_8_2_reindex_badge(
                state_migration=sm,
                index_context=ix if isinstance(ix, dict) else None,
            )
            return
        if sm.get("index_changed") is True:
            src = sm.get("source_generation_id")
            cur = sm.get("current_generation_id")
            if src and cur and str(src) != str(cur):
                st.info(
                    f"Индекс обновился — mastery сопоставлен с текущим графом (**{src}** → **{cur}**).",
                    icon="📎",
                )
            else:
                st.info(
                    "Индекс или generation изменились — вектор mastery приведён к актуальному покрытию графа.",
                    icon="📎",
                )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return


def render_tutor_mastery_forecast_panel(user_id: str | None = None) -> None:
    """
    Emotional state (PLM 19.5), XP forecast из Adaptive Daily Plan, граф XP за 7 дней, быстрые действия.
    Навигация через ``st.session_state["current_view"]`` (без ``st.switch_page``).
    """
    # Локальный импорт: избегаем циклов при загрузке модуля (Streamlit / query_tab).
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    uid = _resolve_user_id(user_id)
    sid = str(st.session_state.get("tutor_session_id") or "").strip() or None

    try:
        profile = get_personalized_learner_profile(uid, session_id=sid)
        plan = get_adaptive_daily_plan(uid)
    except Exception as e:  # noqa: BLE001 - robust UI load, report profile/plan load errors
        st.warning(f"Не удалось загрузить профиль / план: {e}")
        return

    es = str(profile.emotional_state)
    emo = _EMO_FOR_ES.get(es, "😌")
    emo_color = _COLOR_FOR_ES.get(es, "#888888")

    st.markdown(
        f"""
        <div style="background:{emo_color}22;padding:1rem 1.1rem;border-radius:16px;border:1px solid rgba(19,32,25,0.1);text-align:center;margin-bottom:0.75rem;">
            <div style="font-size:1.6rem;margin-bottom:0.2rem;">{emo}</div>
            <div style="font-weight:800;font-size:1.05rem;color:{emo_color};letter-spacing:0.04em;">{es.upper()}</div>
            <div style="opacity:0.9;font-size:0.88rem;margin-top:0.35rem;">
                Confidence <b>{float(profile.confidence_indicator):.0%}</b>
                · Load <b>{float(profile.cognitive_load):.0%}</b>
                · Velocity <b>{float(profile.learning_velocity):.2f}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    goal = int(plan.get("total_xp_goal") or 0)
    daily = int(get_daily_xp(uid))
    total = int(get_total_xp(uid))
    remaining = max(0, goal - daily)

    lv = float(profile.learning_velocity)
    session_fc = int(max(1, min(goal or 9999, round(goal * (lv + 0.3))))) if goal else int(max(1, round(50 * (lv + 0.3))))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Всего XP", f"{total}", help="Суммарный опыт (геймификация)")
    with c2:
        st.metric("Цель XP сегодня", f"{goal} XP", delta=f"собрано {daily} · осталось {remaining}")
    with c3:
        st.metric("Прогноз за сессию", f"~{session_fc} XP", delta=f"velocity {lv:.2f}")

    orch_cap = format_stored_orchestration_caption(load_orchestration_state())
    if orch_cap:
        st.caption(orch_cap)

    hist = get_xp_history(uid, days=7)
    if hist and any(int(r.get("xp") or 0) > 0 for r in hist):
        try:
            import pandas as pd
            import plotly.express as px
        except ImportError as e:
            st.caption(f"График XP недоступен (pandas/plotly): {e}")
        else:
            df = pd.DataFrame(hist)
            fig = px.line(
                df,
                x="date",
                y="xp",
                markers=True,
                title="XP за последние 7 дней (UTC)",
            )
            fig.update_layout(
                margin=dict(l=8, r=8, t=40, b=8),
                height=280,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(255,255,255,0.5)",
            )
            st.plotly_chart(fig, width='stretch')
    else:
        st.caption("Пока мало данных для графика XP — выполни quiz или блоки плана.")

    st.divider()
    b1, b2, b3 = st.columns(3)
    primary = get_primary_plan_block(list(plan.get("blocks") or []))
    with b1:
        if primary is not None and st.button("🎯 Следующий шаг плана", key="tm_adp_chat", width='stretch'):
            launch_tutor_for_plan_block(primary[1], action_label="Adaptive Daily Plan")
    with b2:
        if st.button("🔄 Пересчитать план", key="tm_adp_rebuild", width='stretch'):
            try:
                AdaptiveDailyPlan(uid, session_id=sid).build_adaptive_daily_plan()
                st.success("План обновлён.")
                st.rerun()
            except Exception as ex:  # noqa: BLE001 - robust UI action, report plan rebuild error
                st.error(str(ex))
    with b3:
        if st.button("🕸 Граф знаний", key="tm_kg", width='stretch'):
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Knowledge Graph"
            st.rerun()

    if es == "frustrated":
        st.warning("💡 Рекомендация: короткий шаг с MotivationCoach и один micro-quiz — без перегруза.")
    elif es == "bored":
        st.info("💡 Чередуй форматы: новый концепт из плана или transfer-вопрос.")
    elif lv > 0.18:
        st.success("🔥 Хороший темп — можно брать чуть более сложные шаги из плана.")


__all__ = [
    "format_policy_clamp_reasons_ru",
    "format_stored_orchestration_caption",
    "policy_clamp_reason_label_ru",
    "render_learner_profile_migration_badge",
    "render_tutor_mastery_forecast_panel",
    "render_tutor_orchestration_snapshot_expander",
    "render_tutor_transparency_badge",
    "tutor_orchestration_decision_one_liner",
]
