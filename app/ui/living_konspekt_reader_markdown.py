"""Markdown + Mermaid rendering for Living Konspekt reader."""

from __future__ import annotations

import base64
import mimetypes
import re
from functools import lru_cache
from pathlib import Path

import streamlit as st

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
