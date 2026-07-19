"""Smart Study Router helpers for home resume cards."""
from __future__ import annotations

import html as html_stdlib
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import streamlit as st

from app import user_state
from app.knowledge_service import get_active_knowledge_graph
from app.learner_state_scope import count_due_reviews_for_kg
from app.ui.adaptive_plan_card import (
    apply_smart_study_steering_preference,
    build_smart_study_evidence_ledger_lines,
    build_smart_study_recommendation,
    render_smart_study_next_step_card,
)
from app.ui.tutor_chat_render import (
    apply_smart_study_defer_from_session,
    apply_source_trust_smart_study_overlay,
    render_smart_study_trust_controls,
)
from app.ui.index_labels import index_version_label

_SMART_STUDY_SSR_SURFACE = Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"]

# US-20.11: local before/after check after Smart Study Router navigation.
_SSR_OUTCOME_BASELINE_KEY = "ssr_outcome_baseline_v1"
_SSR_OUTCOME_BASELINE_TTL_SEC = 600.0
_SSR_OUTCOME_SEEN_BASELINE_ID_KEY = "ssr_outcome_seen_baseline_id_v1"
_SSR_NAV_HOOKS_INSTALLED = False

# US-20.12: quiet visual mode preference for SSR cards.
_SSR_QUIET_PREF_KEY = "ssr_quiet_display_v1"

from app.ui.resume_cards_recovery_ladder import (  # noqa: E402
    ConceptRecoveryLadderResolved,
    advance_concept_recovery_ladder_after_primary,
    advance_concept_recovery_ladder_after_secondary,
    ensure_concept_recovery_ladder_enabled_in_session,
    ladder_kwargs_for_build,
    maybe_clear_concept_recovery_ladder_on_variant_quiz_success,
    persist_resolved_ladder_context,
    remember_ssr_primary_nav,
    render_concept_recovery_ladder_status_ui,
    resolve_concept_recovery_ladder_context,
    seed_concept_recovery_ladder_on_quiz_failed,
)


def _ssr_quiet_pref_enabled() -> bool:
    return bool(st.session_state.get(_SSR_QUIET_PREF_KEY, False))


def _ssr_quiet_stylesheet_markup() -> str:
    """Подмешивает стиль к explainable SSR без изменения деревьев кнопок (US-20.12)."""
    return """<style>
[data-testid="e2e-smart-study-next-step"] {
  border: 1px solid rgba(148, 163, 184, 0.28) !important;
  box-shadow: none !important;
}
[data-testid="e2e-smart-study-next-step"] .home-dash-head.home-dash-head-continue {
  background-image: none !important;
  background-color: transparent !important;
  padding-top: 0.35rem !important;
  padding-bottom: 0.35rem !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.35);
}
[data-testid="e2e-smart-study-next-step"] .home-dash-head.home-dash-head-continue h4 {
  font-weight: 600 !important;
  font-size: 1.02rem !important;
  letter-spacing: 0.01em;
}
[data-testid="e2e-smart-study-next-step"] .home-dash-body strong {
  font-weight: 600;
}
[data-testid="e2e-smart-study-next-step"] .home-dash-body li {
  line-height: 1.45;
}
</style>"""


def _maybe_emit_ssr_quiet_styles() -> None:
    if not _ssr_quiet_pref_enabled():
        return
    st.markdown(_ssr_quiet_stylesheet_markup(), unsafe_allow_html=True)


def render_ssr_quiet_mode_toggle(*, key_prefix: str) -> None:
    """Чекбокс «тихий режим» с изолированными ключами по surface, синх prefs в общий флаг."""

    safe_pre = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key_prefix)[:40] or "ssr"
    chk_key = f"{safe_pre}_ssr_quiet_cb"
    if chk_key not in st.session_state:
        st.session_state[chk_key] = bool(st.session_state.get(_SSR_QUIET_PREF_KEY, False))
    st.checkbox(
        "Тихий режим карточки с подсказкой",
        key=chk_key,
        help="Меньше визуального шума: главное действие, короткая причина и дополнительные кнопки остаются на месте.",
    )
    st.session_state[_SSR_QUIET_PREF_KEY] = bool(st.session_state.get(chk_key, False))


def _quiz_feedback_status_from_tutor_snap(tutor_snap: dict[str, Any] | None) -> str | None:
    if not tutor_snap:
        return None
    qfx = tutor_snap.get("quiz_feedback")
    if isinstance(qfx, dict):
        return str(qfx.get("status") or "").strip() or None
    return None


