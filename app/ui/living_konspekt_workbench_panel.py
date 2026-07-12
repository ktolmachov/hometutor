"""Workbench panels for Living Konspekt sections, memory, and term cards."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, MutableMapping

import streamlit as st

from app import workbench_service
from app.llm_resilience import chat_with_resilience, complete_with_resilience
from app.prompts import build_section_diagram_messages
from app.section_index import IndexedSection, parse_sections
from app.ui.helpers import format_request_error
from app.ui.living_konspekt_media import _render_media_panel, _row_section_id, _unique_document_rows

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)
_SECTION_DIAGRAM_PREVIEW_KEY = "living_konspekt_section_diagram_preview"
_MERMAID_BLOCK_RE = re.compile(r"```(?:mermaid|flowchart)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)

AddSection = Callable[[IndexedSection, MutableMapping[str, Any] | None], bool]
MoveSection = Callable[[str, int], bool]
RemoveSection = Callable[[str], None]
RemoveRows = Callable[[set[str]], None]
ClearRows = Callable[[], None]


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text is not None:
        return str(text).strip()
    message = getattr(response, "message", None)
    content = getattr(message, "content", None)
    if content is not None:
        return str(content).strip()
    return str(response or "").strip()


def _normalize_mermaid_block(text: str) -> str:
    raw = str(text or "").strip()
    blocks = _MERMAID_BLOCK_RE.findall(raw)
    if len(blocks) == 1:
        outside = _MERMAID_BLOCK_RE.sub("", raw).strip()
        if outside:
            return ""
        code = blocks[0].strip()
    elif not blocks:
        code = raw.strip("` \n")
    else:
        return ""
    lines = [line.rstrip() for line in code.splitlines() if line.strip()]
    if not lines:
        return ""
    first = lines[0].strip().lower()
    if not (first.startswith("flowchart") or first.startswith("graph ") or first == "mindmap"):
        return ""
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def generate_section_diagram_block(row: dict[str, Any], *, llm: Any | None = None) -> str:
    """Generate and validate one Mermaid block for a Living Konspekt section."""
    section_text = str(row.get("own_text") or row.get("text") or "").strip()
    if not section_text:
        return ""
    messages = build_section_diagram_messages(
        heading=str(row.get("heading_text") or "Без заголовка"),
        section_text=section_text[:8000],
    )
    llm_eff = llm
    if llm_eff is None:
        from app.provider import get_graph_llm

        llm_eff = get_graph_llm()
    if hasattr(llm_eff, "chat"):
        response = chat_with_resilience(
            llm_eff,
            messages,
            stage="section_diagram.generate",
            max_tokens=900,
            temperature=0.1,
        )
    else:
        prompt = "\n\n".join(str(getattr(message, "content", "") or "") for message in messages)
        response = complete_with_resilience(
            llm_eff,
            prompt,
            stage="section_diagram.generate",
            max_tokens=900,
            temperature=0.1,
        )
    return _normalize_mermaid_block(_response_text(response))


def _append_diagram_to_text(text: str, diagram_block: str) -> str:
    body = str(text or "").rstrip()
    block = str(diagram_block or "").strip()
    return f"{body}\n\n{block}".strip() if body else block


def _write_diagram_to_source(row: dict[str, Any], diagram_block: str) -> None:
    md_abs = str(row.get("konspekt_md_abs") or "").strip()
    if not md_abs:
        return
    path = Path(md_abs)
    if not path.is_file():
        return
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    try:
        line_end = int(row.get("line_end") or len(lines))
    except (TypeError, ValueError):
        line_end = len(lines)
    insert_at = max(0, min(line_end, len(lines)))
    block_lines = [str(diagram_block).strip(), ""]
    if insert_at > 0 and lines[insert_at - 1].strip():
        block_lines.insert(0, "")
    updated = "\n".join([*lines[:insert_at], *block_lines, *lines[insert_at:]])
    if content.endswith("\n"):
        updated += "\n"
    path.write_text(updated, encoding="utf-8")


def accept_section_diagram_preview(
    rows: list[dict[str, Any]],
    *,
    row_key: str,
    diagram_block: str,
    write_source: bool = True,
) -> list[dict[str, Any]]:
    """Apply a confirmed section diagram to source markdown and current workbench rows."""
    normalized = _normalize_mermaid_block(diagram_block)
    if not normalized:
        return list(rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("row_key") or "") != row_key:
            out.append(row)
            continue
        if write_source:
            _write_diagram_to_source(row, normalized)
        updated = dict(row)
        updated["text"] = _append_diagram_to_text(str(updated.get("text") or ""), normalized)
        own_text = str(updated.get("own_text") or "").strip()
        if own_text:
            updated["own_text"] = _append_diagram_to_text(own_text, normalized)
        line_delta = len(normalized.splitlines()) + 2
        try:
            updated["line_end"] = int(updated.get("line_end") or 0) + line_delta
        except (TypeError, ValueError):
            pass
        out.append(updated)
    return out


def _render_section_diagram_preview_controls(row: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    from app.ui.living_konspekt_reader import render_markdown_with_mermaid
    from app.ui.living_konspekt_state import set_workbench_rows

    row_key = str(row.get("row_key") or "")
    if not row_key:
        return
    preview = st.session_state.get(_SECTION_DIAGRAM_PREVIEW_KEY)
    if not (isinstance(preview, dict) and str(preview.get("row_key") or "") == row_key):
        return
    diagram_block = str(preview.get("diagram") or "").strip()
    if not diagram_block:
        return
    st.markdown("**Предпросмотр схемы**")
    render_markdown_with_mermaid(diagram_block)
    cols = st.columns(2)
    with cols[0]:
        if st.button("Принять схему", key=f"lk_accept_diagram_{row_key}", width="stretch"):
            updated_rows = accept_section_diagram_preview(
                rows,
                row_key=row_key,
                diagram_block=diagram_block,
            )
            set_workbench_rows(updated_rows)
            st.session_state.pop(_SECTION_DIAGRAM_PREVIEW_KEY, None)
            st.toast("Схема добавлена в раздел.", icon="✓")
            st.rerun()
    with cols[1]:
        if st.button("Отклонить", key=f"lk_reject_diagram_{row_key}", width="stretch"):
            st.session_state.pop(_SECTION_DIAGRAM_PREVIEW_KEY, None)
            st.rerun()


def _render_section_diagram_button(row: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    row_key = str(row.get("row_key") or "")
    section_text = str(row.get("own_text") or row.get("text") or "").strip()
    if not row_key:
        return
    if st.button(
        "Схема раздела",
        key=f"lk_generate_diagram_{row_key}",
        width="stretch",
        disabled=not section_text,
        help="Сгенерировать Mermaid-схему и показать предпросмотр перед записью.",
    ):
        try:
            diagram = generate_section_diagram_block(row)
        except Exception as exc:  # noqa: BLE001 - provider/UI errors should not break the workbench.
            st.error(f"Не удалось сгенерировать схему: {format_request_error(exc)}")
            return
        if not diagram:
            st.warning("Модель не вернула корректный Mermaid-блок. Попробуйте ещё раз после уточнения раздела.")
            return
        st.session_state[_SECTION_DIAGRAM_PREVIEW_KEY] = {
            "row_key": row_key,
            "diagram": diagram,
        }
        st.rerun()
    _render_section_diagram_preview_controls(row, rows)


def _row_konspekt_label(row: dict[str, Any]) -> str:
    md_abs = str(row.get("konspekt_md_abs") or "")
    if md_abs:
        return Path(md_abs).name
    return str(row.get("konspekt_md_label") or row.get("source_label") or "непереносимый источник")


def deletion_options(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Stable row-key/label pairs for explicit workbench cleanup UI."""
    options: list[tuple[str, str]] = []
    for idx, row in enumerate(rows):
        row_key = str(row.get("row_key") or f"legacy_{idx}")
        heading = str(row.get("heading_text") or "Без заголовка").strip()
        doc = _row_konspekt_label(row)
        line = row.get("line_start")
        line_suffix = f":{line}" if line else ""
        options.append((row_key, f"{idx + 1}. {heading} — {doc}{line_suffix}"))
    return options


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

    st.markdown("### 📥 Быстро добавить разделы документа")
    options = [str(row.get("konspekt_md_abs") or "") for row in documents]
    labels = {path: Path(path).name for path in options}
    selected = st.selectbox("Документ", options, format_func=lambda path: labels.get(path, path), key="living_konspekt_bulk_doc")
    cols = st.columns([2, 1])
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


