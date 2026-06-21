"""Decks and deck-detail views for Flashcards hub."""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from app.ui.flashcards_read_cache import (
    flashcards_decks_list,
    invalidate_flashcards_due_counts_only,
    invalidate_flashcards_read_cache,
)


def render_decks_list(
    *,
    api_call: Callable[..., Any],
    deck_head: Callable[[str, str, str], str],
    deck_tail: Callable[[], str],
    badge: Callable[[str], str],
    go: Callable[..., None],
    seed_review_scope: Callable[[int | None], None],
) -> None:
    created = st.session_state.pop("fc_quiz_deck_success_id", None)
    if created is not None:
        st.success(
            f"Колода из квиза создана (id **{created}**). Ниже в списке нажмите **Открыть** для просмотра карточек."
        )
    st.markdown("### 🗂 Мои колоды")
    st.markdown('<div data-testid="e2e-fc-jump-review-from-decks"></div>', unsafe_allow_html=True)
    if st.button("🔁 Перейти в повторение", key="fc_jump_review_from_decks", width='stretch'):
        from app.ui.flashcards_sections import FC_MAIN_SECTION_REVIEW, pending_section_key

        st.session_state[pending_section_key()] = FC_MAIN_SECTION_REVIEW
        st.rerun()
    try:
        decks = flashcards_decks_list()
    except Exception as e:  # noqa: BLE001 - UI displays API failure.
        st.error(f"Не удалось загрузить колоды: {e}")
        return

    if not decks:
        st.markdown(
            '<div class="fc-empty-state">'
            "<p>У тебя пока нет сохранённых колод.</p>"
            "<p>Перейди на вкладку <b>✨ Создать новые</b> и сгенерируй первую колоду из документа.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    for deck in decks:
        due = deck.get("due_count", 0)
        total = deck.get("card_count", 0)
        stype = deck.get("source_type") or "—"
        source = deck.get("source_id") or "—"
        due_badge = badge(f"🔁 {due} к повторению") if due else ""
        st.markdown(
            deck_head(f"📚 {deck['name']}", f"Тип: {stype} · ref: {source} · {total} карточек", "fc")
            + f'<p style="margin:0.5rem 0">{due_badge}</p>'
            + deck_tail(),
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            if st.button("Открыть", key=f"open_deck_{deck['id']}", width='stretch'):
                go("deck_detail", flashcards_active_deck_id=deck["id"])
        with c2:
            if due and st.button(
                f"Повторить ({due})", key=f"review_deck_{deck['id']}", width='stretch', type="primary"
            ):
                seed_review_scope(deck["id"])
                go("review_from_deck")
        with c3:
            if st.button("🗑", key=f"del_deck_{deck['id']}", width='stretch', help="Удалить колоду"):
                try:
                    api_call("DELETE", f"/flashcards/decks/{deck['id']}")
                    invalidate_flashcards_read_cache()
                    st.rerun()
                except Exception as e:  # noqa: BLE001 - UI displays API failure.
                    st.error(str(e))


def render_deck_detail(
    deck_id: int,
    *,
    api_call: Callable[..., Any],
    go: Callable[..., None],
    seed_review_scope: Callable[[int | None], None],
    cached_anki_apkg: Callable[[int, str | None], tuple[bytes | None, str | None]],
    deck_progress_ratio: Callable[[dict[str, Any] | None], float],
) -> None:
    try:
        deck = api_call("GET", f"/flashcards/decks/{deck_id}")
    except Exception as e:  # noqa: BLE001 - UI displays API failure.
        st.error(f"Не удалось загрузить колоду: {e}")
        return

    cards = deck.get("cards") or []
    st.markdown(f"### 📚 {deck['name']}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("← Назад к колодам", width='stretch'):
            go("decks")
    with c2:
        if st.button("🔁 Начать повторение", width='stretch', type="primary"):
            seed_review_scope(deck_id)
            go("review_from_deck")
    with c3:
        safe_name = "".join(c for c in (deck.get("name") or "deck") if c not in '<>:"/\\|?*') or "deck"
        upd = str(deck.get("updated_at") or "")
        apkg_bytes, apkg_err = cached_anki_apkg(int(deck_id), upd or None)
        if apkg_bytes and not apkg_err:
            st.download_button(
                "⬇ Anki .apkg",
                data=apkg_bytes,
                file_name=f"{safe_name}.apkg",
                mime="application/octet-stream",
                width='stretch',
                key=f"anki_dl_{deck_id}",
            )
        else:
            st.button(
                "⬇ Anki .apkg",
                disabled=True,
                width='stretch',
                help=(apkg_err or "Нет данных для экспорта"),
            )

    st.divider()

    try:
        progress = api_call("GET", f"/flashcards/decks/{deck_id}/progress")
        mastered = int(progress.get("mastered", 0))
        total = int(progress.get("total", 0))
        percent = float(progress.get("percent", 0.0))
        st.progress(
            deck_progress_ratio(progress),
            text=f"Освоено: {mastered} / {total} · Готово: {percent:.0f}%",
        )
        if total == 0:
            st.caption("В этой колоде пока нет карточек.")
        elif mastered == 0:
            st.caption("Пока нет освоенных карточек.")
    except Exception as e:  # noqa: BLE001 - UI displays API failure.
        st.warning(f"Не удалось загрузить состояние колоды: {e}")

    st.divider()

    if not cards:
        st.info("В этой колоде нет карточек.")
    else:
        for card in cards:
            with st.expander(f"**{card['front'][:80]}**", expanded=False):
                col_f, col_b = st.columns(2)
                with col_f:
                    new_front = st.text_area("Front", value=card["front"], key=f"cf_{card['id']}")
                with col_b:
                    new_back = st.text_area("Back", value=card["back"], key=f"cb_{card['id']}")
                new_tags = st.text_input("Теги", value=card.get("tags") or "", key=f"ct_{card['id']}")
                ef = card.get("easiness")
                iv = card.get("interval_days")
                reps = card.get("repetitions")
                nr = card.get("next_review")
                lv = card.get("last_review")
                st.caption(
                    f"SM-2: EF **{ef}** · интервал **{iv}** дн. · повторений **{reps}** · "
                    f"next: `{nr or '—'}` · last: `{lv or '—'}`"
                )
                sc1, sc2 = st.columns([3, 1])
                with sc1:
                    if st.button("Сохранить изменения", key=f"save_card_{card['id']}"):
                        try:
                            api_call(
                                "PUT",
                                f"/flashcards/cards/{card['id']}",
                                json={"front": new_front, "back": new_back, "tags": new_tags or None},
                            )
                            st.success("Сохранено")
                            invalidate_flashcards_due_counts_only()
                            st.rerun()
                        except Exception as e:  # noqa: BLE001 - UI displays API failure.
                            st.error(str(e))
                with sc2:
                    if st.button("🗑 Удалить", key=f"del_card_{card['id']}"):
                        try:
                            api_call("DELETE", f"/flashcards/cards/{card['id']}")
                            invalidate_flashcards_read_cache()
                            st.rerun()
                        except Exception as e:  # noqa: BLE001 - UI displays API failure.
                            st.error(str(e))

    st.divider()
    with st.expander("➕ Добавить карточку вручную"):
        nf = st.text_area("Front", key="new_card_front")
        nb = st.text_area("Back", key="new_card_back")
        nt = st.text_input("Теги", key="new_card_tags")
        if st.button("Добавить", key="add_card_btn", type="primary"):
            if nf.strip() and nb.strip():
                try:
                    api_call("POST", "/flashcards/cards", json={"deck_id": deck_id, "front": nf, "back": nb, "tags": nt or None})
                    st.success("Карточка добавлена")
                    invalidate_flashcards_read_cache()
                    st.rerun()
                except Exception as e:  # noqa: BLE001 - UI displays API failure.
                    st.error(str(e))
            else:
                st.warning("Заполни Front и Back")
