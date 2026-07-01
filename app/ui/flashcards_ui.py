"""Flashcards UI — генерация, управление колодами, SM-2 review (E12)."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from app.ui.flashcards_decks_view import render_deck_detail as _render_deck_detail_impl
from app.ui.flashcards_decks_view import render_decks_list as _render_decks_list_impl
from app.ui.flashcards_generate_view import render_generate as _render_generate_impl
from app.ui.flashcards_review_view import render_review as _render_review_impl
from app.ui.flashcards_read_cache import flashcards_bootstrap
from app.ui.flashcards_sections import (
    FC_MAIN_SECTION_CREATE,
    FC_MAIN_SECTION_DECKS,
    FC_MAIN_SECTION_REVIEW,
    apply_e2e_section_override as _apply_e2e_section_override_impl,
    apply_pending_flashcards_section as _apply_pending_flashcards_section_impl,
    pending_section_key as _pending_section_key,
    section_order_and_labels as _section_order_and_labels,
    set_flashcards_section as _set_flashcards_section_impl,
)
from app.ui_client import fetch_json

def _apply_pending_flashcards_section() -> None:
    _apply_pending_flashcards_section_impl()


def _set_flashcards_section(section: str) -> None:
    _set_flashcards_section_impl(section)


def _apply_e2e_section_override() -> None:
    _apply_e2e_section_override_impl()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _api(method: str, path: str, **kwargs) -> Any:
    timeout = kwargs.pop("timeout", 120)
    return fetch_json(method, path, timeout=timeout, **kwargs)


def _parse_iso_utc(iso: str) -> datetime | None:
    """Parse API next_review / last_review ISO string for comparison."""
    raw = (iso or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_next_review_caption(iso: str | None) -> str:
    if not iso:
        return ""
    dt = _parse_iso_utc(str(iso))
    if dt is None:
        return str(iso).strip()
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _merge_session_min_next_review(state: Any, next_review_iso: str | None) -> None:
    """Keep earliest next_review among successfully rated cards in this session."""
    new_dt = _parse_iso_utc(next_review_iso or "")
    if new_dt is None:
        return
    key = "flashcards_review_session_next_review_min"
    prev_raw = state.get(key)
    if prev_raw is None:
        state[key] = (next_review_iso or "").strip()
        return
    prev_dt = _parse_iso_utc(str(prev_raw))
    if prev_dt is None or new_dt < prev_dt:
        state[key] = (next_review_iso or "").strip()


def _review_summary_html(stats: dict[str, Any], total: int, next_review_min: str | None) -> str:
    nr = ""
    if next_review_min:
        cap = html.escape(_format_next_review_caption(next_review_min))
        nr = f"<p>📅 Ближайшее повторение среди оценённых: <b>{cap}</b></p>"
    return (
        '<div class="fc-review-summary">'
        f"<h3>✅ Сессия завершена — {total} карточек</h3>"
        f'<p>🔴 Снова: <b>{stats.get("again", 0)}</b> &nbsp; '
        f'🟡 Трудно: <b>{stats.get("hard", 0)}</b> &nbsp; '
        f'🟢 Хорошо: <b>{stats.get("good", 0)}</b> &nbsp; '
        f'⭐ Легко: <b>{stats.get("easy", 0)}</b></p>'
        f"{nr}"
        "</div>"
    )


def _normalize_review_tag_selection(tags: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize UI tag input for forwarding to the backend filter contract."""
    if tags is None:
        return []
    raw_parts: list[str] = []
    if isinstance(tags, str):
        raw_parts = tags.replace(";", ",").replace("|", ",").split(",")
    else:
        raw_parts = [str(tag) for tag in tags]

    normalized: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        tag = " ".join(str(part).strip().lower().split())
        if tag and tag not in seen:
            normalized.append(tag)
            seen.add(tag)
    return normalized


def _serialize_review_tags(tags: str | list[str] | tuple[str, ...] | None) -> str | None:
    normalized = _normalize_review_tag_selection(tags)
    return ", ".join(normalized) if normalized else None


def _review_scope_signature(deck_id: int | None, tags: str | list[str] | tuple[str, ...] | None) -> str:
    tag_filter = _serialize_review_tags(tags) or ""
    return f"deck={deck_id or 'all'}|tags={tag_filter}"


