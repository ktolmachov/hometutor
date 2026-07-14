"""Режим чтения Живого конспекта: собранный документ читается ЗДЕСЬ, а не только в vault.

До этого корзина показывала превью в 400 символов, а полный текст жил только в
сохранённом файле — «живой» конспект нельзя было прочитать живьём. Reader рендерит
сборку прямо во вкладке: главные мысли лекций → разделы по порядку (полный текст +
медиа-панель с таймкодами) → «Проверь себя».

Медиа-рендер приходит DI-параметром (``media_renderer``): reader не импортирует
``living_konspekt_view`` (view импортирует reader — без цикла), а тесты передают
заглушку и проверяют чистую сборку.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Callable, Mapping

import streamlit as st

MediaRenderer = Callable[[dict[str, Any], bool], None]
SaveNote = Callable[[str, str], None]
MarkRead = Callable[[str], None]
TOC_THRESHOLD = 8


def _reader_anchor(index: int) -> str:
    return f"lk-reader-{index + 1}"


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
    """Отрендерить собранный конспект как документ для чтения."""
    if not rows:
        st.info("Разделов пока нет — добавьте их во вкладке «🧩 Разделы».")
        return

    from app.ui.living_konspekt_view import _check_questions_block, _lecture_main_ideas

    for doc_name, idea in _lecture_main_ideas(rows):
        st.markdown(f"> **Главная мысль ({doc_name}):** {idea}")

    # B2: derived novelty for the whole сборка (доля концептов ниже порога)
    try:
        from app.quiz_adaptive import get_all_mastery_levels, mastery_percent_for_level
        concepts = [str(r.get("concept") or "").strip() for r in rows if r.get("concept")]
        unique = list(dict.fromkeys([c for c in concepts if c]))  # unique preserve order
        if unique:
            levels = get_all_mastery_levels()
            low = sum(1 for c in unique if mastery_percent_for_level(levels.get(c, "recognition")) < 60)
            n = len(unique)
            if low > 0:
                pct = round(low / n * 100)
                st.caption(f"🆕 Нового для тебя ~{pct}% ({low} из {n} концептов в сборке)")
    except Exception:  # noqa: BLE001
        pass

    toc = reader_toc(rows)
    if toc:
        st.markdown("### Оглавление")
        toc_lines = [
            f"- [{item['label']}](#{item['anchor']})"
            + (f" · {item['source']}" if item.get("source") else "")
            for item in toc
        ]
        st.markdown("\n".join(toc_lines))
        st.divider()

    for index, row in enumerate(rows):
        heading = str(row.get("heading_text") or "Без названия")
        source = Path(str(row.get("konspekt_md_abs") or "")).name
        meta_text = f"{source} · строки {row.get('line_start')}-{row.get('line_end')}"
        # A1: rubric in reader source caption (plan)
        try:
            from app.konspekt_discovery import get_konspekt_quality_rubric
            md_abs = row.get("konspekt_md_abs")
            if md_abs:
                r = get_konspekt_quality_rubric(md_abs)
                if r and r.get("average") is not None:
                    meta_text += f" · рубрика {r['average']}/5"
        except Exception:  # noqa: BLE001
            pass

        # B2: derived «нового для тебя ~N%» (per plan: доля концептов раздела с mastery ниже порога)
        try:
            from app.quiz_adaptive import get_all_mastery_levels, mastery_percent_for_level
            c = str(row.get("concept") or "").strip()
            if c:
                levels = get_all_mastery_levels()
                lvl = levels.get(c, "recognition")
                pct = mastery_percent_for_level(lvl)
                if pct < 60:  # threshold как в get_weak_concepts
                    novelty = 100 - pct
                    meta_text += f" · нового для тебя ~{novelty}%"
        except Exception:  # noqa: BLE001
            pass

        # C1: грейд фабрики (derived от ролей)
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

        st.markdown(f"<span id='{_reader_anchor(index)}'></span>", unsafe_allow_html=True)
        st.markdown(f"## {heading}")
        st.caption(meta_text)

        # A1: раскрытие рубрики по клику (в reader)
        try:
            from app.konspekt_discovery import get_konspekt_quality_rubric
            md_abs = row.get("konspekt_md_abs")
            if md_abs:
                r = get_konspekt_quality_rubric(md_abs)
                if r and r.get("items"):
                    with st.expander(f"📋 Рубрика качества ({r.get('average')}/5)", expanded=False):
                        for crit, sc, mx, comm in r["items"]:
                            if "проверка точности" in crit.lower() or "accuracy" in crit.lower():
                                # C3: special visual for accuracy_check role / проверка точности
                                st.markdown(f"**🔍 {crit}**: {sc}/{mx} — {comm or '—'}")
                            else:
                                st.caption(f"**{crit}**: {sc}/{mx} — {comm or '—'}")
        except Exception:
            pass

        with st.expander("Содержимое раздела", expanded=False):
            md_abs = row.get("konspekt_md_abs")
            doc_dir = Path(md_abs).parent if md_abs else None
            render_markdown_with_mermaid(str(row.get("text") or ""), doc_dir=doc_dir)
            if media_renderer is not None:
                media_renderer(row, False)
            row_key = str(row.get("row_key") or "")
            if row_key and (save_note is not None or mark_read is not None):
                _render_section_progress_controls(
                    row,
                    save_note=save_note,
                    mark_read=mark_read,
                    mark_listened=mark_listened,
                    set_status=set_status,
                    set_question=set_question,
                )
        st.divider()


    questions = _check_questions_block(rows)
    if questions:
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
    """A2: knowledge status (3 buttons + соседство «Прочитано») + open_question field (konspekt_quality_plan).

    read_at is updated as date of last status (plan A2.2) and by the "Прочитано" button.
    mark_read remains fully functional.
    """
    row_key = str(row.get("row_key") or "")
    note_value = str(row.get("note") or "")
    read_at = str(row.get("read_at") or "")
    listened_at = str(row.get("listened_at") or "")
    current_status = row.get("knowledge_status")
    current_q = str(row.get("open_question") or "")
    note_key = f"lk_reader_note_{row_key}"
    q_key = f"lk_reader_open_q_{row_key}"

    st.text_area("Моя мысль", value=note_value, key=note_key, height=90)

    # A2: open question field
    q_val = st.text_input("Мой вопрос", value=current_q, key=q_key, placeholder="Что осталось неясным?")
    if set_question and st.button("Сохранить вопрос", key=f"lk_save_q_{row_key}", width="stretch"):
        set_question(row_key, st.session_state.get(q_key) or None)
        st.toast("Вопрос сохранён.", icon="❓")
        st.rerun()

    # B1: кнопка «Спросить тьютора» у открытого вопроса + префилл (konspekt_quality_plan)
    if current_q and set_question:
        col_tutor, col_close = st.columns(2)
        with col_tutor:
            if st.button("Спросить тьютора", key=f"lk_ask_tutor_{row_key}", width="stretch"):
                try:
                    from app.ui.continuity_bridge import store_qa_tutor_handoff_context
                    import streamlit as st2
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
                        st2.session_state["tutor_pending_prompt"] = current_q[:240]
                        # Store row key for "close after answer" CTA (B1)
                        st2.session_state["pending_living_konspekt_close_row"] = row_key
                        st2.session_state["current_view"] = "Тьютор"
                        st2.rerun()
                except Exception:  # noqa: BLE001
                    st.toast("Не удалось открыть тьютора. Перейдите во вкладку «Тьютор» вручную.", icon="⚠️")
        with col_close:
            if st.button("Закрыть вопрос", key=f"lk_close_q_{row_key}", width="stretch"):
                set_question(row_key, None)
                st.toast("Вопрос закрыт.", icon="✅")
                st.rerun()

    # A2: three status buttons (соседство с «Прочитано» per plan)
    cols = st.columns(5)
    with cols[0]:
        if st.button("Понял", key=f"lk_status_understood_{row_key}", width="stretch", disabled=set_status is None):
            set_status(row_key, "understood")
            st.toast("Статус: Понял", icon="✅")
            st.rerun()
    with cols[1]:
        if st.button("Сомневаюсь", key=f"lk_status_unsure_{row_key}", width="stretch", disabled=set_status is None):
            set_status(row_key, "unsure")
            st.toast("Статус: Сомневаюсь", icon="🤔")
            st.rerun()
    with cols[2]:
        if st.button("Не понял", key=f"lk_status_unclear_{row_key}", width="stretch", disabled=set_status is None):
            set_status(row_key, "unclear")
            st.toast("Статус: Не понял", icon="❓")
            st.rerun()
    with cols[3]:
        if st.button("Прочитано", key=f"lk_reader_mark_read_{row_key}", width="stretch", disabled=mark_read is None):
            # Restore legacy "Прочитано" button (critical regression fix)
            mark_read(row_key)
            st.toast("Фрагмент отмечен как прочитанный.", icon="✅")
            st.rerun()
    with cols[4]:
        if st.button("Сохранить мысль", key=f"lk_reader_save_note_{row_key}", width="stretch", disabled=save_note is None):
            save_note(row_key, str(st.session_state.get(note_key) or ""))
            st.toast("Мысль сохранена.", icon="💬")
            st.rerun()

    # legacy + new receipts
    meta = []
    if read_at:
        meta.append(f"Прочитано: {read_at}")
    if listened_at:
        meta.append(f"Прослушано: {listened_at}")
    if current_status:
        status_label = {"understood": "Понял", "unsure": "Сомневаюсь", "unclear": "Не понял"}.get(current_status, current_status)
        meta.append(f"Статус: {status_label}")
    if meta:
        st.caption(" · ".join(meta))


_MERMAID_RE = re.compile(r"```(?:mermaid|flowchart).*?\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_MERMAID_PATH = Path(__file__).resolve().parent / "assets" / "mermaid.min.js"


@lru_cache(maxsize=1)
def _load_mermaid_source() -> str:
    try:
        return _MERMAID_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _mermaid_script_tag() -> str:
    source = _load_mermaid_source()
    if source:
        return f"<script>{source}</script>"
    return '<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'


import base64
import mimetypes


# Кэш base64-data-URI локальных картинок по (resolved path, mtime, size).
# До этого 12 PNG (6,4 МБ) перекодировались в base64 при каждом rerun и для каждой
# вкладки — десятки мегабайт чтения/кодирования за клик. Картинка неизменна, пока
# не изменится файл → инвалидируется автоматически по mtime/size.
_IMAGE_B64_CACHE: dict[tuple[str, float, int], str] = {}


def _resolve_local_images(text: str, doc_dir: Path | None) -> str:
    if not text:
        return text

    def replacer(match: re.Match) -> str:
        alt = match.group(1)
        path_str = match.group(2).strip()

        # Skip web links and base64
        if path_str.startswith(("http://", "https://", "data:")):
            return match.group(0)

        # Resolve path
        if doc_dir:
            img_path = (doc_dir / path_str).resolve()
        else:
            img_path = Path(path_str).resolve()

        if img_path.is_file():
            try:
                resolved = str(img_path)
                stat = img_path.stat()
                cache_key = (resolved, stat.st_mtime, stat.st_size)
                cached = _IMAGE_B64_CACHE.get(cache_key)
                if cached is not None:
                    return f"![{alt}]({cached})"
                mime_type, _ = mimetypes.guess_type(resolved)
                if not mime_type:
                    mime_type = "image/png"
                data = img_path.read_bytes()
                b64_data = base64.b64encode(data).decode("utf-8")
                data_uri = f"data:{mime_type};base64,{b64_data}"
                _IMAGE_B64_CACHE[cache_key] = data_uri
                return f"![{alt}]({data_uri})"
            except Exception:
                pass
        return match.group(0)

    img_re = re.compile(r"!\[(.*?)\]\((.*?)\)")
    return img_re.sub(replacer, text)


def render_markdown_with_mermaid(text: str, doc_dir: Path | None = None) -> None:
    """Render markdown text, rendering any embedded flowchart/mermaid block as an interactive SVG."""
    if not text:
        return
    text = _resolve_local_images(text, doc_dir)
    last_idx = 0
    for match in _MERMAID_RE.finditer(text):
        start, end = match.span()
        if start > last_idx:
            st.markdown(text[last_idx:start])
        code = match.group(1).strip()
        _render_mermaid_diagram(code)
        last_idx = end
    if last_idx < len(text):
        st.markdown(text[last_idx:])


def _render_mermaid_diagram(code: str) -> None:
    lines = [line for line in code.splitlines() if line.strip()]
    is_lr = "LR" in code.upper()
    num_lines = len(lines)
    if is_lr:
        height = max(180, min(500, 150 + num_lines * 25))
    else:
        height = max(250, min(800, 200 + num_lines * 45))

    mermaid_script_tag = _mermaid_script_tag()
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                background-color: transparent;
                margin: 0;
                padding: 0;
                overflow: hidden;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                font-family: system-ui, -apple-system, sans-serif;
            }}
            .mermaid {{
                display: flex;
                justify-content: center;
                align-items: center;
                margin: 0 auto;
                width: 100%;
                height: 100%;
            }}
        </style>
    </head>
    <body>
        <div class="mermaid">
{code}
        </div>
        {mermaid_script_tag}
        <script>
            const mermaidApi = window.mermaid
                || window.__esbuild_esm_mermaid_nm?.mermaid?.default
                || window.__esbuild_esm_mermaid_nm?.mermaid;
            if (mermaidApi) {{
                mermaidApi.initialize({{
                startOnLoad: false,
                theme: 'default',
                securityLevel: 'loose',
                flowchart: {{
                    useWidth: true,
                    htmlLabels: true
                }}
                }});
                function draw() {{
                    if (window.innerWidth > 0 && window.innerHeight > 0) {{
                        mermaidApi.run();
                    }} else {{
                        setTimeout(draw, 50);
                    }}
                }}
                draw();
            }} else {{
                const target = document.querySelector('.mermaid');
                if (target) {{
                    target.textContent = 'Mermaid renderer unavailable.';
                    target.style.color = '#b91c1c';
                    target.style.fontFamily = 'system-ui, -apple-system, sans-serif';
                }} else {{
                    document.body.textContent = 'Mermaid renderer unavailable.';
                }}
            }}
        </script>
    </body>
    </html>
    """
    import streamlit.components.v1 as components
    components.html(html_code, height=height, scrolling=True)