def build_ssr_outcome_metric_dict_from_ctx(ctx: SmartStudyRouterSessionContext) -> dict[str, Any]:
    return {
        "fc_due": int(ctx.flashcard_due_n),
        "sm2_due": int(ctx.sm2_due_n),
        "weak_top": ctx.weak_concepts[0] if ctx.weak_concepts else None,
        "quiz_fb": _quiz_feedback_status_from_tutor_snap(ctx.effective_tutor_snap),
    }


def build_ssr_outcome_metric_dict_live() -> dict[str, Any]:
    from app.learner_state_scope import weak_concepts_for_kg

    kg = get_active_knowledge_graph()
    due_n = count_due_reviews_for_kg(kg)
    try:
        fc = int(user_state.count_due_flashcards())
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("ssr outcome live fc_due: %s", _exc)
        fc = 0
    weak: list[str] = []
    try:
        weak = list(weak_concepts_for_kg(kg, threshold=60, limit=12))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("ssr outcome live weak: %s", _exc)
        weak = []
    tutor_snap: dict[str, Any] | None = None
    try:
        tutor_snap = user_state.get_tutor_learning_resume()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("ssr outcome live tutor_snap: %s", _exc)
        tutor_snap = None
    eff = tutor_snap if isinstance(tutor_snap, dict) else None
    return {
        "fc_due": fc,
        "sm2_due": int(due_n),
        "weak_top": weak[0] if weak else None,
        "quiz_fb": _quiz_feedback_status_from_tutor_snap(eff),
    }


def compute_ssr_outcome_receipt_lines(
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[list[str], bool]:
    lines: list[str] = []
    measurable = False
    b_fc = int(before.get("fc_due") or 0)
    a_fc = int(after.get("fc_due") or 0)
    if b_fc != a_fc:
        measurable = True
        lines.append(f"Карточки к повторению: было {b_fc} → стало {a_fc}.")
    b_sm = int(before.get("sm2_due") or 0)
    a_sm = int(after.get("sm2_due") or 0)
    if b_sm != a_sm:
        measurable = True
        lines.append(f"Очередь повторений по графу: было {b_sm} → стало {a_sm}.")
    b_w = before.get("weak_top")
    a_w = after.get("weak_top")
    if b_w != a_w:
        measurable = True
        bw = html_stdlib.escape(str(b_w or "—"))
        aw = html_stdlib.escape(str(a_w or "—"))
        lines.append(f"Верх слабых концептов (квиз): было «{bw}» → «{aw}».")
    b_q = before.get("quiz_fb")
    a_q = after.get("quiz_fb")
    if b_q != a_q:
        measurable = True
        bqs = html_stdlib.escape(str(b_q or "—"))
        aqs = html_stdlib.escape(str(a_q or "—"))
        lines.append(f"Статус мини-quiz в резюме тьютора: было «{bqs}» → «{aqs}».")
    return lines, measurable


def _store_ssr_outcome_baseline_dict(core: dict[str, Any]) -> None:
    payload = dict(core)
    payload["ts"] = time.time()
    payload["baseline_id"] = str(uuid.uuid4())
    st.session_state[_SSR_OUTCOME_BASELINE_KEY] = payload


def store_ssr_outcome_baseline_from_primary_rec(rec: Any) -> None:
    snap = build_ssr_outcome_metric_dict_live()
    snap["nav_lane"] = "primary"
    snap["hint_kind"] = str(getattr(rec, "hint_kind", "") or "")
    snap["primary_nav"] = str(getattr(rec, "primary_nav", "") or "")
    _store_ssr_outcome_baseline_dict(snap)


def store_ssr_outcome_baseline_from_secondary(action_id: str) -> None:
    snap = build_ssr_outcome_metric_dict_live()
    snap["nav_lane"] = "secondary"
    snap["hint_kind"] = ""
    snap["secondary_id"] = str(action_id or "")
    _store_ssr_outcome_baseline_dict(snap)


def _render_ssr_outcome_receipt_if_needed(
    ctx: SmartStudyRouterSessionContext,
    *,
    key_prefix: str,
    emit_outcome_receipt: bool,
) -> None:
    baseline = st.session_state.get(_SSR_OUTCOME_BASELINE_KEY)
    if not isinstance(baseline, dict):
        return
    ts = float(baseline.get("ts") or 0.0)
    if ts and (time.time() - ts) > _SSR_OUTCOME_BASELINE_TTL_SEC:
        st.session_state.pop(_SSR_OUTCOME_BASELINE_KEY, None)
        st.session_state.pop(_SSR_OUTCOME_SEEN_BASELINE_ID_KEY, None)
        return
    if not emit_outcome_receipt:
        return

    after = build_ssr_outcome_metric_dict_from_ctx(ctx)
    lines, measurable = compute_ssr_outcome_receipt_lines(baseline, after)
    bid = str(baseline.get("baseline_id") or "")
    dom_pre = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key_prefix)[:40] or "ssr"

    if measurable:
        items_li = "".join(
            f'<li style="margin:0.12rem 0;">{html_stdlib.escape(line)}</li>' for line in lines
        )
        st.markdown(
            f'<div class="home-dash-card" data-testid="e2e-ssr-outcome-receipt" id="{dom_pre}_outcome_ok" '
            'style="margin-bottom:0.6rem;">'
            '<div class="home-dash-head home-dash-head-continue"><h4 style="margin:0;">✅ Чек после выбранного шага</h4></div>'
            '<div class="home-dash-body"><p style="margin:0 0 0.35rem 0;">Локальные метрики изменились:</p>'
            f'<ul style="margin:0;padding-left:1.2rem;">{items_li}</ul></div></div>',
            unsafe_allow_html=True,
        )
        st.session_state.pop(_SSR_OUTCOME_BASELINE_KEY, None)
        st.session_state.pop(_SSR_OUTCOME_SEEN_BASELINE_ID_KEY, None)
        return

    seen = st.session_state.get(_SSR_OUTCOME_SEEN_BASELINE_ID_KEY)
    if seen != bid:
        st.session_state[_SSR_OUTCOME_SEEN_BASELINE_ID_KEY] = bid
        return

    st.markdown(
        f'<div class="home-dash-card" data-testid="e2e-ssr-outcome-receipt" id="{dom_pre}_outcome_none" '
        'style="margin-bottom:0.6rem;">'
        '<div class="home-dash-head home-dash-head-continue"><h4 style="margin:0;">ℹ️ Честный чек после шага</h4></div>'
        '<div class="home-dash-body"><p style="margin:0;font-size:0.9rem;">По локальным очередям (flashcards, повторения по графу, '
        "верх «слабого» концепта, статус мини-quiz в резюме) измеримого сдвига пока не видно — без фальшивого «прогресса». "
        "Ниже обновлённая подсказка по актуальным метрикам.</p></div></div>",
        unsafe_allow_html=True,
    )
    st.session_state.pop(_SSR_OUTCOME_BASELINE_KEY, None)
    st.session_state.pop(_SSR_OUTCOME_SEEN_BASELINE_ID_KEY, None)


