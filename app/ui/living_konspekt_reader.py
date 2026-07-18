"""Reading route Живого конспекта (W7): один открытый раздел + rail.

Сборка читается здесь (не только в vault). Маршрут: current / next / reason,
Prev|Next (Next = «прочитано» + фокус), три статуса понимания, contextual
«Сохранить мысль». Не outline из закрытых expander.

Медиа-рендер — DI (``media_renderer``): без import-цикла с view. Markdown/Mermaid —
``living_konspekt_reader_markdown``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import streamlit as st

from app.konspekt_learning_passport import build_konspekt_learning_passport_for_rows
from app.ui.living_konspekt_reader_markdown import (  # noqa: F401 — re-export for tests
    _IMAGE_B64_CACHE,
    _MERMAID_PATH,
    _load_mermaid_source,
    _mermaid_script_tag,
    _resolve_local_images,
    base64,
    render_markdown_with_mermaid,
)

MediaRenderer = Callable[[dict[str, Any], bool], None]
SaveNote = Callable[[str, str], None]
MarkRead = Callable[[str], None]
TOC_THRESHOLD = 8
READER_INDEX_KEY = "lk_reader_current_index"

STATUS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("understood", "Понял"),
    ("unsure", "Сомневаюсь"),
    ("unclear", "Не понял"),
)
STATUS_LABELS: dict[str, str] = {k: v for k, v in STATUS_OPTIONS}


def _reader_anchor(index: int) -> str:
    return f"lk-reader-{index + 1}"


def clamp_reader_index(index: int | None, n: int) -> int:
    """Keep reader index inside ``[0, n)``; empty list → 0."""
    if n <= 0:
        return 0
    try:
        i = int(index) if index is not None else 0
    except (TypeError, ValueError):
        i = 0
    return max(0, min(i, n - 1))


def default_reader_index(rows: list[dict[str, Any]]) -> int:
    """First section without ``read_at``, else 0 (route start)."""
    for i, row in enumerate(rows):
        if not str(row.get("read_at") or "").strip():
            return i
    return 0


def resolve_reader_index(
    rows: list[dict[str, Any]],
    stored: int | None,
    *,
    prefer_unread_when_missing: bool = True,
) -> int:
    """Session index if set; otherwise first unread (W7 reading route)."""
    n = len(rows)
    if n <= 0:
        return 0
    if stored is None and prefer_unread_when_missing:
        return default_reader_index(rows)
    return clamp_reader_index(stored, n)


def section_route_reason(row: Mapping[str, Any] | None) -> str:
    """Short «because» for current/next stop (Memory Run grammar)."""
    if not row:
        return "конец маршрута"
    if not str(row.get("read_at") or "").strip():
        status = str(row.get("knowledge_status") or "").strip()
        if status == "unclear":
            return "ещё не ясно — стоит перечитать"
        if status == "unsure":
            return "есть сомнения — уточнить"
        return "ещё не прочитано"
    status = str(row.get("knowledge_status") or "").strip()
    if status == "understood":
        return "уже понято — можно идти дальше"
    if status == "unclear":
        return "прочитано, но неясно"
    if status == "unsure":
        return "прочитано, есть сомнения"
    return "уже в сборке"


def neighbor_indices(index: int, n: int) -> tuple[int | None, int | None]:
    """(prev, next) indices or None at ends."""
    if n <= 0:
        return None, None
    i = clamp_reader_index(index, n)
    prev_i = i - 1 if i > 0 else None
    next_i = i + 1 if i < n - 1 else None
    return prev_i, next_i


def reader_toc(rows: list[dict[str, Any]], *, threshold: int = TOC_THRESHOLD) -> list[Mapping[str, Any]]:
    """Оглавление reader-а для длинных сборок."""
    if len(rows) < threshold:
        return []
    items: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        heading = str(row.get("heading_text") or "Без названия")
        source = Path(str(row.get("konspekt_md_abs") or "")).name
        items.append({"label": heading, "source": source, "anchor": _reader_anchor(index)})
    return items


def reader_blocks(rows: list[dict[str, Any]]) -> list[Mapping[str, Any]]:
    """Чистая модель чтения: [{kind: heading|meta|body, ...}] по разделам корзины.

    Отделена от Streamlit: тесты проверяют порядок/содержимое без runtime.
    """
    blocks: list[Mapping[str, Any]] = []
    for row in rows:
        heading = str(row.get("heading_text") or "Без названия")
        source = Path(str(row.get("konspekt_md_abs") or "")).name
        blocks.append({"kind": "heading", "text": heading})
        blocks.append({"kind": "meta", "text": f"{source} · строки {row.get('line_start')}-{row.get('line_end')}"})
        blocks.append({"kind": "body", "text": str(row.get("text") or ""), "row": row})
    return blocks


def _section_source_meta(row: Mapping[str, Any]) -> str:
    """Compact address line for the open section (source · lines · optional signals)."""
    source = Path(str(row.get("konspekt_md_abs") or "")).name
    meta_text = f"{source} · строки {row.get('line_start')}-{row.get('line_end')}"
    try:
        from app.konspekt_discovery import get_konspekt_quality_rubric

        md_abs = row.get("konspekt_md_abs")
        if md_abs:
            r = get_konspekt_quality_rubric(md_abs)
            if r and r.get("average") is not None:
                meta_text += f" · рубрика {r['average']}/5"
    except Exception:  # noqa: BLE001 - optional discovery signals
        pass
    try:
        from app.quiz_adaptive import get_all_mastery_levels, mastery_percent_for_level

        c = str(row.get("concept") or "").strip()
        if c:
            levels = get_all_mastery_levels()
            lvl = levels.get(c, "recognition")
            pct = mastery_percent_for_level(lvl)
            if pct < 60:
                meta_text += f" · нового для тебя ~{100 - pct}%"
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.section_index import _cached_parse_sections, get_konspekt_grade

        md_abs = row.get("konspekt_md_abs")
        if md_abs:
            secs = _cached_parse_sections(Path(md_abs))
            grade = get_konspekt_grade(secs)
            if grade != "базовый":
                meta_text += f" · {grade}"
    except Exception:  # noqa: BLE001
        pass
    return meta_text


def _render_reading_rail(
    rows: list[dict[str, Any]],
    index: int,
    *,
    mark_read: MarkRead | None,
) -> None:
    """Sticky-style route chrome: current / next / reason + Prev|Next (W7)."""
    n = len(rows)
    i = clamp_reader_index(index, n)
    row = rows[i]
    prev_i, next_i = neighbor_indices(i, n)
    next_row = rows[next_i] if next_i is not None else None
    heading = str(row.get("heading_text") or "Без названия")
    next_heading = (
        str(next_row.get("heading_text") or "Без названия") if next_row else "—"
    )
    reason_here = section_route_reason(row)
    reason_next = section_route_reason(next_row)

    st.markdown(
        f'<div data-testid="e2e-lk-reader-rail" data-index="{i}" data-total="{n}"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(f"**Маршрут чтения** · {i + 1} из {n}")
    st.caption(f"Сейчас: **{heading}** · {reason_here}")
    if next_i is not None:
        st.caption(f"Дальше: **{next_heading}** · потому что: {reason_next}")
    else:
        st.caption("Дальше: конец сборки")

    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button(
            "← Назад",
            key="lk_reader_prev",
            width="stretch",
            disabled=prev_i is None,
        ):
            st.session_state[READER_INDEX_KEY] = prev_i if prev_i is not None else i
            st.rerun()
    with col_next:
        # Next = mark current as read (Прочитано) + advance focus (W7 DoD).
        next_label = "Далее → · прочитано" if next_i is not None else "Готово · прочитано"
        if st.button(
            next_label,
            key="lk_reader_next",
            type="primary",
            width="stretch",
        ):
            row_key = str(row.get("row_key") or "")
            if mark_read is not None and row_key:
                mark_read(row_key)
            if next_i is not None:
                st.session_state[READER_INDEX_KEY] = next_i
                st.toast("Раздел отмечен прочитанным · следующий.", icon="✅")
            else:
                st.session_state[READER_INDEX_KEY] = i
                st.toast("Раздел отмечен прочитанным · маршрут завершён.", icon="✅")
            st.rerun()


def render_reader(
    rows: list[dict[str, Any]],
    *,
    media_renderer: MediaRenderer | None = None,
    save_note: SaveNote | None = None,
    mark_read: MarkRead | None = None,
    mark_listened: Any = None,
    set_status: Any = None,
    set_question: Any = None,
) -> None:
    """Reading route: one open section + rail (current/next/reason), not outline expanders."""
    if not rows:
        st.info("Разделов пока нет — добавьте их во вкладке «🧩 Разделы».")
        return

    from app.ui.living_konspekt_view import _check_questions_block, _lecture_main_ideas

    for doc_name, idea in _lecture_main_ideas(rows):
        st.markdown(f"> **Главная мысль ({doc_name}):** {idea}")

    passport = build_konspekt_learning_passport_for_rows(rows)
    counts = passport["counts"]
    status_label = {"raw": "сырой", "in_progress": "в работе", "ready": "готов"}.get(
        str(passport.get("status") or ""),
        "в работе",
    )
    readiness_parts = [
        f"готовность: {status_label}",
        f"прочитано/прослушано {counts['consumed']}/{counts['sections']}",
        f"понято {counts['understood']}/{counts['sections']}",
        f"вопросов {counts['open_questions']}",
    ]
    quality = passport["quality"]
    if quality.get("rubric_average") is not None:
        readiness_parts.append(f"рубрика {quality['rubric_average']}/5")
    if passport["flags"].get("has_stale_sources"):
        readiness_parts.append("есть устаревшие источники")
    st.caption(" · ".join(readiness_parts))

    novelty = passport["novelty"]
    if not novelty.get("unknown") and novelty.get("low_mastery_concepts"):
        st.caption(
            f"🆕 Нового для тебя ~{novelty['pct']}% "
            f"({novelty['low_mastery_concepts']} из {novelty['concepts']} концептов в сборке)"
        )

    # Session index: first visit → first unread; else clamped stored index.
    stored_raw = st.session_state.get(READER_INDEX_KEY)
    if stored_raw is None:
        index = default_reader_index(rows)
        st.session_state[READER_INDEX_KEY] = index
    else:
        index = resolve_reader_index(rows, stored_raw, prefer_unread_when_missing=False)
        st.session_state[READER_INDEX_KEY] = index

    _render_reading_rail(rows, index, mark_read=mark_read)

    toc = reader_toc(rows)
    if toc:
        with st.expander("Оглавление сборки", expanded=False):
            for item_i, item in enumerate(toc):
                # TOC items align with rows when threshold met (all rows).
                label = item["label"]
                src = item.get("source") or ""
                btn_label = f"{item_i + 1}. {label}" + (f" · {src}" if src else "")
                if st.button(btn_label, key=f"lk_toc_jump_{item_i}", width="stretch"):
                    st.session_state[READER_INDEX_KEY] = item_i
                    st.rerun()

    row = rows[index]
    heading = str(row.get("heading_text") or "Без названия")
    st.markdown(f"<span id='{_reader_anchor(index)}'></span>", unsafe_allow_html=True)
    st.markdown(f"## {heading}")
    st.caption(_section_source_meta(row))

    # Secondary metadata in disclosure (W7) — not in the main reading flow.
    with st.expander("Подробности источника", expanded=False):
        try:
            from app.konspekt_discovery import get_konspekt_quality_rubric

            md_abs = row.get("konspekt_md_abs")
            if md_abs:
                r = get_konspekt_quality_rubric(md_abs)
                if r and r.get("items"):
                    st.markdown(f"**Рубрика** ({r.get('average')}/5)")
                    for crit, sc, mx, comm in r["items"]:
                        if "проверка точности" in crit.lower() or "accuracy" in crit.lower():
                            st.markdown(f"**🔍 {crit}**: {sc}/{mx} — {comm or '—'}")
                        else:
                            st.caption(f"**{crit}**: {sc}/{mx} — {comm or '—'}")
                else:
                    st.caption("Рубрика качества для файла не найдена.")
            else:
                st.caption("Путь к markdown-источнику не задан.")
        except Exception:  # noqa: BLE001
            st.caption("Метаданные источника недоступны.")
        read_at = str(row.get("read_at") or "")
        listened_at = str(row.get("listened_at") or "")
        current_status = row.get("knowledge_status")
        receipts = []
        if read_at:
            receipts.append(f"Прочитано: {read_at}")
        if listened_at:
            receipts.append(f"Прослушано: {listened_at}")
        if current_status:
            receipts.append(f"Статус: {STATUS_LABELS.get(str(current_status), current_status)}")
        if receipts:
            st.caption(" · ".join(receipts))

    # Body always open — not a closed expander (W7 critical fix).
    md_abs = row.get("konspekt_md_abs")
    doc_dir = Path(md_abs).parent if md_abs else None
    render_markdown_with_mermaid(str(row.get("text") or ""), doc_dir=doc_dir)
    if media_renderer is not None:
        media_renderer(row, index == 0)

    row_key = str(row.get("row_key") or "")
    if row_key and (save_note is not None or mark_read is not None or set_status is not None):
        _render_section_progress_controls(
            row,
            save_note=save_note,
            mark_read=mark_read,
            mark_listened=mark_listened,
            set_status=set_status,
            set_question=set_question,
        )

    questions = _check_questions_block(rows)
    if questions:
        st.divider()
        st.markdown(questions)


def _render_section_progress_controls(
    row: Mapping[str, Any],
    *,
    save_note: SaveNote | None,
    mark_read: MarkRead | None,
    mark_listened: Any = None,
    set_status: Any = None,
    set_question: Any = None,
) -> None:
    """Confidence segmented control + contextual thought; «Прочитано» is rail Next (W7)."""
    del mark_listened  # reserved for media path; listened receipts stay in disclosure
    row_key = str(row.get("row_key") or "")
    note_value = str(row.get("note") or "")
    current_status = str(row.get("knowledge_status") or "").strip()
    current_q = str(row.get("open_question") or "")
    note_key = f"lk_reader_note_{row_key}"
    q_key = f"lk_reader_open_q_{row_key}"

    # Segmented confidence (3 states only — not a 5-button row).
    st.markdown("**Понимание**")
    conf_cols = st.columns(3)
    for col, (status_key, label) in zip(conf_cols, STATUS_OPTIONS):
        is_on = current_status == status_key
        with col:
            if st.button(
                label,
                key=f"lk_status_{status_key}_{row_key}",
                type="primary" if is_on else "secondary",
                width="stretch",
                disabled=set_status is None,
            ):
                if set_status is not None:
                    set_status(row_key, status_key)
                    st.toast(f"Статус: {label}", icon="✅")
                    st.rerun()

    # Contextual «Сохранить мысль» (not in the primary action strip).
    with st.expander("Сохранить мысль", expanded=bool(note_value)):
        st.text_area("Моя мысль", value=note_value, key=note_key, height=90)
        if st.button(
            "Сохранить мысль",
            key=f"lk_reader_save_note_{row_key}",
            width="stretch",
            disabled=save_note is None,
        ):
            if save_note is not None:
                save_note(row_key, str(st.session_state.get(note_key) or ""))
                st.toast("Мысль сохранена.", icon="💬")
                st.rerun()

    with st.expander("Мой вопрос", expanded=bool(current_q)):
        st.text_input("Мой вопрос", value=current_q, key=q_key, placeholder="Что осталось неясным?")
        if set_question and st.button("Сохранить вопрос", key=f"lk_save_q_{row_key}", width="stretch"):
            set_question(row_key, st.session_state.get(q_key) or None)
            st.toast("Вопрос сохранён.", icon="❓")
            st.rerun()
        if current_q and set_question:
            col_tutor, col_close = st.columns(2)
            with col_tutor:
                if st.button("Спросить тьютора", key=f"lk_ask_tutor_{row_key}", width="stretch"):
                    try:
                        from app.ui.continuity_bridge import store_qa_tutor_handoff_context
                        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

                        src = str(row.get("konspekt_md_abs") or "")
                        hdg = str(row.get("heading_text") or "")
                        line_info = f"{row.get('line_start')}-{row.get('line_end')}"
                        topic = f"{Path(src).name} — {hdg} (строки {line_info})" if hdg else src
                        last_q = f"[{hdg}] {current_q}"
                        if store_qa_tutor_handoff_context(
                            st.session_state,
                            topic=topic,
                            last_question=last_q,
                            source="living_konspekt_open_question",
                        ):
                            st.session_state["tutor_pending_prompt"] = current_q[:240]
                            st.session_state["pending_living_konspekt_close_row"] = row_key
                            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
                            st.rerun()
                    except Exception:  # noqa: BLE001 - handoff best-effort
                        st.toast(
                            "Не удалось открыть тьютора. Перейдите в «Учиться · Тьютор» вручную.",
                            icon="⚠️",
                        )
            with col_close:
                if st.button("Закрыть вопрос", key=f"lk_close_q_{row_key}", width="stretch"):
                    set_question(row_key, None)
                    st.toast("Вопрос закрыт.", icon="✅")
                    st.rerun()

    # Optional mark-read without advancing (accessibility; primary path is rail Next).
    if mark_read is not None:
        with st.expander("Дополнительно", expanded=False):
            if st.button(
                "Отметить прочитанным без перехода",
                key=f"lk_reader_mark_read_{row_key}",
                width="stretch",
            ):
                mark_read(row_key)
                st.toast("Фрагмент отмечен как прочитанный.", icon="✅")
                st.rerun()
