"""Adaptive Daily Plan: карточка для главного экрана (стиль home-dash-card, навигация через current_view).

Мониторинг SSR LLM explanation (US-20.7 / llm-ssr-explanation-integration):
- Кэш: ``_SSR_LLM_EXPLANATION_CACHE``, TTL ``_SSR_LLM_EXPLANATION_CACHE_TTL_SEC`` (1 ч).
- Таймаут вызова: ``_SSR_LLM_EXPLANATION_TIMEOUT_SEC``; при превышении — шаблон ``why_now_ru``.
- Token guard: usage ``> 500`` логируется для prompt compression; ``> 700`` откатывается в шаблон.
- Профили: ``logs/ssr_llm_profiles/ssr_llm_profile_*.jsonl`` (см. ``app.ssr_llm_profiling``; сводка ``scripts/summarize_ssr_llm_profiles.py``; откл. ``ENABLE_SSR_LLM_PROFILING=false``).
- OTEL: спан ``ssr_llm_explanation`` при ``ENABLE_OTEL_TRACING`` (см. ``app.otel_tracing``).
- LLM: ``get_ssr_llm_resolved()`` — при недоступном loopback SSR — основной ``LLM_MODEL`` (см. ``app.provider``).
- Логи: ``logger.info("ssr_llm_explanation_fallback", ...)`` при ошибке LLM;
  стадия ``ssr_llm_explanation`` уходит в ``complete_with_resilience`` (см. cost/метрики провайдера).
- Маршрутизация SSR не читает ответ LLM; подменяется только текст короткой причины в UI.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from app.gamification_service import award_xp_for_block, count_completed_plan_blocks, get_snapshot
from app.ssr_context_builder import build_ssr_llm_learning_context as _build_ssr_llm_learning_context
from app.ui_client import stream_ssr_explain as _stream_ssr_explain
from app.learning_plan_service import (
    ADAPTIVE_DAILY_PLAN_KV_KEY,
    AdaptiveDailyPlan,
    get_adaptive_daily_plan_history,
    get_primary_adaptive_daily_plan_block,
    get_primary_adaptive_daily_plan_block_from_plan,
    iter_adaptive_daily_plan_blocks,
    get_saved_adaptive_daily_plan,
)
from app.adaptive_plan_step_text import (
    BLOCK_TYPE_BADGE as _BLOCK_BADGE,
    BLOCK_TYPE_LABEL_RU as _BLOCK_LABEL,
    block_badge_label,
    build_plan_step_reason,
    is_placeholder_plan_concept as _is_placeholder_concept,
    plan_block_concept_line as _block_concept_line,
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.smart_study_router import (
    EvidenceItem,
    SmartStudyPrimaryNav,
    SmartStudyRecommendation,
    SmartStudyRouterHintKind,
    SmartStudySecondaryAction,
    _build_smart_study_recommendation_rules,
    apply_smart_study_steering_preference,
    build_smart_study_evidence_items,
    build_smart_study_evidence_ledger_lines,
    build_smart_study_recommendation,
    smart_study_contrastive_explanation,
    smart_study_why_not_others_ru,
)

def _session_has_last_answer_qa() -> bool:
    la = st.session_state.get("last_answer")
    return bool(
        isinstance(la, dict)
        and (str(la.get("question") or "").strip() or str(la.get("answer") or "").strip())
    )

def _ensure_tutor_session_local() -> None:
    if not str(st.session_state.get("tutor_session_id") or "").strip():
        st.session_state["tutor_session_id"] = str(uuid.uuid4())

def apply_smart_study_secondary_navigation(action_id: str, *, topic_hint: str | None = None) -> None:
    """Навигация для вторичных кнопок карточки Smart Study Router."""
    try:
        from app.ui.resume_cards_smart_study import advance_concept_recovery_ladder_after_secondary

        advance_concept_recovery_ladder_after_secondary(action_id)
    except Exception as _exc:  # noqa: BLE001 - ladder advance must not block navigation.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("ladder secondary advance: %s", _exc)
    th = str(topic_hint or "").strip()
    if action_id == "qa_sources":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Быстрый ответ"
        st.rerun()
        return
    if action_id == "tutor_simpler":
        _ensure_tutor_session_local()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            "Объясни проще короткими шагами, без лишних терминов и с одним мини-примером."
        )
        st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
        st.session_state["tutor_cta_action"] = "smart_study_simpler"
        if th:
            st.session_state["current_topic"] = th
        st.rerun()
        return
    if action_id == "fc_create":
        from app.ui.flashcards_sections import FC_MAIN_SECTION_CREATE, set_flashcards_section

        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
        st.session_state["flashcards_subview"] = "decks"
        set_flashcards_section(FC_MAIN_SECTION_CREATE)
        return
    if action_id == "quiz_nav":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Интерактивный Quiz"
        st.rerun()
        return
    if action_id == "progress_go":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
        st.rerun()
        return
    if action_id == "topics_nav":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Темы"
        st.rerun()
        return

def apply_smart_study_primary_navigation(
    rec: SmartStudyRecommendation,
    *,
    tutor_session_id: str | None = None,
    tutor_topic: str | None = None,
    plan_block: dict[str, Any] | None = None,
    weak_concept: str | None = None,
) -> None:
    """Primary-клики карточки (дублируют ключевые переходы continuity без скрытия режимов)."""
    try:
        from app.ui.resume_cards_smart_study import advance_concept_recovery_ladder_after_primary

        advance_concept_recovery_ladder_after_primary(rec)
    except Exception as _exc:  # noqa: BLE001 - ladder advance must not block navigation.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("ladder primary advance: %s", _exc)
    nav = rec.primary_nav
    sid = str(tutor_session_id or "").strip() or None
    tt = str(tutor_topic or "").strip() or None
    wc = str(weak_concept or "").strip()
    block = plan_block if isinstance(plan_block, dict) else None

    if nav == "flashcards_review":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
        st.session_state["flashcards_subview"] = "review"
        st.session_state["flashcards_review_queue"] = []
        st.rerun()
        return
    if nav == "sm2_tutor":
        _ensure_tutor_session_local()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        c = wc or tt or "текущий концепт"
        st.session_state["tutor_pending_prompt"] = (
            f"Помоги коротко повторить тему «{c}» (она в очереди интервальных повторений)."
        )
        st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
        st.session_state["tutor_cta_action"] = "smart_study_sm2"
        st.session_state["current_topic"] = c
        st.rerun()
        return
    if nav == "quiz_recovery_tutor":
        _ensure_tutor_session_local()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            "Разберём ошибку последнего мини-квиза: короткая диагностика и одно упражнение без давления."
        )
        st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
        st.session_state["tutor_cta_action"] = "smart_study_quiz_recovery"
        if tt:
            st.session_state["current_topic"] = tt
        st.rerun()
        return
    if nav == "tutor_resume":
        _ensure_tutor_session_local()
        if sid:
            st.session_state["tutor_session_id"] = sid
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_cta_action"] = "smart_study_resume"
        if tt:
            st.session_state["current_topic"] = tt
        st.rerun()
        return
    if nav == "qa_continue":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Быстрый ответ"
        st.session_state["tutor_cta_action"] = "smart_study_qa"
        st.rerun()
        return
    if nav == "tutor_weak_gap":
        _ensure_tutor_session_local()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        concept = wc or tt or "текущую тему"
        st.session_state["tutor_pending_prompt"] = (
            f"Помоги освоить следующий шаг по концепту «{concept}»: кратко объясни суть и дай одно упражнение."
        )
        st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
        st.session_state["tutor_cta_action"] = "smart_study_mastery_gap"
        st.session_state["current_topic"] = concept
        st.rerun()
        return
    if nav == "plan_block_tutor" and block is not None:
        launch_tutor_for_plan_block(block, action_label="Smart Study Router")
        return
    _ensure_tutor_session_local()
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
    st.session_state["tutor_pending_prompt"] = (
        "Сделай короткую учебную сессию на 5 минут по одной теме: один концепт, "
        "микро-пояснение и одно простое упражнение без длинного вступления."
    )
    st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
    st.session_state["tutor_e11_five_min_loop"] = True
    st.session_state["tutor_cta_action"] = "smart_study_safe"
    st.rerun()

def render_ssr_why_now_streaming(
    rec: "SmartStudyRecommendation",
    *,
    evidence_ledger: list[str] | None = None,
    tutor_topic: str | None = None,
    weak_concept: str | None = None,
    primary_topic_hint: str | None = None,
    label: str = "**Почему это подходит:**",
) -> str:
    """Render the SSR «Why now» explanation with streaming tokens visible in real time.

    Use this instead of ``_ssr_why_now_for_card`` when you want the user to see
    text appearing token-by-token (typically on a cache miss with a local CPU model).

    - Cache hit → renders the cached text instantly via ``st.markdown``.
    - Cache miss + streaming LLM → streams tokens into an ``st.empty`` placeholder
      using ``st.write_stream``; caches the result when done.
    - Any error / unsupported LLM → falls back to the template text.

    Returns the final explanation text so the caller can embed it elsewhere if needed.
    """
    import streamlit as st

    ctx = _build_ssr_llm_learning_context(
        rec,
        evidence_ledger=evidence_ledger,
        tutor_topic=tutor_topic,
        weak_concept=weak_concept,
        primary_topic_hint=primary_topic_hint,
    )

    def _gen():
        count = 0
        for token in _stream_ssr_explain(
            ctx,
            hint_kind=rec.hint_kind,
            primary_label_ru=rec.primary_label_ru,
            why_now_ru=rec.why_now_ru,
            primary_nav=str(rec.primary_nav),
            route_pedagogy_ru=str(rec.route_pedagogy_ru or ""),
            ml_audit_ru=str(rec.ml_audit_ru or ""),
            has_secondaries=bool(rec.secondaries),
            evidence_ledger=evidence_ledger,
        ):
            count += 1
            yield token
        if count == 0:
            yield rec.why_now_ru

    st.markdown(label)
    result_text: str = ""
    try:
        with st.spinner("Формулируем объяснение…"):
            result_text = st.write_stream(_gen())  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - streaming must survive errors gracefully.
        result_text = rec.why_now_ru
        st.markdown(result_text)
    return str(result_text)

def render_smart_study_next_step_card(
    rec: SmartStudyRecommendation,
    *,
    key_prefix: str,
    primary_topic_hint: str | None = None,
    tutor_session_id: str | None = None,
    tutor_topic: str | None = None,
    plan_block: dict[str, Any] | None = None,
    weak_concept: str | None = None,
    show_primary_button: bool = False,
    evidence_ledger: list[str] | None = None,
    has_last_answer_qa_for_steering: bool | None = None,
    defer_was_applied_for_steering: bool = False,
    auto_apply_saved_steering: bool = True,
) -> None:
    """Render the SSR next-step card via the extracted UI module."""
    from app.ui.smart_study_next_step_card import render_smart_study_next_step_card as _render

    _render(
        rec,
        key_prefix=key_prefix,
        primary_topic_hint=primary_topic_hint,
        tutor_session_id=tutor_session_id,
        tutor_topic=tutor_topic,
        plan_block=plan_block,
        weak_concept=weak_concept,
        show_primary_button=show_primary_button,
        evidence_ledger=evidence_ledger,
        has_last_answer_qa_for_steering=has_last_answer_qa_for_steering,
        defer_was_applied_for_steering=defer_was_applied_for_steering,
        auto_apply_saved_steering=auto_apply_saved_steering,
    )

def render_recent_adaptive_plan_history() -> None:
    """US-6.3: краткая история последних снимков (данные только из KV history)."""
    entries = get_adaptive_daily_plan_history()
    if not entries:
        return
    with st.expander("Недавние снимки плана", expanded=False):
        st.caption("До трёх последних версий до пересчёта: дата, фокус review/gap/new, главные концепты.")
        for e in reversed(entries[-3:]):
            if not isinstance(e, dict):
                continue
            date = str(e.get("date") or "—")
            f = e.get("focus_review_gap_new")
            if isinstance(f, list) and len(f) >= 3:
                fg = f"{int(f[0])}/{int(f[1])}/{int(f[2])}"
            else:
                fg = "—"
            concs = [str(c).strip() for c in (e.get("main_concepts") or []) if str(c).strip()][:3]
            conc_line = ", ".join(f"«{c}»" for c in concs) if concs else ""
            st.markdown(f"**{date}** · review/gap/new: **{fg}**")
            if conc_line:
                st.caption(conc_line)
            arch = str(e.get("archived_at") or "").strip()
            if arch:
                st.caption(f"зафиксировано: {arch[:19].replace('T', ' ')} UTC")

def render_plan_concepts_delta_ui(plan: dict[str, Any]) -> None:
    """US-6.2: краткий diff концептов в шагах плана vs предыдущий сохранённый снимок."""
    delta = plan.get("plan_concepts_delta")
    if not isinstance(delta, dict):
        return
    added, removed = _normalize_plan_concepts_delta(plan, delta)
    with st.expander("Что изменилось в плане", expanded=False):
        bd = str(delta.get("baseline_date") or "").strip()
        if bd:
            st.caption(f"Сравнение с сохранённой версией плана ({bd}).")
        else:
            st.caption("Нет вчерашнего плана для сравнения: diff появится после следующего пересчёта.")
        if added:
            st.markdown("**Появились в шагах:** " + ", ".join(f"«{x}»" for x in added))
        if removed:
            st.markdown("**Исчезли из шагов:** " + ", ".join(f"«{x}»" for x in removed))
        if not added and not removed and bd:
            st.caption("Состав концептов не изменился относительно предыдущего плана.")

def _normalize_plan_concepts_delta(
    plan: dict[str, Any],
    delta: dict[str, Any],
) -> tuple[list[str], list[str]]:
    current_concepts = {
        str((raw or {}).get("concept") or "").strip()
        for raw in (plan.get("blocks") or [])
        if isinstance(raw, dict)
    }
    current_concepts.discard("")

    added = sorted(
        {
            str(item).strip()
            for item in (delta.get("added") or [])
            if str(item).strip() and str(item).strip() in current_concepts
        }
    )
    removed = sorted(
        {
            str(item).strip()
            for item in (delta.get("removed") or [])
            if str(item).strip()
        }
    )
    return added, removed

def _session_user_id(explicit: str | None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return str(st.session_state.get("user_id") or "local").strip() or "local"

def _tutor_session_id() -> str | None:
    sid = st.session_state.get("tutor_session_id")
    if sid is None:
        return None
    s = str(sid).strip()
    return s or None

def _refresh_plan_lp_context(plan: dict[str, Any]) -> bool:
    """Refresh learning_plan_context from current resume. Returns True if changed."""
    try:
        from app.user_state import get_latest_learning_plan_resume
        lp_resume = get_latest_learning_plan_resume()
        new_ctx = None
        if lp_resume:
            new_ctx = {
                "display_title": str(lp_resume.get("display_title") or ""),
                "step_index": lp_resume.get("step_index"),
                "step_label": str(lp_resume.get("step_label") or "")[:120],
                "progress": lp_resume.get("progress"),
            }
        old_ctx = plan.get("learning_plan_context")
        if old_ctx != new_ctx:
            if new_ctx:
                plan["learning_plan_context"] = new_ctx
            else:
                plan.pop("learning_plan_context", None)
            return True
    except Exception:  # noqa: BLE001 — context refresh is best-effort
        pass
    return False


def _effective_plan(user_id: str, plan_override: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(plan_override, dict) and plan_override:
        return plan_override
    today = datetime.now(timezone.utc).date().isoformat()
    saved = get_saved_adaptive_daily_plan()
    if saved and str(saved.get("date") or "") == today:
        if _refresh_plan_lp_context(saved):
            try:
                from app.user_state import set_kv
                set_kv(ADAPTIVE_DAILY_PLAN_KV_KEY, json.dumps(saved, ensure_ascii=False))
            except Exception:  # noqa: BLE001 — context refresh is best-effort
                pass
        return saved
    return AdaptiveDailyPlan(user_id, session_id=_tutor_session_id()).build_adaptive_daily_plan()

def get_adaptive_daily_plan(
    user_id: str | None = None,
    *,
    plan_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = _session_user_id(user_id)
    return _effective_plan(uid, plan_override)

def _iter_plan_blocks(blocks: list[Any]) -> list[tuple[int, dict[str, Any]]]:
    return iter_adaptive_daily_plan_blocks(blocks)

def _block_agent(block: dict[str, Any]) -> str:
    return str(block.get("agent") or block.get("recommended_agent") or "Orchestrator").strip() or "Orchestrator"

def tutor_prompt_for_block(block: dict[str, Any]) -> str:
    bt = str(block.get("type") or "").strip()
    c_raw = str(block.get("concept") or "").strip()
    c_ok = None if _is_placeholder_concept(c_raw) else c_raw
    if bt == "review" and c_ok:
        return (
            f"Помоги повторить концепт «{c_ok}» (шаг из Adaptive Daily Plan: повторение по расписанию)."
        )
    if bt == "review" and not c_ok:
        return (
            "Помоги с коротким повторением: один наводящий вопрос и мини-проверка — тему уточним по ходу."
        )
    if bt == "gap" and c_ok:
        return (
            f"Помоги спокойно разобрать «{c_ok}»: коротко проверь понимание и дай одно маленькое упражнение."
        )
    if bt == "gap" and not c_ok:
        return (
            "Предложи мягкий старт: спроси, что уже лежит в моей базе (data), и дай одно короткое упражнение "
            "на разогрев без жёсткой темы."
        )
    if bt == "new" and c_ok:
        return f"Давай разберём новую тему «{c_ok}»: краткий обзор и следующий шаг."
    if bt == "new" and not c_ok:
        return (
            "Предложи лёгкий вход в новый материал: с чего начать из моей папки data и какой маленький первый шаг."
        )
    if bt == "motivation":
        return "Короткая мотивационная сессия: с чего начать сегодня и один конкретный следующий шаг."
    return str(block.get("description") or "Продолжим по учебному плану на сегодня.")

def get_primary_plan_block(blocks: list[Any]) -> tuple[int, dict[str, Any]] | None:
    """Первый содержательный шаг плана; ``auto_loop`` остаётся fallback-only."""
    return get_primary_adaptive_daily_plan_block(blocks)

def get_primary_plan_block_from_plan(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Prefer the explicit entry-surface contract when present."""
    return get_primary_adaptive_daily_plan_block_from_plan(plan)