def _build_review_due_params(
    deck_id: int | None,
    tags: str | list[str] | tuple[str, ...] | None,
    *,
    limit: int = 1000,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if deck_id is not None:
        params["deck_id"] = int(deck_id)
    serialized_tags = _serialize_review_tags(tags)
    if serialized_tags:
        params["tags"] = serialized_tags
    return params


def _review_progress_ratio(index: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, index / total))


def _fc_receipt_baseline_valid(baseline: Any, scope_signature: str) -> bool:
    from app.flashcards_review_receipt import FC_REVIEW_RECEIPT_BASELINE_TTL_SEC
    import time

    if not isinstance(baseline, dict):
        return False
    if str(baseline.get("scope_signature") or "") != (scope_signature or "").strip():
        return False
    try:
        age = time.time() - float(baseline.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= FC_REVIEW_RECEIPT_BASELINE_TTL_SEC


def _fc_review_completion_receipt_visible(*, idx: int, total: int, stats: dict[str, Any]) -> bool:
    if total <= 0 or idx < total:
        return False
    rating_sum = sum(int(stats.get(k, 0) or 0) for k in ("again", "hard", "good", "easy"))
    return rating_sum >= 1


def _reset_review_session_state(state: Any) -> None:
    from app.ui.session_state import FLASHCARDS_REVIEW_RECEIPT_BASELINE_KEY

    state["flashcards_review_queue"] = []
    state["flashcards_review_index"] = 0
    state["flashcards_card_flipped"] = False
    state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    state["flashcards_review_session_status"] = "idle"
    state["flashcards_review_session_error"] = None
    state["flashcards_review_session_loaded_at"] = None
    state["flashcards_review_session_next_review_min"] = None
    # Namespaces the interactive card's sessionStorage flip flag (per-cardId
    # key) so a stale "already flipped" flag from a previous queue load can
    # never leak onto the same card reappearing after a fresh load.
    state["flashcards_review_queue_nonce"] = int(state.get("flashcards_review_queue_nonce", 0)) + 1
    state.pop("flashcards_review_last_action", None)
    state.pop(FLASHCARDS_REVIEW_RECEIPT_BASELINE_KEY, None)


def _seed_review_scope(deck_id: int | None) -> None:
    st.session_state["flashcards_review_session_deck_id"] = deck_id
    st.session_state.pop("flashcards_review_session_deck_label", None)
    st.session_state["flashcards_review_deck_sync_pending"] = deck_id
    _reset_review_session_state(st.session_state)


def _deck_progress_ratio(progress: dict[str, Any] | None) -> float:
    if not progress:
        return 0.0
    try:
        return max(0.0, min(1.0, float(progress.get("percent", 0.0)) / 100.0))
    except (TypeError, ValueError):
        return 0.0


def _deck_head(title: str, subtitle: str = "", color_class: str = "fc") -> str:
    sub = f"<p style='margin:0.25rem 0 0;font-size:0.85rem;opacity:0.85'>{subtitle}</p>" if subtitle else ""
    return (
        f'<div class="home-dash-card">'
        f'<div class="home-dash-head home-dash-head-{color_class}">'
        f"<h3>{title}</h3>{sub}</div>"
        f'<div class="home-dash-body">'
    )


def _deck_tail() -> str:
    return "</div></div>"


def _badge(text: str, color: str = "#b95631") -> str:
    return (
        f'<span style="background:{color};color:#fff;border-radius:10px;'
        f'padding:2px 10px;font-size:0.78rem;font-weight:700">{text}</span>'
    )


def _go(view: str, **extra) -> None:
    """Navigate to a flashcard subview."""
    st.session_state["flashcards_subview"] = view
    if view == "review_from_deck":
        st.session_state[_pending_section_key()] = FC_MAIN_SECTION_REVIEW
    for k, v in extra.items():
        st.session_state[k] = v
    st.rerun()


@st.cache_data(show_spinner=False)
def _cached_anki_apkg(deck_id: int, deck_updated: str | None) -> tuple[bytes | None, str | None]:
    """Локальная сборка .apkg без HTTP; deck_updated — сброс кэша при правках колоды."""
    from app.flashcard_service import export_deck_to_anki

    return export_deck_to_anki(deck_id)


# ─────────────────────────────────────────────────────────────
# Top-level tab
# ─────────────────────────────────────────────────────────────

def _render_flashcards_tab() -> None:
    _apply_pending_flashcards_section()
    _apply_e2e_section_override()

    subview = st.session_state.get("flashcards_subview", "decks")
    deck_id = st.session_state.get("flashcards_active_deck_id")

    # Bootstrap — один запрос вместо due/count + /decks (кэш shared с review_view)
    try:
        due_n = flashcards_bootstrap()["due_count"]
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        due_n = 0

    # Текст опций radio должен быть стабильным между rerun: иначе при смене due_n
    # Streamlit может сбросить выбор на первую опцию (эффект «вылета» на 2-й карточке).
    _fc_section_order, _fc_section_labels = _section_order_and_labels()
    st.markdown('<div data-testid="e2e-fc-main-section"></div>', unsafe_allow_html=True)
    active_section = st.radio(
        "flashcards_hub_section",
        options=_fc_section_order,
        format_func=lambda k: _fc_section_labels[k],
        horizontal=True,
        key="flashcards_main_section",
        label_visibility="collapsed",
    )
    st.caption(f"Карточек к повторению (все колоды): {due_n}")
    st.markdown(f'<div data-testid="e2e-fc-active-section">{active_section}</div>', unsafe_allow_html=True)
    nav_decks, nav_create, nav_review = st.columns(3)
    with nav_decks:
        if st.button("🗂 Колоды", key="fc_nav_decks", width='stretch'):
            _set_flashcards_section(FC_MAIN_SECTION_DECKS)
    with nav_create:
        if st.button("✨ Создать", key="fc_nav_create", width='stretch'):
            _set_flashcards_section(FC_MAIN_SECTION_CREATE)
    with nav_review:
        if st.button("🔁 Повторение", key="fc_nav_review", width='stretch'):
            _set_flashcards_section(FC_MAIN_SECTION_REVIEW)

    try:
        from app.ui.resume_cards import (
            gather_smart_study_router_session_context,
            render_smart_study_router_strip_from_session_context,
        )

        _ix_fc = st.session_state.get("_ui_index_stats_tab")
        _ctx_fc = gather_smart_study_router_session_context(
            index_stats=_ix_fc if isinstance(_ix_fc, dict) else None,
            flashcard_due_n=due_n,
        )
        render_smart_study_router_strip_from_session_context(
            _ctx_fc,
            key_prefix="fc_hub_ssr",
            surface="flashcards_hub",
            emit_outcome_receipt=False,
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("flashcards hub smart study router: %s", _exc)

    if active_section == FC_MAIN_SECTION_DECKS:
        if subview == "deck_detail" and deck_id:
            _render_deck_detail(deck_id)
        else:
            _render_decks_list()
    elif active_section == FC_MAIN_SECTION_CREATE:
        _render_generate()
    else:
        _render_review()


# ─────────────────────────────────────────────────────────────
# Decks list
# ─────────────────────────────────────────────────────────────

def _render_decks_list() -> None:
    _render_decks_list_impl(
        api_call=_api,
        deck_head=_deck_head,
        deck_tail=_deck_tail,
        badge=_badge,
        go=_go,
        seed_review_scope=_seed_review_scope,
    )


# ─────────────────────────────────────────────────────────────
# Deck detail
# ─────────────────────────────────────────────────────────────

def _render_deck_detail(deck_id: int) -> None:
    _render_deck_detail_impl(
        deck_id,
        api_call=_api,
        go=_go,
        seed_review_scope=_seed_review_scope,
        cached_anki_apkg=_cached_anki_apkg,
        deck_progress_ratio=_deck_progress_ratio,
    )


# ─────────────────────────────────────────────────────────────
# Generate
# ─────────────────────────────────────────────────────────────

def _render_generate() -> None:
    _render_generate_impl(api_call=_api)


# ─────────────────────────────────────────────────────────────
# Review session
# ─────────────────────────────────────────────────────────────

_RATING_BUTTONS = [
    ("🔴 Снова", "again", 0, "#c0392b"),
    ("🟡 Трудно", "hard", 3, "#d68910"),
    ("🟢 Хорошо", "good", 4, "#1e8449"),
    ("⭐ Легко", "easy", 5, "#1a5276"),
]


def _render_review_legacy() -> None:
    # Load queue if not already loaded for this session
    queue: list[dict] = st.session_state.get("flashcards_review_queue", [])
    if not queue:
        try:
            deck_filter = st.session_state.pop("flashcards_review_deck_filter", None)
            data = _api("GET", "/flashcards/due", params={"limit": 100} if not deck_filter else {"limit": 200})
            cards = data.get("cards") or []
            if deck_filter:
                cards = [c for c in cards if c["deck_id"] == deck_filter]
            queue = cards
            st.session_state["flashcards_review_queue"] = queue
            st.session_state["flashcards_review_index"] = 0
            st.session_state["flashcards_card_flipped"] = False
            st.session_state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
            st.session_state["flashcards_review_session_next_review_min"] = None
        except Exception as e:  # noqa: BLE001 - robust UI load, report flashcards load error
            st.error(f"Не удалось загрузить карточки: {e}")
            return

    idx: int = st.session_state.get("flashcards_review_index", 0)
    total = len(queue)

    if total == 0:
        st.markdown(
            '<div class="fc-empty-state">'
            "<h3>🎉 Всё повторено!</h3>"
            "<p>Нет карточек к повторению прямо сейчас. Расписание само напомнит, когда придёт время.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Обновить", width='stretch'):
            st.session_state["flashcards_review_queue"] = []
            st.rerun()
        return

    # ── Session finished ──
    if idx >= total:
        stats = st.session_state.get("flashcards_review_stats", {})
        nr_min = st.session_state.get("flashcards_review_session_next_review_min")
        st.markdown(
            _review_summary_html(stats, total, nr_min if isinstance(nr_min, str) else None),
            unsafe_allow_html=True,
        )
        if st.button("🔁 Начать снова", width='stretch', type="primary"):
            st.session_state["flashcards_review_queue"] = []
            st.rerun()
        return

    card = queue[idx]
    flipped: bool = st.session_state.get("flashcards_card_flipped", False)

    # Progress bar
    st.progress(idx / total, text=f"Карточка {idx + 1} из {total}")

    # ── Card display ──
    deck_name = card.get("deck_name", "")
    tags = card.get("tags") or ""

    tags_html = f'<div class="fc-card-tags">{tags}</div>' if tags else ""
    st.markdown(
        f'<div class="flashcard flashcard-front">'
        f'<div class="fc-card-label">Вопрос · {deck_name}</div>'
        f'<div class="fc-card-text">{card["front"]}</div>'
        f"{tags_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if flipped:
        st.markdown(
            f'<div class="flashcard flashcard-back">'
            f'<div class="fc-card-label">Ответ</div>'
            f'<div class="fc-card-text">{card["back"]}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        # Rating buttons
        cols = st.columns(4)
        for col, (label, q_label, quality, _color) in zip(cols, _RATING_BUTTONS):
            with col:
                if st.button(label, key=f"rate_{q_label}_{idx}", width='stretch'):
                    try:
                        result = _api(
                            "POST",
                            "/flashcards/review",
                            json={"card_id": card["id"], "quality": quality},
                        )
                    except Exception as e:  # noqa: BLE001 - robust UI action, report card rating save error
                        st.error(f"Не удалось сохранить оценку: {e}")
                    else:
                        _merge_session_min_next_review(
                            st.session_state,
                            result.get("next_review") if isinstance(result, dict) else None,
                        )
                        stats = st.session_state.get("flashcards_review_stats", {})
                        stats[q_label] = stats.get(q_label, 0) + 1
                        st.session_state["flashcards_review_stats"] = stats
                        st.session_state["flashcards_review_index"] = idx + 1
                        st.session_state["flashcards_card_flipped"] = False
                        st.rerun()
    else:
        if st.button("👁 Показать ответ", width='stretch', type="primary", key=f"flip_{idx}"):
            st.session_state["flashcards_card_flipped"] = True
            st.rerun()

    # SM-2 hint
    interval = card.get("interval_days", 0)
    reps = card.get("repetitions", 0)
    if reps == 0:
        hint = "🆕 Новая карточка"
    elif interval <= 1:
        hint = "🔴 Интервал: 1 день"
    elif interval <= 7:
        hint = f"🟡 Интервал: {interval} дней"
    else:
        hint = f"🟢 Интервал: {interval} дней"
    st.caption(hint)


def _render_review() -> None:
    _render_review_impl(
        api_call=_api,
        seed_review_scope=_seed_review_scope,
        normalize_review_tag_selection=_normalize_review_tag_selection,
        serialize_review_tags=_serialize_review_tags,
        review_scope_signature=_review_scope_signature,
        reset_review_session_state=_reset_review_session_state,
        build_review_due_params=_build_review_due_params,
        review_summary_html=_review_summary_html,
        review_progress_ratio=_review_progress_ratio,
        merge_session_min_next_review=_merge_session_min_next_review,
    )