def render_cleanup_panel(
    rows: list[dict[str, Any]],
    *,
    remove_rows: RemoveRows,
    clear_rows: ClearRows,
) -> None:
    options = deletion_options(rows)
    if not options:
        return

    labels = dict(options)
    st.markdown("### 🧹 Очистка корзины")
    selected_keys = st.multiselect(
        "Разделы для удаления",
        [key for key, _ in options],
        format_func=lambda key: labels.get(str(key), str(key)),
        key="living_konspekt_cleanup_selected",
        placeholder="Выберите один или несколько разделов",
    )
    cols = st.columns([1, 1])
    with cols[0]:
        if st.button(
            "Убрать выбранные",
            key="living_konspekt_cleanup_remove_selected",
            width="stretch",
            disabled=not selected_keys,
        ):
            remove_rows({str(key) for key in selected_keys})
            st.toast(f"Удалено разделов: {len(selected_keys)}", icon="🧹")
            st.rerun()
    with cols[1]:
        confirm = st.checkbox(
            "Подтвердить очистку всей корзины",
            key="living_konspekt_cleanup_confirm_all",
        )
        if st.button(
            "Очистить все разделы",
            key="living_konspekt_cleanup_clear_all",
            width="stretch",
            disabled=not confirm,
        ):
            clear_rows()
            st.toast("Корзина Живого конспекта очищена.", icon="🧹")
            st.rerun()


def render_collected_sections(
    rows: list[dict[str, Any]],
    *,
    move_section: MoveSection,
    remove_section: RemoveSection,
) -> None:
    from app.obsidian_export import obsidian_uri, vscode_uri

    st.markdown("### Собранные разделы")
    if not rows:
        return

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
                badges = []
                if row.get("read_at"):
                    badges.append("✅")
                if str(row.get("note") or "").strip():
                    badges.append("📝")
                badge_str = " " + " ".join(badges) if badges else ""
                st.markdown(f"**{heading_text or '—'}**{badge_str}")
                st.caption(f"{_row_konspekt_label(row)} · строки {line_start}-{row.get('line_end')}")
                if (md_abs, heading_text) in duplicate_keys or _heading_ambiguous(md_abs, heading_text):
                    st.caption("⚠️ Заголовок повторяется в документе — VS Code точнее для повторяющихся заголовков.")
                stale_status = _row_stale_status(row)
                if stale_status:
                    st.caption(f"🕰 {stale_status}")
                with st.expander("Содержимое раздела", expanded=False):
                    from app.ui.living_konspekt_reader import render_markdown_with_mermaid
                    doc_dir = Path(md_abs).parent if md_abs else None
                    render_markdown_with_mermaid(str(row.get("text") or ""), doc_dir=doc_dir)
                    _render_media_panel(row)
                    _render_section_diagram_button(row, row_list)
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