def adaptive_plan_progress_teaser_caption(
    user_id: str | None = None,
    *,
    plan_override: dict[str, Any] | None = None,
) -> str | None:
    """E9.6 / US-9.1: одна строка для блока «Прогресс» (без нового дашборда)."""
    plan = get_adaptive_daily_plan(user_id, plan_override=plan_override)
    blocks = plan.get("blocks") or []
    primary = get_primary_plan_block(blocks)
    if not primary:
        return None
    _, block = primary
    bt = str(block.get("type") or "").strip()
    lab = _BLOCK_LABEL.get(bt, (bt or "шаг").replace("_", " "))
    c_raw = str(block.get("concept") or "").strip()
    if _is_placeholder_concept(c_raw):
        return f"Adaptive plan: следующий акцент — {lab}"
    return f"Adaptive plan: следующий акцент — {lab} — «{c_raw[:72]}»"

def build_plan_progress_summary(*, progress_done: int, total_blocks: int, daily_xp: int) -> str:
    total = max(0, int(total_blocks))
    done = max(0, min(int(progress_done), total))
    if total <= 0:
        return f"На сегодня в плане пока нет шагов · {int(daily_xp)} XP за день."
    left = max(0, total - done)
    if done >= total:
        return f"План на сегодня закрыт: {done}/{total} блоков · {int(daily_xp)} XP за день."
    return f"Сделано {done}/{total} блоков · осталось {left} · набрано {int(daily_xp)} XP сегодня."

