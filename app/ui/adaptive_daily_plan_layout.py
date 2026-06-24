"""Adaptive Daily Plan full-card renderer."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.gamification_service import award_xp_for_block, get_snapshot
from app.learning_plan_service import AdaptiveDailyPlan, get_adaptive_daily_plan_history
from app.ui.continuity_bridge import adaptive_plan_expert_controls_intro_ru
from app.ui.expert_controls import render_expert_controls, render_expert_metric_row
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY


def build_adaptive_plan_redacted_debug(plan: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        bt = str(raw.get("type") or "step").strip() or "step"
        type_counts[bt] = type_counts.get(bt, 0) + 1
    cg = plan.get("concept_graduation")
    cg_n = len(cg) if isinstance(cg, dict) else 0
    seed = str(plan.get("seed_topic") or "").strip()
    return {
        "date": plan.get("date"),
        "seed_topic_redacted": (seed[:48] + ("…" if len(seed) > 48 else "")) if seed else "",
        "new_reviews_balance": plan.get("new_reviews_balance"),
        "learner_model": plan.get("learner_model"),
        "entry_state": plan.get("entry_state"),
        "primary_block": plan.get("primary_block"),
        "block_type_counts": type_counts,
        "concept_graduation_signals": cg_n,
    }


def compact_plan_history_for_expert(
    entries: list[dict[str, Any]] | None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in (entries or [])[:limit]:
        if not isinstance(raw, dict):
            continue
        concepts = raw.get("main_concepts")
        mc = list(concepts)[:5] if isinstance(concepts, list) else []
        out.append(
            {
                "date": raw.get("date"),
                "archived_at": raw.get("archived_at"),
                "focus_review_gap_new": raw.get("focus_review_gap_new"),
                "main_concepts": mc,
                "total_xp_goal": raw.get("total_xp_goal"),
                "motivation_excerpt": (str(raw.get("motivation_excerpt") or "").strip()[:120] or None),
            }
        )
    return out


def learner_profile_snapshot_redacted() -> dict[str, Any]:
    try:
        snap = get_snapshot()
    except Exception as exc:  # noqa: BLE001 - snapshot optional in expert panel
        return {"available": False, "error": str(exc)[:80]}
    if not isinstance(snap, dict):
        return {"available": False}
    return {
        "available": True,
        "level": snap.get("level"),
        "level_title": snap.get("level_title"),
        "daily_streak": snap.get("daily_streak"),
        "blocks_completed_today": snap.get("blocks_completed_today"),
        "daily_xp_today": snap.get("daily_xp_today"),
    }


def adaptive_plan_trust_summary(plan: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a compact explanation of why the current daily plan is ordered this way."""
    counts: dict[str, int] = {}
    total_duration = 0
    total_xp = 0
    mastery_values: list[float] = []
    concepts: list[str] = []
    for block in blocks:
        bt = str(block.get("type") or "step").strip() or "step"
        counts[bt] = counts.get(bt, 0) + 1
        try:
            total_duration += int(block.get("duration_min") or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_xp += int(block.get("xp_base") or 0)
        except (TypeError, ValueError):
            pass
        try:
            mastery_values.append(float(block["current_mastery"]))
        except (KeyError, TypeError, ValueError):
            pass
        concept = str(block.get("concept") or "").strip()
        if concept and concept.lower() not in {"general", "auto", "qa", "neutral"}:
            concepts.append(concept)

    first = blocks[0] if blocks else {}
    first_type = str(first.get("type") or "step").strip() or "step"
    first_concept = str(first.get("concept") or "").strip()
    first_label = first_type if not first_concept else f"{first_type}: {first_concept}"
    avg_mastery = sum(mastery_values) / len(mastery_values) if mastery_values else None
    balance = str(plan.get("new_reviews_balance") or "").strip()
    seed_topic = str(plan.get("seed_topic") or "").strip()
    signals = [
        f"первый шаг: {first_label}",
        f"баланс: {balance}" if balance else "",
        f"seed: {seed_topic}" if seed_topic else "",
        "концепты: " + ", ".join(dict.fromkeys(concepts[:5])) if concepts else "",
    ]
    if avg_mastery is not None:
        signals.append(f"средний mastery gap: {avg_mastery:.0%}")
    return {
        "counts": counts,
        "total_duration": total_duration,
        "total_xp": total_xp,
        "avg_mastery": avg_mastery,
        "signals": [item for item in signals if item],
    }


def _render_adaptive_plan_trust_block(plan: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    summary = adaptive_plan_trust_summary(plan, blocks)
    counts = summary["counts"]
    review_count = int(counts.get("review", 0))
    gap_count = int(counts.get("gap", 0))
    new_count = int(counts.get("new", 0))
    with st.expander("Почему такой порядок", expanded=False):
        st.caption(
            "Короткое объяснение маршрута без экспертных настроек: план сначала закрывает срочные повторы, "
            "затем пробелы и только после этого добавляет новые темы."
        )
        render_expert_metric_row(
            (
                ("Review", str(review_count), "повторы"),
                ("Gap", str(gap_count), "пробелы"),
                ("New", str(new_count), "новые темы"),
                ("Время", f"{summary['total_duration']} мин", "оценка"),
            )
        )
        for signal in summary["signals"]:
            st.caption(signal)
        st.caption(
            "Безопасные действия: пересчитать план, открыть первый блок в чате, перейти к очереди повторений "
            "или прогрессу. Ручные веса планировщика здесь не меняются."
        )


def _render_adaptive_plan_expert_layer(plan: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    summary = adaptive_plan_trust_summary(plan, blocks)
    counts = summary["counts"] or {}
    balance = str(plan.get("new_reviews_balance") or "").strip()
    entry = str(plan.get("entry_state") or "—")
    prof = learner_profile_snapshot_redacted()
    hist_compact = compact_plan_history_for_expert(get_adaptive_daily_plan_history(), limit=3)
    pb = plan.get("primary_block")
    pb_line = "—"
    if isinstance(pb, dict):
        pb_line = f"{pb.get('type') or '—'} / {pb.get('concept') or '—'}"

    if prof.get("available"):
        prof_signal = (
            f"Lv{prof.get('level')} {prof.get('level_title')} · streak {prof.get('daily_streak')} · "
            f"блоков сегодня {prof.get('blocks_completed_today')} · XP сегодня {prof.get('daily_xp_today')}"
        )
    else:
        prof_signal = "профиль геймификации недоступен в этом контексте"

    payload = {
        "plan_redacted": build_adaptive_plan_redacted_debug(plan, blocks),
        "recent_plan_snapshots": hist_compact,
    }
    signals = [
        f"seed: {str(plan.get('seed_topic') or '')[:72]}",
        f"learner_model: {plan.get('learner_model')}",
        f"primary: {pb_line}",
        f"профиль: {prof_signal}",
    ]
    render_expert_controls(
        intro=adaptive_plan_expert_controls_intro_ru(),
        metrics=(
            ("Баланс R/G/N", balance or "—", "из планировщика"),
            ("В маршруте", f"{counts.get('review', 0)}/{counts.get('gap', 0)}/{counts.get('new', 0)}", "review/gap/new"),
            ("Сессия (мин)", str(plan.get("recommended_session_length_min") or "—"), "рекомендация"),
            ("XP цель", str(plan.get("total_xp_goal") or "—"), "день"),
            ("Вход", entry, "entry_state"),
        ),
        signals=signals,
        safe_actions=(
            "Пересчёт плана выполняйте кнопкой карточки — запись в KV обновится атомарно.",
            "История снимков ограничена тремя последними версиями без полного JSON.",
        ),
        raw_debug_label="План (redacted) + компактная история",
        raw_debug_payload=payload,
    )


def render_adaptive_daily_plan(
    user_id: str | None = None,
    *,
    show_buttons: bool = True,
    compact: bool = False,
    key_prefix: str = "adp",
    plan_override: dict[str, Any] | None = None,
    show_json_expander: bool = False,
) -> None:
    from app.ui import adaptive_plan_card as _card

    """
    Карточка Adaptive Daily Plan. Навигация — через ``current_view`` и ``tutor_pending_prompt``,
    как в ``resume_cards.py`` (без ``st.switch_page``).
    """
    uid = _card._session_user_id(user_id)
    toast_key = f"{key_prefix}_xp_toast"
    toast = st.session_state.pop(toast_key, None)
    if toast:
        st.success(toast)
        st.balloons()

    try:
        plan = _card.get_adaptive_daily_plan(uid, plan_override=plan_override)
    except Exception as e:  # noqa: BLE001 - Streamlit plan loading fallback must render an error state.
        st.error(f"Не удалось загрузить план: {e}")
        return

    blocks = list(plan.get("blocks") or [])
    head_cls = "home-dash-head home-dash-head-continue"

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    if compact:
        st.markdown(
            f'<div class="{head_cls}"><h4 style="margin:0;">🎯 Adaptive Daily Plan</h4>'
            f'<span style="opacity:0.9;font-size:0.85rem;"> · {plan.get("date", "—")}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="{head_cls}"><h3>🎯 Adaptive Daily Plan</h3></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    cap_lead = "" if compact else f"Дата: **{plan.get('date', '—')}** · "
    st.caption(
        f"{cap_lead}"
        f"Рекомендуемая сессия: **{plan.get('recommended_session_length_min', '—')}** мин · "
        f"цель XP: **{plan.get('total_xp_goal', '—')}**"
    )
    mot = plan.get("motivation_message")
    if mot:
        if compact:
            st.caption(str(mot))
        else:
            st.info(str(mot))

    if not compact:
        _render_adaptive_plan_trust_block(plan, blocks)
        _render_adaptive_plan_expert_layer(plan, blocks)

    if not compact:
        _card.render_plan_concepts_delta_ui(plan)
        _card.render_recent_adaptive_plan_history()

    denom = max(len(blocks), 6, 1)
    if show_buttons:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.progress(min(1.0, len(blocks) / denom))
        with col2:
            if st.button(
                "🔄 Пересчитать",
                key=f"{key_prefix}_rebuild",
                width='stretch',
            ):
                try:
                    AdaptiveDailyPlan(uid, session_id=_card._tutor_session_id()).build_adaptive_daily_plan()
                    st.success("План обновлён.")
                    st.rerun()
                except Exception as ex:  # noqa: BLE001 - completion fallback must keep the plan card usable.
                    st.error(str(ex))
    else:
        st.progress(min(1.0, len(blocks) / denom))

    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            continue
        bt = str(raw.get("type") or "").strip()
        title = _card._BLOCK_LABEL.get(bt, bt or "шаг")
        subtitle = _card._block_concept_line(raw)
        exp_label = f"**{i + 1}. {title.upper()}** — {subtitle}" if subtitle else f"**{i + 1}. {title.upper()}**"
        expanded = (i == 0) and (not compact)
        with st.expander(exp_label, expanded=expanded):
            xpb = raw.get("xp_base")
            xpd = raw.get("xp_multiplier_description")
            if xpb is not None:
                st.caption(f"База XP блока: **{xpb}** · {xpd or 'множители: velocity, streak, gap, fast'}")
            c0, c1, c2 = st.columns([3, 1, 1])
            with c0:
                st.caption(f"Агент: **{_card._block_agent(raw)}**")
                st.caption(f"⏱ ~{raw.get('duration_min', 5)} мин")
                cm = raw.get("current_mastery")
                if cm is not None:
                    try:
                        st.metric("Mastery", f"{float(cm):.0%}")
                    except (TypeError, ValueError):
                        pass
            with c1:
                if show_buttons and st.button("▶️ В чат", key=f"{key_prefix}_chat_{i}", width='stretch'):
                    _card.launch_tutor_for_plan_block(raw)
            with c2:
                if show_buttons and st.button(
                    "✅ Завершить",
                    key=f"{key_prefix}_complete_{i}",
                    type="primary",
                    width='stretch',
                ):
                    try:
                        result = award_xp_for_block(
                            uid,
                            raw,
                            completion_time_min=5,
                            block_index=i,
                            plan_date=str(plan.get("date") or ""),
                            session_id=_card._tutor_session_id(),
                        )
                        if result.get("already_awarded"):
                            st.warning(result.get("message") or "Уже засчитано.")
                        else:
                            st.session_state[toast_key] = result.get("message") or f"+{result.get('xp_earned', 0)} XP"
                            st.rerun()
                    except Exception as ex:  # noqa: BLE001 - XP award fallback must keep the plan card usable.
                        st.error(str(ex))

    if show_buttons and not compact:
        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📚 Очередь повторений", key=f"{key_prefix}_due", width='stretch'):
                _card._ensure_tutor_session()
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
                st.session_state["tutor_pending_prompt"] = (
                    "Покажи мои темы в очереди повторений и с чего начать."
                )
                st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
                st.session_state["tutor_cta_action"] = "Due reviews"
                st.rerun()
        with c2:
            if st.button("🕸 Граф знаний", key=f"{key_prefix}_kg", width='stretch'):
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Knowledge Graph"
                st.rerun()
        with c3:
            if st.button("📊 Мой прогресс", key=f"{key_prefix}_prog", width='stretch'):
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
                st.rerun()

    if show_json_expander:
        with st.expander("Полный JSON плана", expanded=False):
            st.json(plan)

    st.markdown("</div></div>", unsafe_allow_html=True)