def _install_ssr_outcome_navigation_hooks() -> None:
    global _SSR_NAV_HOOKS_INSTALLED
    if _SSR_NAV_HOOKS_INSTALLED:
        return
    from app.ui import adaptive_plan_card as apc

    _orig_p = apc.apply_smart_study_primary_navigation
    _orig_s = apc.apply_smart_study_secondary_navigation

    def _wrap_p(rec: Any, **kwargs: Any) -> None:
        store_ssr_outcome_baseline_from_primary_rec(rec)
        return _orig_p(rec, **kwargs)

    def _wrap_s(action_id: str, *, topic_hint: str | None = None) -> None:
        store_ssr_outcome_baseline_from_secondary(str(action_id))
        return _orig_s(action_id, topic_hint=topic_hint)

    apc.apply_smart_study_primary_navigation = _wrap_p  # type: ignore[method-assign]
    apc.apply_smart_study_secondary_navigation = _wrap_s  # type: ignore[method-assign]
    _SSR_NAV_HOOKS_INSTALLED = True


def resolve_tutor_resume_for_home(
    tutor_snap: dict[str, Any] | None,
    *,
    current_index_version: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    """Return valid tutor resume for home CTA and stale flag.

    Assumption: stale policy is limited to existing index-version mismatch guard.
    If current index version exists and differs from snapshot version, snapshot is
    considered stale and must not drive resume CTA.
    """
    if not isinstance(tutor_snap, dict):
        return None, False
    snap_iv = str(tutor_snap.get("index_version") or "").strip()
    cur_iv = str(current_index_version or "").strip()
    stale = bool(cur_iv and snap_iv and snap_iv != cur_iv)
    if stale:
        return None, True
    return tutor_snap, False


@dataclass
class SmartStudyRouterSessionContext:
    """Локальный снимок для детерминированного SSR (главная, Progress и др.)."""

    kg: Any
    sm2_due_n: int
    flashcard_due_n: int
    effective_tutor_snap: dict[str, Any] | None
    stale_tutor: bool
    last_answer: Any
    has_last_answer_qa: bool
    latest_resume: dict[str, Any] | None
    has_reading: bool
    weak_concepts: list[str]
    tutor_topic: str | None


def _get_saved_plan_primary_block() -> dict | None:
    """Retrieve the saved adaptive daily plan's primary block (cheap KV read, no regeneration)."""
    try:
        from datetime import datetime

        from app.learning_plan_adaptive import get_saved_adaptive_daily_plan
        from app.ui.adaptive_plan_card import get_primary_plan_block_from_plan

        saved = get_saved_adaptive_daily_plan()
        if not saved:
            return None
        today = datetime.now().date().isoformat()
        if str(saved.get("date") or "") != today:
            return None
        return get_primary_plan_block_from_plan(saved)
    except Exception:  # noqa: BLE001 - best-effort, must not break SSR
        return None


def gather_smart_study_router_session_context(
    *,
    index_stats: dict[str, Any] | None,
    flashcard_due_n: int | None = None,
) -> SmartStudyRouterSessionContext:
    """Снимок очередей/резюме для Smart Study Router (без Streamlit-кнопок).

    Pass ``flashcard_due_n`` when the caller already has the value (e.g. from
    ``flashcards_bootstrap()``) to skip a redundant ``count_due_flashcards()`` DB call.
    """
    from app.learner_state_scope import weak_concepts_for_kg

    kg = get_active_knowledge_graph()
    due_n = count_due_reviews_for_kg(kg)

    tutor_snap: dict[str, Any] | None = None
    try:
        tutor_snap = user_state.get_tutor_learning_resume()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        tutor_snap = None

    last_ans = st.session_state.get("last_answer")
    has_qa = bool(
        isinstance(last_ans, dict)
        and (
            (str(last_ans.get("question") or "").strip())
            or (str(last_ans.get("answer") or "").strip())
        )
    )

    latest_resume: dict[str, Any] | None = None
    try:
        latest_resume = user_state.get_latest_resume()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        latest_resume = None
    has_reading = latest_resume is not None

    weak_concepts: list[str] = []
    try:
        weak_concepts = list(weak_concepts_for_kg(kg, threshold=60, limit=12))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        weak_concepts = []

    if flashcard_due_n is None:
        try:
            flashcard_due_n = int(user_state.count_due_flashcards())
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001

            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            flashcard_due_n = 0

    iv = index_version_label(index_stats)
    effective_tutor_snap, stale_tutor = resolve_tutor_resume_for_home(
        tutor_snap,
        current_index_version=iv,
    )

    tutor_topic = (
        str(effective_tutor_snap.get("topic") or "").strip() if effective_tutor_snap else ""
    ) or None

    return SmartStudyRouterSessionContext(
        kg=kg,
        sm2_due_n=due_n,
        flashcard_due_n=flashcard_due_n,
        effective_tutor_snap=effective_tutor_snap,
        stale_tutor=stale_tutor,
        last_answer=last_ans,
        has_last_answer_qa=has_qa,
        latest_resume=latest_resume,
        has_reading=has_reading,
        weak_concepts=weak_concepts,
        tutor_topic=tutor_topic,
    )


def render_smart_study_router_strip_from_session_context(
    ctx: SmartStudyRouterSessionContext,
    *,
    key_prefix: str,
    surface: _SMART_STUDY_SSR_SURFACE = "home",
    emit_outcome_receipt: bool | None = None,
) -> None:
    _install_ssr_outcome_navigation_hooks()
    if emit_outcome_receipt is None:
        emit_outcome_receipt = key_prefix in ("home_ssr", "progress_ssr")
    _render_ssr_outcome_receipt_if_needed(
        ctx,
        key_prefix=key_prefix,
        emit_outcome_receipt=emit_outcome_receipt,
    )
    render_ssr_quiet_mode_toggle(key_prefix=key_prefix)
    _maybe_emit_ssr_quiet_styles()
    render_concept_recovery_ladder_status_ui()
    qf_status_home: str | None = None
    if ctx.effective_tutor_snap:
        qfx = ctx.effective_tutor_snap.get("quiz_feedback")
        if isinstance(qfx, dict):
            qf_status_home = str(qfx.get("status") or "").strip() or None
    ss_home = build_smart_study_recommendation(
        surface=surface,
        flashcard_due_n=ctx.flashcard_due_n,
        sm2_due_n=ctx.sm2_due_n,
        quiz_feedback_status=qf_status_home,
        has_tutor_resume=bool(ctx.effective_tutor_snap and ctx.tutor_topic),
        tutor_topic=ctx.tutor_topic,
        has_last_answer_qa=ctx.has_last_answer_qa,
        has_reading_resume=ctx.has_reading,
        first_weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
        plan_primary_block=_get_saved_plan_primary_block(),
        **ladder_kwargs_for_build(
            current_anchor=ctx.tutor_topic,
            quiz_feedback_status=qf_status_home,
        ),
    )
    if key_prefix in ("home_ssr", "progress_ssr"):
        try:
            from app.user_state_weekly_narrative import record_ssr_route_impression

            record_ssr_route_impression(
                hint_kind=str(ss_home.hint_kind or ""),
                primary_nav=str(ss_home.primary_nav or ""),
                session_key_prefix=key_prefix,
            )
        except Exception:  # noqa: BLE001 - best-effort impression log; never block SSR card
            pass
    remember_ssr_primary_nav(ss_home.primary_nav)
    last_ans_home = ctx.last_answer if isinstance(ctx.last_answer, dict) else None
    ss_home, trust_ss_home = apply_source_trust_smart_study_overlay(
        ss_home,
        last_answer=last_ans_home,
        tutor_trust=None,
    )
    ss_home, defer_ss_home = apply_smart_study_defer_from_session(ss_home)
    sid_for_ssr = ""
    if ctx.effective_tutor_snap:
        sid_for_ssr = str(ctx.effective_tutor_snap.get("session_id") or "").strip()
    qa_topic_hint: str | None = None
    if isinstance(ctx.last_answer, dict) and ctx.has_last_answer_qa:
        qa_topic_hint = str(ctx.last_answer.get("question") or "").strip() or None
    steer_tag = user_state.get_smart_study_steering_preference()
    ss_steered, _ = apply_smart_study_steering_preference(
        ss_home,
        steering=steer_tag,
        has_last_answer_qa=ctx.has_last_answer_qa,
        defer_was_applied=defer_ss_home,
    )
    ssr_evidence = build_smart_study_evidence_ledger_lines(
        flashcard_due_n=ctx.flashcard_due_n,
        sm2_due_n=ctx.sm2_due_n,
        quiz_feedback_status=qf_status_home,
        has_last_answer_qa=ctx.has_last_answer_qa,
        last_answer=last_ans_home,
        tutor_trust=None,
        defer_applied=defer_ss_home,
        trust_branch_applied=trust_ss_home,
        steering_local=steer_tag or None,
        include_all=False,
    )
    render_smart_study_next_step_card(
        ss_steered,
        key_prefix=key_prefix,
        primary_topic_hint=qa_topic_hint,
        tutor_session_id=sid_for_ssr or None,
        tutor_topic=ctx.tutor_topic,
        weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
        show_primary_button=True,
        evidence_ledger=ssr_evidence,
        auto_apply_saved_steering=False,
    )
    render_smart_study_trust_controls(
        ss_steered,
        key_prefix=key_prefix,
        trust_branch_applied=trust_ss_home,
        defer_applied=defer_ss_home,
    )
    render_smart_study_steering_controls(key_prefix=key_prefix)


def render_smart_study_steering_controls(*, key_prefix: str) -> None:
    """US-20.10: локальный «руль» SSR с подсказкой про приоритет жёстких сигналов."""

    safe_pre = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key_prefix)[:40] or "ssr"
    label_to_val = {
        "По умолчанию (базовая политика)": "",
        "Сначала повтор": "review_first",
        "Новая тема": "new_topic",
        "Мягкий режим": "gentle",
    }
    labels = list(label_to_val.keys())
    ui_key = f"{safe_pre}_ssr_steering_pick"
    cur_db = user_state.get_smart_study_steering_preference()
    if ui_key not in st.session_state:
        init_lab = next((lb for lb, v in label_to_val.items() if v == cur_db), labels[0])
        st.session_state[ui_key] = init_lab
    picked = st.radio(
        "Предпочтение для следующей подсказки",
        labels,
        key=ui_key,
        help=(
            "Сохраняется только на этом устройстве. Очереди интервалов и провал мини-quiz остаются приоритетнее; "
            "короткая причина покажет компромисс."
        ),
    )
    chosen_val = label_to_val[picked]
    if chosen_val != cur_db:
        if chosen_val:
            user_state.set_smart_study_steering_preference(chosen_val)
        else:
            user_state.clear_smart_study_steering_preference()
        st.rerun()


def render_smart_study_router_for_progress_tab(*, index_stats: dict[str, Any] | None) -> None:
    ctx = gather_smart_study_router_session_context(index_stats=index_stats)
    render_smart_study_router_strip_from_session_context(
        ctx,
        key_prefix="progress_ssr",
        emit_outcome_receipt=True,
    )