def _ensure_tutor_session() -> None:
    import uuid

    if not str(st.session_state.get("tutor_session_id") or "").strip():
        st.session_state["tutor_session_id"] = str(uuid.uuid4())

def go_tutor_with_prompt(
    prompt: str,
    topic: str | None,
    *,
    action_label: str = "Adaptive Daily Plan",
) -> None:
    _ensure_tutor_session()
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
    st.session_state["tutor_pending_prompt"] = prompt
    st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
    st.session_state["tutor_cta_action"] = action_label
    if topic:
        st.session_state["current_topic"] = topic
    st.rerun()

def launch_tutor_for_plan_block(
    block: dict[str, Any],
    *,
    action_label: str = "Adaptive Daily Plan",
) -> None:
    cc = str(block.get("concept") or "").strip()
    topic = cc if cc and not _is_placeholder_concept(cc) else None
    go_tutor_with_prompt(
        tutor_prompt_for_block(block),
        topic,
        action_label=action_label,
    )

def request_home_full_plan_expanded() -> None:
    st.session_state["home_adp_full_expanded"] = True

def render_adaptive_plan_hub(
    user_id: str | None = None,
    *,
    key_prefix: str = "adp_hub",
    plan_override: dict[str, Any] | None = None,
    preview_limit: int = 4,
) -> None:
    """Render the home CTA block via the extracted hub layout module."""
    from app.ui.adaptive_plan_hub_layout import render_adaptive_plan_hub as _render

    _render(
        user_id=user_id,
        key_prefix=key_prefix,
        plan_override=plan_override,
        preview_limit=preview_limit,
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
    """Render the full Adaptive Daily Plan card via the extracted UI module."""
    from app.ui.adaptive_daily_plan_layout import render_adaptive_daily_plan as _render

    _render(
        user_id=user_id,
        show_buttons=show_buttons,
        compact=compact,
        key_prefix=key_prefix,
        plan_override=plan_override,
        show_json_expander=show_json_expander,
    )

__all__ = [
    "EvidenceItem",
    "SmartStudyRecommendation",
    "SmartStudyRouterHintKind",
    "SmartStudySecondaryAction",
    "SmartStudyPrimaryNav",
    "_build_smart_study_recommendation_rules",
    "apply_smart_study_primary_navigation",
    "apply_smart_study_secondary_navigation",
    "apply_smart_study_steering_preference",
    "build_plan_progress_summary",
    "build_plan_step_reason",
    "build_smart_study_evidence_items",
    "build_smart_study_evidence_ledger_lines",
    "build_smart_study_recommendation",
    "block_badge_label",
    "get_adaptive_daily_plan",
    "get_primary_plan_block",
    "get_primary_plan_block_from_plan",
    "go_tutor_with_prompt",
    "launch_tutor_for_plan_block",
    "render_adaptive_daily_plan",
    "render_adaptive_plan_hub",
    "render_smart_study_next_step_card",
    "render_ssr_why_now_streaming",
    "smart_study_contrastive_explanation",
    "smart_study_why_not_others_ru",
    "request_home_full_plan_expanded",
    "tutor_prompt_for_block",
]
