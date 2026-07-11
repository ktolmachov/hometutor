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
) -> None:
    """Отрендерить собранный конспект как документ для чтения."""
    if not rows:
        st.info("Разделов пока нет — добавьте их во вкладке «🧩 Разделы».")
        return

    from app.ui.living_konspekt_view import _check_questions_block, _lecture_main_ideas

    for doc_name, idea in _lecture_main_ideas(rows):
        st.markdown(f"> **Главная мысль ({doc_name}):** {idea}")

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

        st.markdown(f"<span id='{_reader_anchor(index)}'></span>", unsafe_allow_html=True)
        st.markdown(f"## {heading}")
        st.caption(meta_text)

        with st.expander("Содержимое раздела", expanded=False):
            md_abs = row.get("konspekt_md_abs")
            doc_dir = Path(md_abs).parent if md_abs else None
            render_markdown_with_mermaid(str(row.get("text") or ""), doc_dir=doc_dir)
            if media_renderer is not None:
                media_renderer(row, False)
            row_key = str(row.get("row_key") or "")
            if row_key and (save_note is not None or mark_read is not None):
                _render_section_progress_controls(row, save_note=save_note, mark_read=mark_read)
        st.divider()


    questions = _check_questions_block(rows)
    if questions:
        st.markdown(questions)



def _render_section_progress_controls(
    row: Mapping[str, Any],
    *,
    save_note: SaveNote | None,
    mark_read: MarkRead | None,
) -> None:
    row_key = str(row.get("row_key") or "")
    note_value = str(row.get("note") or "")
    read_at = str(row.get("read_at") or "")
    note_key = f"lk_reader_note_{row_key}"
    st.text_area("Моя мысль", value=note_value, key=note_key, height=90)
    cols = st.columns([1, 1, 3])
    with cols[0]:
        if st.button("Сохранить", key=f"lk_reader_save_note_{row_key}", width="stretch", disabled=save_note is None):
            save_note(row_key, str(st.session_state.get(note_key) or ""))
            st.toast("Мысль сохранена.", icon="💬")
            st.rerun()
    with cols[1]:
        if st.button("Прочитано", key=f"lk_reader_mark_read_{row_key}", width="stretch", disabled=mark_read is None):
            mark_read(row_key)
            st.toast("Фрагмент отмечен как прочитанный.", icon="✓")
            st.rerun()
    with cols[2]:
        if read_at:
            st.caption(f"Прочитано: {read_at}")


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
