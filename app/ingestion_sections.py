"""HTML/Markdown section extraction for ingestion (split from ``app.ingestion``)."""

import re
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_HTML_HEADING_TAGS = ("h1", "h2", "h3", "h4")


class HTMLTextReader(BaseReader):
    """Читает HTML, удаляет скрипты/стили/навигацию, возвращает чистый текст."""

    STRIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript"}

    def load_data(self, file, extra_info=None):
        with open(file, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f, "html.parser")

        for tag in soup.find_all(self.STRIP_TAGS):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        metadata = extra_info or {}
        if title:
            metadata["html_title"] = title
            metadata["title"] = title

        structured_docs = _extract_html_sections(soup, metadata)
        if structured_docs:
            return structured_docs

        text = soup.get_text(separator="\n", strip=True)
        return [Document(text=text, metadata=metadata)]


# ---------------------------------------------------------------------------
# Flat Markdown reader (konspekt support)
# ---------------------------------------------------------------------------

_YAML_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)

# Flag written into metadata by FlatMarkdownReader so _expand_structured_documents
# knows NOT to re-split the file by Markdown headings.
_MD_FLAT_KEY = "_md_flat"


def _parse_md_frontmatter(text: str) -> tuple[dict, str]:
    """Strip YAML front-matter block from *text*.

    Returns ``(meta_dict, body)`` where *body* is the text with the front-matter
    removed.  If no front-matter is found, returns ``({}, text)`` unchanged.
    """
    m = _YAML_FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:  # noqa: BLE001
        meta = {}
    body = text[m.end():]
    return meta if isinstance(meta, dict) else {}, body


class FlatMarkdownReader(BaseReader):
    """Read a ``.md`` file as a single plain-text Document.

    Unlike LlamaIndex's default ``MarkdownReader``, this reader does **not** split
    by headings — the entire file body becomes one Document.  YAML front-matter is
    stripped and stored in ``doc.metadata`` with a ``md_`` prefix so downstream
    code can inspect it (e.g. ``md_type``, ``md_tags``, ``md_source``).

    The ``_md_flat=True`` flag tells ``_expand_structured_documents`` to skip the
    heading-based split for this file.
    """

    def load_data(self, file, extra_info=None):  # noqa: ANN001
        with open(file, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()

        meta, body = _parse_md_frontmatter(raw)
        metadata: dict = dict(extra_info or {})
        metadata[_MD_FLAT_KEY] = True

        # Store each front-matter field under a ``md_`` prefix.
        md_keys: list[str] = []
        for key, value in meta.items():
            mk = f"md_{key}"
            md_keys.append(mk)
            if isinstance(value, list):
                metadata[mk] = ",".join(str(v) for v in value)
            elif isinstance(value, (str, int, float, bool)):
                metadata[mk] = value
            else:
                metadata[mk] = str(value)

        doc = Document(text=body.strip(), metadata=metadata)
        # CRITICAL: front-matter (sha256, source path, tags, _md_flat) is structural
        # provenance, NOT retrieval content. Exclude it from embed/LLM text so the
        # 64-char hashes don't pollute every chunk's embedding (the whole reason we
        # strip the YAML from the body in the first place).
        excluded = [_MD_FLAT_KEY, *md_keys]
        doc.excluded_embed_metadata_keys = excluded
        doc.excluded_llm_metadata_keys = list(excluded)
        return [doc]


# ---------------------------------------------------------------------------

def _normalize_whitespace(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _split_markdown_sections(text: str, metadata: dict[str, object]) -> list[Document]:
    if not text.strip():
        return []

    sections: list[Document] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_title = metadata.get("title") or "Introduction"
    current_level = 0

    def flush_current() -> None:
        nonlocal current_lines, current_title, current_level
        body = "\n".join(line for line in current_lines if line.strip()).strip()
        if not body:
            current_lines = []
            return
        section_path_parts = heading_stack.copy() if heading_stack else [str(current_title)]
        section_path = " > ".join(section_path_parts)
        section_metadata = {
            **metadata,
            "section_title": str(current_title),
            "section_level": current_level,
            "section_path": section_path,
            "structural_path": section_path,
        }
        sections.append(Document(text=body, metadata=section_metadata))
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = _MARKDOWN_HEADING_RE.match(line.strip())
        if match:
            flush_current()
            level = len(match.group(1))
            title = _normalize_whitespace(match.group(2))
            heading_stack[:] = heading_stack[: max(level - 1, 0)]
            heading_stack.append(title)
            current_title = title
            current_level = level
            continue
        current_lines.append(line)

    flush_current()
    return sections


def _extract_html_sections(soup: BeautifulSoup, metadata: dict[str, object]) -> list[Document]:
    body = soup.body or soup
    sequence = body.find_all([*_HTML_HEADING_TAGS, "p", "li", "pre", "blockquote"])
    if not sequence:
        return []

    sections: list[Document] = []
    heading_stack: list[str] = []
    current_parts: list[str] = []
    current_title = metadata.get("title") or metadata.get("html_title") or "Introduction"
    current_level = 0

    def flush_current() -> None:
        nonlocal current_parts, current_title, current_level
        text = "\n".join(part for part in current_parts if part.strip()).strip()
        if not text:
            current_parts = []
            return
        section_path_parts = heading_stack.copy() if heading_stack else [str(current_title)]
        section_path = " > ".join(section_path_parts)
        section_metadata = {
            **metadata,
            "section_title": str(current_title),
            "section_level": current_level,
            "section_path": section_path,
            "structural_path": section_path,
        }
        sections.append(Document(text=text, metadata=section_metadata))
        current_parts = []

    for tag in sequence:
        text = _normalize_whitespace(tag.get_text(separator=" ", strip=True))
        if not text:
            continue
        if tag.name in _HTML_HEADING_TAGS:
            flush_current()
            level = int(tag.name[1])
            heading_stack[:] = heading_stack[: max(level - 1, 0)]
            heading_stack.append(text)
            current_title = text
            current_level = level
            continue
        current_parts.append(text)

    flush_current()
    return sections


def _expand_structured_documents(documents: list[Document]) -> list[Document]:
    expanded: list[Document] = []
    for doc in documents:
        metadata = dict(doc.metadata or {})
        file_path = Path(str(metadata.get("file_path", "")))
        ext = file_path.suffix.lower()
        # FlatMarkdownReader sets _md_flat=True — skip heading-based split for
        # those files so the entire document stays as one unit in the corpus.
        if ext == ".md" and not metadata.get(_MD_FLAT_KEY):
            metadata.setdefault(
                "title",
                file_path.stem.replace("_", " ").replace("-", " ").strip() or file_path.stem,
            )
            sections = _split_markdown_sections(doc.text or "", metadata)
            if sections:
                expanded.extend(sections)
                continue
        expanded.append(doc)
    return expanded