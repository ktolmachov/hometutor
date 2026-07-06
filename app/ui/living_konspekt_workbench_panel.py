"""Workbench panels for Living Konspekt sections, memory, and term cards."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, MutableMapping

import streamlit as st

from app import workbench_service
from app.section_index import IndexedSection, parse_sections
from app.ui.helpers import format_request_error
from app.ui.living_konspekt_media import _render_media_panel, _row_section_id, _unique_document_rows

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)

AddSection = Callable[[IndexedSection, MutableMapping[str, Any] | None], bool]
MoveSection = Callable[[str, int], bool]
RemoveSection = Callable[[str], None]
RemoveRows = Callable[[set[str]], None]
ClearRows = Callable[[], None]


def _row_konspekt_label(row: dict[str, Any]) -> str:
    md_abs = str(row.get("konspekt_md_abs") or "")
    if md_abs:
        return Path(md_abs).name
    return str(row.get("konspekt_md_label") or row.get("source_label") or "непереносимый источник")


def _row_stale_status(row: dict[str, Any]) -> str | None:
    if str(row.get("portability_status") or "") == workbench_service.NON_PORTABLE:
        reason = str(row.get("resolve_error") or "источник вне data/").replace("_", " ")
        return f"непереносимый снимок: {reason}"
    md_abs = str(row.get("konspekt_md_abs") or "")
    if not md_abs:
        return None
    path = Path(md_abs)
    if not path.is_file():
        return "исходный файл не найден — используется сохранённый снимок"
    try:
        from app.section_index import _cached_parse_sections

        sections = _cached_parse_sections(path)
    except Exception:  # noqa: BLE001 - проверка дрейфа опциональна, корзина работает без неё
        return None
    for section in sections:
        if section.slug == row.get("slug") and section.line_start == row.get("line_start"):
            if section.text == str(row.get("text") or ""):
                return None
            return "раздел изменился в источнике — в корзине старый снимок"
    row_id = _row_section_id(row)
    if row_id is not None:
        try:
            from app.media_alignment import compute_section_id

            if any(compute_section_id(s) == row_id for s in sections):
                return "раздел переехал в источнике (строки сместились)"
        except Exception:  # noqa: BLE001 - compute_section_id опционален — дрейф не проверяем
            return None
    return "раздел не найден в источнике — возможно, конспект перегенерирован"


def _add_document_sections_to_workbench(
    md_abs: str,
    rows: list[dict[str, Any]],
    add_section: AddSection,
    state: MutableMapping[str, Any] | None = None,
) -> tuple[int, int]:
    representative = next((row for row in rows if str(row.get("konspekt_md_abs") or "") == md_abs), None)
    if representative is None:
        return 0, 0

    md_path = Path(md_abs)
    source_abs = Path(str(representative.get("source_abs") or md_abs))
    added = duplicates = 0
    for parsed in parse_sections(md_path):
        if not _is_bulk_document_section(parsed):
            continue
        section = IndexedSection(
            heading_text=parsed.heading_text,
            slug=parsed.slug,
            level=parsed.level,
            line_start=parsed.line_start,
            line_end=parsed.line_end,
            text=parsed.text,
            own_text=parsed.own_text,
            source_abs=source_abs,
            konspekt_md_abs=md_path,
            concept=representative.get("concept"),
        )
        if add_section(section, state):
            added += 1
        else:
            duplicates += 1
    return added, duplicates


def render_bulk_document_panel(
    rows: list[dict[str, Any]],
    *,
    add_document_sections: Callable[[str, list[dict[str, Any]]], tuple[int, int]],
    remove_rows: RemoveRows,
    clear_rows: ClearRows,
) -> None:
    documents = _unique_document_rows(rows)
    if not documents:
        return

    st.markdown("### 📥 Быстро добавить разделы")
    options = [str(row.get("konspekt_md_abs") or "") for row in documents]
    labels = {path: Path(path).name for path in options}
    selected = st.selectbox("Документ", options, format_func=lambda path: labels.get(path, path), key="living_konspekt_bulk_doc")
    cols = st.columns([2, 1, 1])
    with cols[0]:
        if st.button("➕ Добавить крупные разделы документа", key="living_konspekt_bulk_add", width="stretch"):
            try:
                added, duplicates = add_document_sections(selected, rows)
            except OSError as exc:
                st.error(f"Не удалось прочитать документ: {format_request_error(exc)}")
                return
            st.toast(f"В корзину: +{added}" + (f" · уже было: {duplicates}" if duplicates else ""), icon="📚")
            st.rerun()
    with cols[1]:
        selected_keys = {str(row.get("row_key") or "") for row in rows if str(row.get("konspekt_md_abs") or "") == selected}
        if st.button("Убрать документ", key="living_konspekt_bulk_remove_doc", width="stretch"):
            remove_rows(selected_keys)
            st.rerun()
    with cols[2]:
        if st.button("Очистить всё", key="living_konspekt_bulk_clear", width="stretch"):
            clear_rows()
            st.rerun()


def render_collected_sections(
    rows: list[dict[str, Any]],
    *,
    move_section: MoveSection,
    remove_section: RemoveSection,
) -> None:
    from app.obsidian_export import obsidian_uri, vscode_uri

    st.markdown("### Собранные разделы")
    duplicate_keys = _duplicate_heading_keys(rows)
    row_list = list(rows)
    for idx, row in enumerate(row_list):
        md_abs = str(row.get("konspekt_md_abs") or "")
        row_key = str(row.get("row_key") or f"legacy_{idx}")
        line_start = row.get("line_start")
        heading_text = str(row.get("heading_text") or "")
        with st.container(border=True):
            cols = st.columns([5, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{heading_text or '—'}**")
                st.caption(f"{_row_konspekt_label(row)} · строки {line_start}-{row.get('line_end')}")
                if (md_abs, heading_text) in duplicate_keys or _heading_ambiguous(md_abs, heading_text):
                    st.caption("⚠️ Заголовок повторяется в документе — VS Code точнее для повторяющихся заголовков.")
                stale_status = _row_stale_status(row)
                if stale_status:
                    st.caption(f"🕰 {stale_status}")
                st.write(str(row.get("text") or "")[:400])
                _render_media_panel(row)
            with cols[1]:
                if md_abs:
                    st.link_button("📄 Открыть", obsidian_uri(Path(md_abs), heading_text=heading_text), width="stretch")
                    st.link_button("🖥 VS Code", vscode_uri(Path(md_abs), line=int(line_start) if line_start else None), width="stretch")
            with cols[2]:
                move_cols = st.columns(2)
                with move_cols[0]:
                    if st.button("↑", key=f"wb_move_up_{row_key}", disabled=idx == 0, help="Поднять раздел выше", width="stretch"):
                        move_section(row_key, -1)
                        st.rerun()
                with move_cols[1]:
                    if st.button("↓", key=f"wb_move_down_{row_key}", disabled=idx >= len(row_list) - 1, help="Опустить раздел ниже", width="stretch"):
                        move_section(row_key, 1)
                        st.rerun()
            with cols[3]:
                if st.button("🗑 Убрать", key=f"wb_remove_{row_key}", width="stretch"):
                    remove_section(row_key)
                    st.rerun()


def render_memory_panel(rows: list[dict[str, Any]]) -> None:
    entries = [(doc_name, tag, due) for doc_name, tag, due in _due_by_document(rows) if due > 0]
    if not entries:
        return
    st.markdown("### 🧠 Память конспекта")
    st.caption("Карточки из этих конспектов ждут повторения — забытое подсвечивается здесь само.")
    for doc_name, tag, due in entries:
        mem_cols = st.columns([4, 2])
        with mem_cols[0]:
            st.markdown(f"**{doc_name}** — {due} карточк(и) к повторению")
        with mem_cols[1]:
            if st.button("🔁 Повторить", key=f"wb_review_{tag}", width="stretch"):
                _open_flashcard_review(tag, due)
                st.rerun()


def render_term_cards_panel(rows: list[dict[str, Any]]) -> None:
    from app.term_cards import term_cards_from_documents

    st.markdown("### 🃏 Карточки из терминов лекции (без LLM)")
    md_paths = list(dict.fromkeys(str(row.get("konspekt_md_abs") or "") for row in rows if row.get("konspekt_md_abs")))
    cards, source_docs = term_cards_from_documents(md_paths)
    if not cards:
        st.caption("В конспектах собранных разделов нет раздела «🧠 Важные термины и концепции» — карточки собрать не из чего.")
        return
    deck_title = f"Термины — {', '.join(source_docs)}"[:120]
    st.caption(
        f"Найдено {len(cards)} терминов с определениями в {len(source_docs)} конспект(ах): "
        + ", ".join(source_docs)
        + ". Карточки собираются без нового LLM-вызова: front/back берутся из уже сохранённого конспекта."
    )
    if len(cards) < 5:
        st.caption(f"Для сохранения колоды нужно минимум 5 карточек, сейчас найдено {len(cards)}. Добавьте в корзину разделы из других конспектов с терминами.")
        return
    if st.button("🃏 Создать карточки из терминов", key="wb_term_cards_btn", type="primary"):
        _open_flashcard_create(cards, deck_title, ", ".join(source_docs))
        st.rerun()


def _duplicate_heading_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("konspekt_md_abs") or ""), str(row.get("heading_text") or ""))
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _heading_ambiguous(md_abs: str, heading_text: str) -> bool:
    if not md_abs or not heading_text:
        return False
    try:
        from app.section_index import heading_repeats_in_document

        return heading_repeats_in_document(Path(md_abs), heading_text)
    except Exception:  # noqa: BLE001 - подпись о дублях не должна ломать рендер корзины
        return False


def _is_bulk_document_section(section: Any) -> bool:
    if section.level != 2 or not section.text.strip():
        return False
    return _SLUG_RE.sub(" ", section.heading_text.strip().lower()).strip() not in {"оглавление", "содержание", "toc"}


def _due_by_document(rows: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    from app.term_cards import source_tag_value

    out: list[tuple[str, str, int]] = []
    for md in dict.fromkeys(str(row.get("konspekt_md_abs") or "") for row in rows if row.get("konspekt_md_abs")):
        tag = f"source:{source_tag_value(Path(md))}"
        try:
            from app import user_state

            due = int(user_state.count_due_flashcards(tags=tag))
        except Exception:  # noqa: BLE001 - память опциональна, корзина работает и без БД
            continue
        out.append((Path(md).name, tag, due))
    return out


def _open_flashcard_review(tag: str, due: int) -> None:
    from app.ui.flashcards_sections import FC_MAIN_SECTION_REVIEW, pending_section_key
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    st.session_state["flashcards_review_session_deck_id"] = None
    st.session_state["flashcards_review_deck_sync_pending"] = None
    st.session_state["flashcards_review_session_tags_text"] = tag
    st.session_state["flashcards_review_session_tag_ids"] = [tag]
    st.session_state["flashcards_review_queue"] = []
    st.session_state["flashcards_review_index"] = 0
    st.session_state["flashcards_card_flipped"] = False
    st.session_state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    st.session_state["flashcards_review_session_status"] = "idle"
    st.session_state["flashcards_review_session_error"] = None
    st.session_state.pop("flashcards_review_session_scope_signature", None)
    st.session_state[pending_section_key()] = FC_MAIN_SECTION_REVIEW
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
    try:
        from app.ui_events import track_event

        track_event("living_konspekt_review_loop_opened", {"due": due})
    except Exception:  # noqa: BLE001 - аналитика не должна ломать переход к повторению
        pass


def _open_flashcard_create(cards: list[dict[str, Any]], deck_title: str, source_docs: str) -> None:
    from app.ui.flashcards_sections import FC_MAIN_SECTION_CREATE, pending_section_key
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    _clear_flashcards_preview_widget_state()
    st.session_state["fc_preview_cards"] = cards
    st.session_state["fc_preview_title"] = deck_title
    st.session_state["fc_deck_name"] = deck_title
    st.session_state["fc_preview_source_type"] = "living_konspekt_terms"
    st.session_state["fc_preview_source_identifier"] = source_docs
    st.session_state[pending_section_key()] = FC_MAIN_SECTION_CREATE
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
    try:
        from app.ui_events import track_event

        track_event("living_konspekt_term_cards_created", {"cards": len(cards)})
    except Exception:  # noqa: BLE001 - аналитика не должна ломать создание карточек
        pass


def _clear_flashcards_preview_widget_state() -> None:
    stale_prefixes = ("prev_f_", "prev_b_", "prev_t_")
    for key in list(st.session_state.keys()):
        if key == "fc_deck_name" or (isinstance(key, str) and key.startswith(stale_prefixes)):
            st.session_state.pop(key, None)
