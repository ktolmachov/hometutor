"""Review-session view for Flashcards hub."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components

from app.flashcard_handoff import (
    build_flashcard_handoff_seed,
    clear_flashcard_handoff_session_fields,
    flashcard_handoff_session_fields,
)
from app.flashcard_handoff_timing import log_handoff_answer_ready, record_handoff_click
from app.flashcards_tag_display import source_path_from_card
from app.flashcard_service import (
    build_flashcard_review_undo_snapshot,
    build_flashcards_session_audit_export,
    estimate_flashcard_due_clear_minutes,
    filter_due_cards_expert,
    get_flashcard_expert_settings,
    get_flashcard_rating_history,
    preview_flashcard_review_intervals,
    set_flashcard_expert_settings,
)
from app.flashcards_memory_signals import compute_card_memory_signals
from app.flashcards_rating_labels import RATING_BUTTONS
from app.flashcards_scheduling import format_interval_ru
from app.models import Message
from app.session_store import session_store

from app.ui.continuity_bridge import flashcard_gap_to_tutor_cta_ru, flashcards_expert_controls_intro_ru
from app.ui.expert_controls import render_expert_controls
from app.ui.flashcards_interactive_card import build_interactive_card_html, estimate_interactive_card_height
from app.ui.flashcards_read_cache import (
    due_count_cache_key,
    flashcards_bootstrap,
    flashcards_due_count,
    invalidate_flashcards_due_counts_only,
    invalidate_flashcards_read_cache,
)
from app.flashcards_review_receipt import (
    build_fc_review_metric_dict_live,
    build_fc_review_receipt_html,
    build_fc_review_receipt_lines,
    capture_fc_review_receipt_baseline,
)
from app.ui.flashcards_sections import FC_MAIN_SECTION_CREATE, pending_section_key
from app.ui.session_state import (
    FLASHCARDS_REVIEW_RECEIPT_BASELINE_KEY,
    PENDING_CURRENT_VIEW_KEY,
    PROGRESS_FOCUS_SECTION_KEY,
    PROGRESS_FOCUS_STREAK_WEEKLY,
)

_EXPERT_FILTER_DEFAULTS = {
    "fc_expert_iv_min": 0,
    "fc_expert_iv_max": 999,
    "fc_expert_ef_min": 1.3,
    "fc_expert_ef_max": 3.0,
    "fc_expert_overdue_only": False,
}

_REVIEW_SCOPE_RESET_PENDING_KEY = "flashcards_review_scope_reset_pending"
_FC_LAST_ACTION_KEY = "flashcards_review_last_action"


def _maybe_render_undo_last_rating(api_call: Callable[..., Any]) -> None:
    """One-step undo for the previous rating: restore SR state and step back."""
    last = st.session_state.get(_FC_LAST_ACTION_KEY)
    if not isinstance(last, dict):
        return
    button_label = str(last.get("button_label") or last.get("q_label") or "оценку")
    eta = str(last.get("eta") or "")
    eta_suffix = f" → {eta}" if eta else ""
    if st.button(
        f"↩ Отменить прошлую оценку: {button_label}{eta_suffix}",
        key="fc_undo_last_rating",
        width="stretch",
    ):
        snapshot = last.get("snapshot") or {}
        try:
            api_call("POST", "/flashcards/review/undo", json=snapshot)
        except Exception as exc:  # noqa: BLE001 - UI displays API failure.
            st.error(f"Не удалось отменить оценку: {exc}")
            return
        q_label = str(last.get("q_label") or "")
        stats = st.session_state.get("flashcards_review_stats", {})
        if stats.get(q_label, 0) > 0:
            stats[q_label] -= 1
            st.session_state["flashcards_review_stats"] = stats
        audit = st.session_state.get("flashcards_review_session_audit")
        if isinstance(audit, list) and audit:
            audit.pop()
        st.session_state["flashcards_review_index"] = int(last.get("idx") or 0)
        st.session_state["flashcards_card_flipped"] = True
        st.session_state.pop(_FC_LAST_ACTION_KEY, None)
        invalidate_flashcards_due_counts_only()
        st.rerun()


def apply_pending_review_scope_reset(
    state: Any,
    *,
    reset_review_session_state: Callable[[Any], None],
    review_scope_signature: Callable[[int | None, str | list[str] | tuple[str, ...] | None], str],
) -> bool:
    if not state.pop(_REVIEW_SCOPE_RESET_PENDING_KEY, False):
        return False

    state["flashcards_review_session_deck_id"] = None
    state["flashcards_review_deck_sync_pending"] = None
    state["flashcards_review_session_tags_text"] = ""
    state["flashcards_review_session_tag_ids"] = []
    state["flashcards_review_session_scope_signature"] = review_scope_signature(None, None)
    reset_review_session_state(state)
    return True


def _fc_ensure_expert_filter_defaults() -> None:
    for k, v in _EXPERT_FILTER_DEFAULTS.items():
        st.session_state.setdefault(k, v)


def _fc_audit_log(event: dict[str, Any]) -> None:
    log = st.session_state.setdefault("flashcards_review_session_audit", [])
    log.append(event)


def _fc_sync_expert_filtered_queue() -> None:
    raw = st.session_state.get("flashcards_review_queue_raw")
    if not isinstance(raw, list):
        return
    _fc_ensure_expert_filter_defaults()
    filtered = filter_due_cards_expert(
        list(raw),
        interval_min=int(st.session_state.get("fc_expert_iv_min", 0)),
        interval_max=int(st.session_state.get("fc_expert_iv_max", 999)),
        ef_min=float(st.session_state.get("fc_expert_ef_min", 1.3)),
        ef_max=float(st.session_state.get("fc_expert_ef_max", 3.0)),
        overdue_only=bool(st.session_state.get("fc_expert_overdue_only", False)),
    )
    st.session_state["flashcards_review_queue"] = filtered
    idx = int(st.session_state.get("flashcards_review_index", 0))
    if not filtered:
        st.session_state["flashcards_review_index"] = 0
        st.session_state["flashcards_card_flipped"] = False
    elif idx >= len(filtered):
        st.session_state["flashcards_review_index"] = 0
        st.session_state["flashcards_card_flipped"] = False


def build_flashcard_tutor_handoff_state(card: dict[str, Any]) -> dict[str, Any]:
    """Session-state fields for Flashcard → Tutor gap handoff (excluding current_view).

    Note: current_view is a selectbox widget key in main.py and cannot be modified after
    the widget is instantiated. Use _request_navigate_to_tutor flag instead; main.py
    checks this before rendering the selectbox.
    """
    deck_label = str(card.get("deck_name") or "карточки").strip()
    front = str(card.get("front") or "").strip()
    topic = str(card.get("topic") or deck_label or "карточки")
    return {
        "current_topic": topic,
        "tutor_goal_subtopic": front[:120],
        "tutor_goal_desired_outcome": "объяснить вопрос из карточки",
        "tutor_goal_time_budget_min": 5,
        "flashcard_review_return": True,
        **flashcard_handoff_session_fields(topic),
    }


def _render_flashcards_expert_layer(
    *,
    deck_label: str,
    selected_tags: list[str],
    recovery_count: int,
    idx: int,
    total: int,
    card: dict[str, Any] | None,
    scope_signature: str,
) -> None:
    stats = st.session_state.get("flashcards_review_stats", {})
    next_review_min = st.session_state.get("flashcards_review_session_next_review_min")
    done = min(idx, total)
    remaining = max(total - idx, 0)
    interval = card.get("interval_days") if isinstance(card, dict) else None
    repetitions = card.get("repetitions") if isinstance(card, dict) else None
    ease = card.get("easiness") if isinstance(card, dict) else None
    signals = [
        f"колода: {deck_label}",
        "теги: " + ", ".join(selected_tags) if selected_tags else "теги: все",
        f"оценки: again {stats.get('again', 0)} / hard {stats.get('hard', 0)} / good {stats.get('good', 0)} / easy {stats.get('easy', 0)}",
    ]
    if interval is not None:
        signals.append(f"интервал: {interval} дн.")
    if repetitions is not None:
        signals.append(f"повторений: {repetitions}")
    if ease is not None:
        signals.append(f"ease: {ease}")
    if isinstance(next_review_min, str) and next_review_min:
        signals.append(f"ближайший повтор: {next_review_min}")
    render_expert_controls(
        intro=flashcards_expert_controls_intro_ru(),
        metrics=(
            ("Пройдено", f"{done}/{total}", "текущая сессия"),
            ("Осталось", str(remaining), "в очереди"),
            ("Due", str(recovery_count), "в выбранном scope"),
            ("Again", str(stats.get("again", 0)), "сигнал пробела"),
        ),
        signals=signals,
        safe_actions=(
            "Обновить очередь или сбросить фильтр можно в блоке фильтра повторения выше.",
            "Если хвост большой, recovery-действие разносит очередь без изменения настроек повторения.",
            "Переход к тьютору сохраняет карточку как пробел и открывает объяснение.",
        ),
        raw_debug_label="Текущая карточка (raw)",
        raw_debug_payload=card,
    )
    with st.expander("Эксперт: фильтры очереди, история повторений, аудит сессии", expanded=False):
        _fc_ensure_expert_filter_defaults()
        c1, c2, c3 = st.columns(3)
        with c1:
            st.slider("Интервал (мин дн.)", 0, 365, key="fc_expert_iv_min")
        with c2:
            st.slider("Интервал (макс дн.)", 0, 999, key="fc_expert_iv_max")
        with c3:
            st.checkbox("Только просрочка по next_review", key="fc_expert_overdue_only")
        e1, e2 = st.columns(2)
        with e1:
            st.slider("EF мин", 1.3, 3.0, key="fc_expert_ef_min")
        with e2:
            st.slider("EF макс", 1.3, 3.0, key="fc_expert_ef_max")
        if st.button("Применить фильтры к загруженной очереди", key="fc_expert_apply_filters"):
            _fc_sync_expert_filtered_queue()
            st.rerun()
        st.caption(
            f"Сырьевая очередь: **{len(st.session_state.get('flashcards_review_queue_raw') or [])}** карточек · "
            f"после фильтра: **{len(st.session_state.get('flashcards_review_queue') or [])}**."
        )
        cur_settings = get_flashcard_expert_settings()
        if "fc_expert_min_ef_input" not in st.session_state:
            st.session_state["fc_expert_min_ef_input"] = float(cur_settings.get("min_easiness", 2.5))
        new_floor = st.number_input(
            "Минимальный коэффициент лёгкости после оценки",
            min_value=1.3,
            max_value=5.0,
            step=0.1,
            key="fc_expert_min_ef_input",
        )
        if st.button("Сохранить пол EF", key="fc_expert_save_min_ef"):
            set_flashcard_expert_settings({"min_easiness": new_floor})
            st.success("Сохранено в локальном хранилище (app_kv).")
        if isinstance(card, dict) and card.get("id") is not None:
            hist_kv = get_flashcard_rating_history(int(card["id"]), limit=10)
            if hist_kv:
                st.markdown("**История оценок (локально)**")
                st.dataframe(hist_kv, width='stretch', hide_index=True)
        audit = st.session_state.get("flashcards_review_session_audit") or []
        st.markdown("**Журнал текущей сессии**")
        st.caption("События оценки в этой вкладке до перезагрузки очереди.")
        if audit:
            st.dataframe(audit[-50:], width='stretch', hide_index=True)
        payload = build_flashcards_session_audit_export(
            deck_label=deck_label,
            scope_signature=scope_signature,
            events=list(audit),
            stats=dict(stats),
        )
        st.download_button(
            "Экспорт JSON сессии",
            json.dumps(payload, ensure_ascii=False, indent=2),
            file_name="flashcards_review_session_expert.json",
            mime="application/json",
            key="fc_expert_dl_session_json",
            width='stretch',
        )


def _render_review_completion(
    *,
    api_call: Callable[..., Any],
    deck_label: str,
    selected_tags: list[str],
    recovery_count: int,
    idx: int,
    total: int,
    scope_signature: str,
    review_summary_html: Callable[[dict[str, Any], int, str | None], str],
    reset_review_session_state: Callable[[Any], None],
) -> None:
    from app.ui.flashcards_ui import (
        _fc_receipt_baseline_valid,
        _fc_review_completion_receipt_visible,
    )

    stats = st.session_state.get("flashcards_review_stats", {})
    nr_min = st.session_state.get("flashcards_review_session_next_review_min")
    nr_val = nr_min if isinstance(nr_min, str) else None
    show_receipt = _fc_review_completion_receipt_visible(idx=idx, total=total, stats=stats)
    _render_flashcards_expert_layer(
        deck_label=deck_label,
        selected_tags=selected_tags,
        recovery_count=recovery_count,
        idx=idx,
        total=total,
        card=None,
        scope_signature=scope_signature,
    )
    _maybe_render_undo_last_rating(api_call)
    if show_receipt:
        baseline = st.session_state.get(FLASHCARDS_REVIEW_RECEIPT_BASELINE_KEY)
        if _fc_receipt_baseline_valid(baseline, scope_signature):
            after = build_fc_review_metric_dict_live(scope_signature=scope_signature)
            lines, measurable = build_fc_review_receipt_lines(baseline, after, next_review_min=nr_val)
            receipt_html = build_fc_review_receipt_html(
                lines,
                measurable=measurable,
                next_review_min=nr_val,
            )
            st.markdown(receipt_html, unsafe_allow_html=True)
            if st.button(
                "Посмотреть в Progress",
                key="flashcards_review_progress_cta",
                type="primary",
                width="stretch",
            ):
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
                st.session_state[PROGRESS_FOCUS_SECTION_KEY] = PROGRESS_FOCUS_STREAK_WEEKLY
                st.rerun()
        st.markdown(review_summary_html(stats, total, nr_val), unsafe_allow_html=True)
    if st.button("🔁 Начать снова", width='stretch', type="secondary"):
        reset_review_session_state(st.session_state)
        st.rerun()


def _record_review_rating(
    *,
    card: dict[str, Any],
    idx: int,
    q_label: str,
    button_label: str,
    quality: int,
    eta: str,
    result: Any,
    merge_session_min_next_review: Callable[[Any, str | None], None],
) -> None:
    merge_session_min_next_review(
        st.session_state,
        result.get("next_review") if isinstance(result, dict) else None,
    )
    _fc_audit_log({"card_id": int(card["id"]), "label": q_label, "quality": quality})
    stats = st.session_state.get("flashcards_review_stats", {})
    stats[q_label] = stats.get(q_label, 0) + 1
    st.session_state["flashcards_review_stats"] = stats
    st.session_state[_FC_LAST_ACTION_KEY] = {
        "card_id": int(card["id"]),
        "idx": idx,
        "q_label": q_label,
        "button_label": button_label,
        "eta": eta,
        "snapshot": build_flashcard_review_undo_snapshot(card),
    }
    st.session_state["flashcards_review_index"] = idx + 1
    st.session_state["flashcards_card_flipped"] = False
    invalidate_flashcards_due_counts_only()
    st.rerun()


def _render_review_rating_bridge(
    *,
    api_call: Callable[..., Any],
    card: dict[str, Any],
    idx: int,
    interval_preview: dict[str, int],
    merge_session_min_next_review: Callable[[Any, str | None], None],
) -> None:
    """Hidden native buttons the interactive card iframe clicks to score.

    Rendered unconditionally (not gated on ``flipped``) because the flip is
    now client-side inside the iframe and the server never learns about it —
    the buttons must exist in the DOM before the learner flips the card.
    Visually hidden off-screen via ``app/ui_theme.css`` (``.st-key-fc_rate_*``),
    not via ``st.columns``/markdown wrapping (that visual layer now lives in
    the iframe card face).
    """
    for label, q_label, quality, _color in RATING_BUTTONS:
        eta = format_interval_ru(int(interval_preview.get(q_label, 1)))
        if st.button(label, key=f"fc_rate_{q_label}", width='stretch'):
            try:
                result = api_call(
                    "POST",
                    "/flashcards/review",
                    json={"card_id": card["id"], "quality": quality},
                )
            except Exception as e:  # noqa: BLE001 - UI displays API failure.
                st.error(f"Не удалось сохранить оценку: {e}")
            else:
                _record_review_rating(
                    card=card,
                    idx=idx,
                    q_label=q_label,
                    button_label=label,
                    quality=quality,
                    eta=eta,
                    result=result,
                    merge_session_min_next_review=merge_session_min_next_review,
                )
    _render_flashcard_tutor_handoff_button(
        api_call=api_call,
        card=card,
        idx=idx,
        merge_session_min_next_review=merge_session_min_next_review,
    )


def _seed_tutor_handoff_session(card: dict[str, Any]) -> None:
    import uuid as _uuid

    _sid = st.session_state.get("tutor_session_id") or str(_uuid.uuid4())
    st.session_state["tutor_session_id"] = _sid
    record_handoff_click(
        st.session_state,
        card_id=int(card["id"]),
        topic=str(card.get("topic") or card.get("deck_name") or "карточки"),
    )
    _seed = build_flashcard_handoff_seed(card)
    _history = session_store.get(_sid)
    _history.extend(
        [
            Message(role="user", content=str(_seed["user_content"])),
            Message(
                role="assistant",
                content=str(_seed["assistant_content"]),
                metadata=dict(_seed["assistant_metadata"]),
            ),
        ]
    )
    session_store.save(
        _sid,
        _history,
        merge_metadata={
            "last_entrypoint": "flashcard_handoff_seed",
            "last_flashcard_id": int(card["id"]),
        },
    )
    _stored_history = session_store.get(_sid)
    st.session_state["tutor_handoff_check_self_pending"] = True
    st.session_state["tutor_handoff_quiz_msg_idx"] = max(0, len(_stored_history) - 1)


def _complete_tutor_handoff_navigation(card: dict[str, Any]) -> None:
    for key, value in build_flashcard_tutor_handoff_state(card).items():
        st.session_state[key] = value
    _seed_tutor_handoff_session(card)
    st.session_state["tutor_last_nba"] = {
        "concept": str(card.get("topic") or card.get("deck_name") or ""),
        "reason": "Карточка отмечена как непонятная; следующий шаг — короткая проверка.",
        "action": "Проверь меня",
        "route": "targeted_reinforcement",
    }
    st.session_state.pop("tutor_pending_prompt", None)
    st.session_state.pop("tutor_pending_session_id", None)
    log_handoff_answer_ready(
        st.session_state,
        api_debug={
            "engine_build_ms": 0.0,
            "retrieval_ms": 0.0,
            "llm_ms": 0.0,
            "rag_ms": 0.0,
            "post_processing_ms": 0.0,
            "total_answer_ms": 0.0,
            "cache_hit": True,
        },
    )
    clear_flashcard_handoff_session_fields(st.session_state)
    st.session_state["_request_navigate_to_tutor"] = True
    invalidate_flashcards_due_counts_only()
    st.rerun()


def _render_flashcard_tutor_handoff_button(
    *,
    api_call: Callable[..., Any],
    card: dict[str, Any],
    idx: int,
    merge_session_min_next_review: Callable[[Any, str | None], None],
) -> None:
    if not st.button(flashcard_gap_to_tutor_cta_ru(), key="fc_gap_to_tutor", width='stretch', type="secondary"):
        return
    try:
        result = api_call(
            "POST",
            "/flashcards/review",
            json={"card_id": card["id"], "quality": 1},
        )
    except Exception as e:  # noqa: BLE001 - UI displays API failure.
        st.error(f"Не удалось сохранить оценку перед переходом: {e}")
        return
    merge_session_min_next_review(
        st.session_state,
        result.get("next_review") if isinstance(result, dict) else None,
    )
    _fc_audit_log({"card_id": int(card["id"]), "label": "tutor_handoff", "quality": 1})
    stats = st.session_state.get("flashcards_review_stats", {})
    stats["again"] = stats.get("again", 0) + 1
    st.session_state["flashcards_review_stats"] = stats
    st.session_state["flashcards_review_index"] = idx + 1
    st.session_state["flashcards_card_flipped"] = False
    _complete_tutor_handoff_navigation(card)


def _render_card_section_links(card: dict[str, Any], idx: int) -> None:
    """«Открыть раздел» (Obsidian/VS Code) + «В рабочий конспект» под карточкой.

    Деградирует тихо: pseudo-source (``scoped-quiz``/``manual``) или конспект ещё
    не создан → ряд не рисуем, карточка остаётся как раньше.
    """
    source_path = source_path_from_card(card)
    if not source_path:
        return
    try:
        from app import workbench_service
        from app.obsidian_export import obsidian_uri, vscode_uri
        from app.section_index import best_section_for, build_section_index

        sections = build_section_index(source_path)
        if not sections:
            return
        query_text = " ".join(
            part for part in [str(card.get("front") or ""), str(card.get("back") or card.get("answer") or "")] if part
        )
        section = best_section_for(sections, query_text)
    except Exception:  # noqa: BLE001 - section lookup must not break card rendering
        return
    if section is None:
        return

    # Obsidian-якорь откроет ПЕРВЫЙ одноимённый heading — при дублях честно подсказываем.
    if sum(1 for s in sections if s.heading_text == section.heading_text) > 1:
        st.caption("⚠️ Заголовок повторяется в документе — VS Code точнее для повторяющихся заголовков.")

    has_video = False
    is_local_video = False
    video_url = None
    video_label = ""
    local_video_obj = None
    local_start_seconds = 0
    local_video_title = ""

    try:
        from urllib.parse import urlencode
        from app.config import get_settings
        from app.living_konspekt_source_resolver import SourceSectionCandidate
        from app.living_konspekt_video_citations import video_citation_for_candidate

        candidate = SourceSectionCandidate(section=section, score=0.0, reason="flashcard_review")
        video_resolution = video_citation_for_candidate(candidate)
        if (
            video_resolution.status == "available"
            and video_resolution.citation is not None
        ):
            citation = video_resolution.citation
            if citation.url is not None:
                has_video = True
                video_label = f"🎬 Смотреть с {citation.timestamp_label}"

                settings = get_settings()
                if settings.auth_enabled or (settings.home_rag_api_key or "").strip():
                    video_url = citation.url
                else:
                    query = urlencode(
                        {
                            "url": citation.url,
                            "heading": section.heading_text,
                            "source": str(section.source_abs.name),
                        }
                    )
                    video_url = f"{settings.ui_api_base_url.rstrip('/')}/living-konspekt/video-citation/open?{query}"
            else:
                # Local video citation
                from pathlib import Path
                from app.media_sidecar import load_media_sidecar_for_konspekt, LocalVideoSource

                sidecar = load_media_sidecar_for_konspekt(Path(section.konspekt_md_abs))
                if sidecar and isinstance(sidecar.video, LocalVideoSource):
                    is_local_video = True
                    has_video = True
                    local_video_obj = sidecar.video
                    local_start_seconds = citation.start_seconds
                    local_video_title = citation.video_title
                    video_label = f"🎬 Видео {citation.timestamp_label}"
    except Exception:  # noqa: BLE001 - video citation lookup failure must not break card rendering
        pass

    if has_video:
        link_cols = st.columns(4)
        obs_col, vs_col, vid_col, wb_col = link_cols[0], link_cols[1], link_cols[2], link_cols[3]
    else:
        link_cols = st.columns(3)
        obs_col, vs_col, wb_col = link_cols[0], link_cols[1], link_cols[2]
        vid_col = None

    with obs_col:
        st.link_button(
            f"📄 «{section.heading_text}» · Obsidian",
            obsidian_uri(section.konspekt_md_abs, heading_text=section.heading_text),
            width="stretch",
        )
    with vs_col:
        st.link_button(
            f"🖥 «{section.heading_text}» · VS Code",
            vscode_uri(section.konspekt_md_abs, line=section.line_start),
            width="stretch",
        )
    if vid_col is not None:
        with vid_col:
            if is_local_video:
                show_local_key = f"fc_show_local_video_{idx}"
                is_active = bool(st.session_state.get(show_local_key, False))
                btn_label = "🎬 Скрыть видео" if is_active else video_label
                if st.button(btn_label, key=f"fc_toggle_video_{idx}", width="stretch"):
                    st.session_state[show_local_key] = not is_active
                    st.rerun()
            elif video_url is not None:
                st.link_button(
                    video_label,
                    video_url,
                    width="stretch",
                )
    with wb_col:
        if st.button("➕ В рабочий конспект", key=f"fc_section_to_workbench_{idx}", width="stretch"):
            rows = workbench_service.normalize_runtime_rows(
                list(st.session_state.get(workbench_service.WORKBENCH_SECTIONS_KEY) or [])
            )
            before = {str(row.get("row_key") or "") for row in rows}
            new_rows = workbench_service.add_section(rows, section)
            st.session_state[workbench_service.WORKBENCH_SECTIONS_KEY] = new_rows
            added = any(str(row.get("row_key") or "") not in before for row in new_rows)
            st.toast(
                f"Добавлено в рабочий конспект: «{section.heading_text}»" if added else "Уже в рабочем конспекте",
                icon="📚",
            )

    if is_local_video and st.session_state.get(f"fc_show_local_video_{idx}", False):
        try:
            from app.ui.living_konspekt_media import _render_local_video_player
            st.write("")  # spacing
            _render_local_video_player(local_video_obj, local_video_title, start_time=local_start_seconds)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Не удалось воспроизвести локальное видео: {exc}")


def _render_active_review_card(
    *,
    api_call: Callable[..., Any],
    card: dict[str, Any],
    idx: int,
    total: int,
    deck_label: str,
    selected_tags: list[str],
    recovery_count: int,
    scope_signature: str,
    review_progress_ratio: Callable[[int, int], float],
    merge_session_min_next_review: Callable[[Any, str | None], None],
) -> None:
    _render_flashcards_expert_layer(
        deck_label=deck_label,
        selected_tags=selected_tags,
        recovery_count=recovery_count,
        idx=idx,
        total=total,
        card=card,
        scope_signature=scope_signature,
    )

    remaining = total - idx - 1
    progress_text = f"Карточка {idx + 1} из {total} · Осталось: {remaining}"
    if remaining > 0:
        progress_text += f" · ~{estimate_flashcard_due_clear_minutes(remaining)} мин"
    st.progress(review_progress_ratio(idx, total), text=progress_text)
    _maybe_render_undo_last_rating(api_call)

    interval_preview = preview_flashcard_review_intervals(card)
    memory = compute_card_memory_signals(card)
    initial_flipped = bool(st.session_state.get("flashcards_card_flipped", False))
    session_nonce = int(st.session_state.get("flashcards_review_queue_nonce", 0))
    card_html = build_interactive_card_html(
        card=card,
        idx=idx,
        total=total,
        interval_preview=interval_preview,
        memory=memory,
        initial_flipped=initial_flipped,
        session_nonce=session_nonce,
    )
    # scrolling=True is a safety net, not the primary sizing mechanism: the
    # JS resize inside the card (see flashcards_interactive_card.py) can only
    # resize its own inner div, not this outer iframe box — components.html()
    # renders a plain iframe that Streamlit never resizes from postMessage.
    # If estimate_interactive_card_height() ever undershoots the real
    # rendered content, scrolling=True means an ugly in-iframe scrollbar
    # instead of the bottom of the card (rating chips, tutor-handoff button)
    # being silently clipped and unreachable by mouse/tap.
    components.html(card_html, height=estimate_interactive_card_height(card), scrolling=True)

    _render_card_section_links(card, idx)

    _render_review_rating_bridge(
        api_call=api_call,
        card=card,
        idx=idx,
        interval_preview=interval_preview,
        merge_session_min_next_review=merge_session_min_next_review,
    )


def render_review(
    *,
    api_call: Callable[..., Any],
    seed_review_scope: Callable[[int | None], None],
    normalize_review_tag_selection: Callable[[str | list[str] | tuple[str, ...] | None], list[str]],
    serialize_review_tags: Callable[[str | list[str] | tuple[str, ...] | None], str | None],
    review_scope_signature: Callable[[int | None, str | list[str] | tuple[str, ...] | None], str],
    reset_review_session_state: Callable[[Any], None],
    build_review_due_params: Callable[[int | None, str | list[str] | tuple[str, ...] | None], dict[str, Any]],
    review_summary_html: Callable[[dict[str, Any], int, str | None], str],
    review_progress_ratio: Callable[[int, int], float],
    merge_session_min_next_review: Callable[[Any, str | None], None],
) -> None:
    apply_pending_review_scope_reset(
        st.session_state,
        reset_review_session_state=reset_review_session_state,
        review_scope_signature=review_scope_signature,
    )

    legacy_deck_filter = st.session_state.pop("flashcards_review_deck_filter", None)
    if legacy_deck_filter is not None:
        seed_review_scope(int(legacy_deck_filter))

    st.markdown('<div data-testid="e2e-fc-jump-create-from-review"></div>', unsafe_allow_html=True)
    if st.button("✨ Создать новую колоду", key="fc_jump_create_from_review", width='stretch'):
        st.session_state[pending_section_key()] = FC_MAIN_SECTION_CREATE
        st.rerun()

    try:
        decks = flashcards_bootstrap()["decks"]
    except Exception as exc:  # noqa: BLE001 - non-critical UI load failure.
        logging.getLogger(__name__).debug("Deck list load failed: %s", exc)
        decks = []

    deck_options: list[tuple[str, int | None]] = [("Все колоды", None)]
    deck_options.extend((str(deck.get("name") or f"Колода {deck['id']}"), int(deck["id"])) for deck in decks)
    deck_labels = [label for label, _deck_id in deck_options]
    deck_ids_by_label = dict(deck_options)
    deck_labels_by_id = {deck_id: label for label, deck_id in deck_options}

    _deck_sel_key = "flashcards_review_scope_deck"
    if "flashcards_review_deck_sync_pending" in st.session_state:
        _pending = st.session_state.pop("flashcards_review_deck_sync_pending")
        _pl = deck_labels_by_id.get(_pending, "Все колоды")
        st.session_state[_deck_sel_key] = _pl if _pl in deck_labels else "Все колоды"

    selected_deck_id = st.session_state.get("flashcards_review_session_deck_id")
    sync_label = deck_labels_by_id.get(selected_deck_id, "Все колоды")
    if sync_label not in deck_labels:
        sync_label = "Все колоды"

    if _deck_sel_key not in st.session_state or st.session_state[_deck_sel_key] not in deck_labels:
        st.session_state[_deck_sel_key] = sync_label

    st.markdown("#### Фильтр повторения")
    c_scope, c_tags = st.columns([1, 2])
    with c_scope:
        deck_label = st.selectbox(
            "Колода",
            deck_labels,
            key=_deck_sel_key,
        )
    with c_tags:
        tags_text = st.text_input(
            "Теги",
            key="flashcards_review_session_tags_text",
            placeholder="Например: algebra, formulas",
        )

    selected_deck_id = deck_ids_by_label[deck_label]
    selected_tags = normalize_review_tag_selection(tags_text)
    st.session_state["flashcards_review_session_deck_id"] = selected_deck_id
    st.session_state["flashcards_review_session_tag_ids"] = selected_tags

    scope_signature = review_scope_signature(selected_deck_id, selected_tags)
    if st.session_state.get("flashcards_review_session_scope_signature") != scope_signature:
        reset_review_session_state(st.session_state)
        st.session_state["flashcards_review_session_scope_signature"] = scope_signature

    scope_bits = []
    if selected_deck_id is not None:
        scope_bits.append(f"Колода: {deck_label}")
    if selected_tags:
        scope_bits.append("Теги: " + ", ".join(selected_tags))
    st.caption(" · ".join(scope_bits) if scope_bits else "Повторение по всем due-карточкам.")

    ser_tags_str = serialize_review_tags(selected_tags)
    recovery_count = 0
    schedule_info: dict[str, Any] = {}
    cnt_p: dict[str, Any] = {}
    try:
        if selected_deck_id is not None:
            cnt_p["deck_id"] = int(selected_deck_id)
        if ser_tags_str:
            cnt_p["tags"] = ser_tags_str
        recovery_count = int(flashcards_due_count(due_count_cache_key(cnt_p)))
        if recovery_count == 0:
            schedule_info = api_call("GET", "/flashcards/due/schedule", params=cnt_p)
    except Exception as exc:  # noqa: BLE001 - non-critical precheck failure.
        logging.getLogger(__name__).debug("Due count load failed: %s", exc)
        recovery_count = 0

    if recovery_count > 20:
        st.warning(
            f"**Recovery-план:** в выбранной области **{recovery_count}** карточек к повторению. "
            "Рекомендуем проходить по 5–7 в день. Можно разнести хвост очереди: "
            "останутся только топ-7 по приоритету, остальные получат новые даты повторения."
        )
        _rk = hashlib.sha256(scope_signature.encode("utf-8")).hexdigest()[:24]
        if st.button(
            "Разнести хвост очереди на 5 дней",
            key=f"fc_due_recovery_{_rk}",
            width='stretch',
            type="secondary",
        ):
            try:
                payload: dict[str, Any] = {"keep_limit": 7, "stagger_days": 5}
                if selected_deck_id is not None:
                    payload["deck_id"] = int(selected_deck_id)
                if ser_tags_str:
                    payload["tags"] = ser_tags_str
                moved = int(api_call("POST", "/flashcards/due/recovery", json=payload).get("moved") or 0)
                st.success(f"Отложено карточек: **{moved}**.")
                invalidate_flashcards_read_cache()
                reset_review_session_state(st.session_state)
                st.rerun()
            except Exception as ex:  # noqa: BLE001 - UI displays API failure.
                st.error(str(ex))

    c_load, c_clear = st.columns([2, 1])
    with c_load:
        if st.button("Загрузить очередь", type="primary", width='stretch', key="flashcards_review_load_queue"):
            st.session_state["flashcards_review_session_status"] = "loading"
            try:
                data = api_call("GET", "/flashcards/due", params=build_review_due_params(selected_deck_id, selected_tags))
                queue = data.get("cards") or []
                st.session_state["flashcards_review_queue_raw"] = list(queue)
                st.session_state["flashcards_review_session_audit"] = []
                _fc_ensure_expert_filter_defaults()
                _fc_sync_expert_filtered_queue()
                st.session_state["flashcards_review_index"] = 0
                st.session_state["flashcards_card_flipped"] = False
                st.session_state["flashcards_review_queue_nonce"] = (
                    int(st.session_state.get("flashcards_review_queue_nonce", 0)) + 1
                )
                st.session_state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
                st.session_state.pop(_FC_LAST_ACTION_KEY, None)
                st.session_state["flashcards_review_session_next_review_min"] = None
                st.session_state["flashcards_review_session_status"] = "loaded"
                st.session_state["flashcards_review_session_error"] = None
                st.session_state[FLASHCARDS_REVIEW_RECEIPT_BASELINE_KEY] = (
                    capture_fc_review_receipt_baseline(scope_signature)
                )
            except Exception as e:  # noqa: BLE001 - UI displays API failure.
                st.session_state["flashcards_review_queue"] = []
                st.session_state["flashcards_review_session_status"] = "error"
                st.session_state["flashcards_review_session_error"] = str(e)
    with c_clear:
        if st.button("Сбросить фильтр", width='stretch', key="flashcards_review_clear_scope"):
            st.session_state[_REVIEW_SCOPE_RESET_PENDING_KEY] = True
            st.rerun()

    status = st.session_state.get("flashcards_review_session_status", "idle")
    if status == "error":
        st.error(f"Не удалось загрузить очередь повторения: {st.session_state.get('flashcards_review_session_error')}")
        return
    if status == "idle":
        st.info("Выберите область повторения и загрузите очередь.")
        return

    queue: list[dict] = st.session_state.get("flashcards_review_queue", [])
    idx: int = st.session_state.get("flashcards_review_index", 0)
    total = len(queue)

    if total == 0:
        if selected_tags:
            st.info("Ничего не нашлось по выбранным тегам. Сбросьте фильтр или выберите другие теги.")
        else:
            next_review = schedule_info.get("next_review")
            next_count = int(schedule_info.get("next_count") or 0)
            if next_review:
                st.info(
                    f"Сейчас нет карточек к повторению. Ближайшие: **{next_count}** — "
                    f"**{str(next_review)[:10]}**."
                )
            else:
                st.info("Сейчас нет карточек к повторению.")
            undoable_count = int(schedule_info.get("undoable_count") or 0)
            if undoable_count > 0 and st.button(
                f"Отменить разнесение хвоста ({undoable_count})",
                width='stretch',
                key="flashcards_review_undo_recovery",
            ):
                try:
                    payload: dict[str, Any] = {}
                    if selected_deck_id is not None:
                        payload["deck_id"] = int(selected_deck_id)
                    if ser_tags_str:
                        payload["tags"] = ser_tags_str
                    restored = int(
                        api_call("POST", "/flashcards/due/recovery/undo", json=payload).get("restored") or 0
                    )
                    st.success(f"Возвращено в очередь: **{restored}** карточек.")
                    invalidate_flashcards_read_cache()
                    reset_review_session_state(st.session_state)
                    st.rerun()
                except Exception as ex:  # noqa: BLE001 - UI displays API failure.
                    st.error(str(ex))
        if st.button("Обновить", width='stretch'):
            reset_review_session_state(st.session_state)
            st.rerun()
        return

    if idx >= total:
        _render_review_completion(
            api_call=api_call,
            deck_label=deck_label,
            selected_tags=selected_tags,
            recovery_count=recovery_count,
            idx=idx,
            total=total,
            scope_signature=scope_signature,
            review_summary_html=review_summary_html,
            reset_review_session_state=reset_review_session_state,
        )
        return

    card = queue[idx]
    _render_active_review_card(
        api_call=api_call,
        card=card,
        idx=idx,
        total=total,
        deck_label=deck_label,
        selected_tags=selected_tags,
        recovery_count=recovery_count,
        scope_signature=scope_signature,
        review_progress_ratio=review_progress_ratio,
        merge_session_min_next_review=merge_session_min_next_review,
    )
