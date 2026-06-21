"""
Explain и preview содержимого файлов из ``data/`` (паритет с форматами ingestion).

Итерация 16 tail: ``.html`` / ``.pdf`` / ``.docx`` + LLM-fallback при слишком коротком извлечении.
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from bs4 import BeautifulSoup

from app.prompts import EXPLAIN_FILE_PROMPT, EXPLAIN_RECOVER_TEXT_PROMPT

from app.config import DATA_DIR
from app.llm_resilience import complete_with_resilience
from app.logging_config import setup_logging
from app.path_safety import resolve_data_relative_path

logger = setup_logging()

TEXT_VIEWABLE_EXTENSIONS = {".txt", ".md", ".pdf", ".html", ".docx"}

# Меньше порога — пробуем расширенное чтение + LLM (tasklist: <100 символов).
SHORT_EXTRACT_THRESHOLD = 100
# Бюджет «сырья» для fallback-саммари (~8k токенов оценочно по символам).
FALLBACK_SOURCE_CHAR_BUDGET = 32_000


def _resolve_data_path(relative_path: str) -> Path:
    return resolve_data_relative_path(relative_path, data_dir=DATA_DIR)


def _extract_pdf_text(path: Path, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF explain requires pypdf to be installed") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    collected = 0

    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue

        remaining = max_chars - collected
        if remaining <= 0:
            break

        chunk = text[:remaining]
        parts.append(chunk)
        collected += len(chunk)

    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError(f"Could not extract text from PDF: {path.name}")
    return content


def _extract_html_text(path: Path, max_chars: int) -> str:
    raw_bytes = path.read_bytes()
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw = raw_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    compact = "\n".join(ln for ln in lines if ln)
    if not compact:
        raise ValueError(f"Could not extract text from HTML: {path.name}")
    return compact[:max_chars]


def _extract_docx_text(path: Path, max_chars: int) -> str:
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:
        raise ValueError("DOCX explain requires python-docx to be installed") from exc

    doc = DocxDocument(str(path))
    parts: list[str] = []
    n = 0
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if not t:
            continue
        sep_len = 1 if parts else 0
        if n + sep_len + len(t) > max_chars:
            rest = max_chars - n - sep_len
            if rest > 0:
                parts.append(t[:rest])
            break
        parts.append(t)
        n += sep_len + len(t)
    content = "\n".join(parts).strip()
    if not content:
        raise ValueError(f"Could not extract text from DOCX: {path.name}")
    return content


def _gather_extended_source_for_fallback(path: Path, suffix: str) -> str:
    """Больше страниц/байт для LLM-fallback при слабом первом проходе."""
    budget = FALLBACK_SOURCE_CHAR_BUDGET
    if suffix == ".pdf":
        try:
            return _extract_pdf_text(path, budget)
        except ValueError:
            return ""
    if suffix == ".html":
        try:
            raw_bytes = path.read_bytes()
            raw = raw_bytes.decode("utf-8", errors="replace")
            return raw[:budget]
        except OSError:
            return ""
    if suffix == ".docx":
        try:
            return _extract_docx_text(path, budget)
        except ValueError:
            return ""
    if suffix in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:budget]
        except OSError:
            return ""
    return ""


def _llm_fallback_plaintext(extended_source: str, relative_path: str) -> str:
    """Сжать/восстановить читаемый текст из расширенного сырья (первые ~8k токенов по бюджету)."""
    from app.provider import get_ingestion_llm

    llm = get_ingestion_llm()
    snippet = (extended_source or "").strip()
    if not snippet:
        return ""

    prompt = EXPLAIN_RECOVER_TEXT_PROMPT.format(
        relative_path=relative_path,
        snippet=snippet[:FALLBACK_SOURCE_CHAR_BUDGET],
    )
    response = complete_with_resilience(
        llm,
        prompt,
        stage="explain.recover_plaintext",
    )
    out = (getattr(response, "text", None) or str(response) or "").strip()
    if out == "(empty)":
        return ""
    return out


def _read_file_raw(path: Path, suffix: str, max_chars: int) -> str:
    if suffix == ".pdf":
        return _extract_pdf_text(path, max_chars)
    if suffix == ".html":
        return _extract_html_text(path, max_chars)
    if suffix == ".docx":
        return _extract_docx_text(path, max_chars)
    with open(path, "r", encoding="utf-8", errors="replace") as file_obj:
        return file_obj.read(max_chars)


def _read_file(relative_path: str, max_chars: int = 8000) -> str:
    path = _resolve_data_path(relative_path)

    if not path.exists() or not path.is_file():
        # Fallback: try resolving relative to the project root (BASE_DIR).
        # This allows reading doc/ files and other non-data/ project files
        # (e.g. doc/team_workflow/*.md) while still preventing path traversal.
        fallback = (BASE_DIR / relative_path).resolve()
        try:
            fallback.relative_to(BASE_DIR.resolve())
        except ValueError:
            raise FileNotFoundError(f"File not found: {relative_path}")
        if fallback.exists() and fallback.is_file():
            path = fallback
        else:
            raise FileNotFoundError(f"File not found: {relative_path}")

    suffix = path.suffix.lower()
    if suffix not in TEXT_VIEWABLE_EXTENSIONS:
        raise ValueError(
            "Explain supports only .txt, .md, .html, .pdf and .docx files"
        )

    text = _read_file_raw(path, suffix, max_chars)
    stripped = text.strip()
    if len(stripped) >= SHORT_EXTRACT_THRESHOLD:
        return text

    extended = _gather_extended_source_for_fallback(path, suffix)
    if not extended.strip():
        logger.warning(
            "explain_short_extract_no_extended | path=%s | len=%s",
            relative_path,
            len(stripped),
        )
        return text

    try:
        recovered = _llm_fallback_plaintext(extended, relative_path)
    except ValueError as exc:
        logger.warning("explain_llm_fallback_skipped | path=%s | error=%s", relative_path, exc)
        return text
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.exception("explain_llm_fallback_failed | path=%s", relative_path)
        return text

    if not recovered.strip():
        return text
    logger.info(
        "explain_llm_fallback_applied | path=%s | out_len=%s",
        relative_path,
        len(recovered),
    )
    return recovered[:max_chars]


@lru_cache(maxsize=64)
def _cached_file_content(relative_path: str, max_chars: int, mtime_ns: int) -> str:
    """Parse and return file text. mtime_ns in the key auto-invalidates when the file changes."""
    return _read_file(relative_path, max_chars=max_chars)


def get_file_content(relative_path: str, max_chars: int = 200_000) -> dict:
    """Read file content from data/ for UI preview. Results are cached per (path, mtime)."""
    path = _resolve_data_path(relative_path)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0

    t0 = time.perf_counter()
    content = _cached_file_content(relative_path, max_chars, mtime_ns)
    read_ms = round((time.perf_counter() - t0) * 1000, 1)

    logger.info(
        "file_content_served | path=%s | read_ms=%.1f | chars=%d",
        relative_path,
        read_ms,
        len(content),
    )
    return {"relative_path": relative_path, "content": content}


def explain_file(relative_path: str) -> Dict[str, Any]:
    """Generate a short explanation of the file based on its content."""
    from app.retrieval_cache import get_base_services

    content = _read_file(relative_path)

    services = get_base_services()
    llm = services["llm"]

    prompt = EXPLAIN_FILE_PROMPT.format(
        relative_path=relative_path,
        content=content,
    )

    logger.info("Explain file called | relative_path=%r", relative_path)

    try:
        response = complete_with_resilience(
            llm,
            prompt,
            stage="explain.file",
        )
        explanation_text = getattr(response, "text", str(response))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.exception("Failed to get explanation from LLM | path=%r", relative_path)
        raise

    return {
        "relative_path": relative_path,
        "content_preview": content,
        "explanation": explanation_text,
    }
