"""Local smart-konspekt generation from staged lecture materials."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

import yaml
from llama_index.core import SimpleDirectoryReader

from app.config import BASE_DIR, DATA_DIR, get_settings
from app.ingestion_sections import HTMLTextReader
from app.llm_resilience import complete_with_resilience
from app.obsidian_export import (
    REDUCE_GROUP_CHARS,
    _delete_notes_cache,
    _existing_source_hash,
    _group_by_chars,
    _load_notes_cache,
    _notes_cache_path,
    _save_notes_cache,
    _split_chunks,
    _strip_md_fence,
)
from app.prompts import (
    OBSIDIAN_EXPORT_MAP_PROMPT,
    OBSIDIAN_EXPORT_MERGE_PROMPT,
    get_smart_lecture_konspekt_universal_prompt,
)
from app.provider import get_obsidian_export_llm

ProgressFn = Callable[[str, int, int], None]


class _HTMLPlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


@dataclass(frozen=True)
class LectureInputs:
    """Classified source files for one lecture directory."""

    lecture_dir: Path
    transcripts: tuple[Path, ...]
    drafts: tuple[Path, ...]
    html_notes: tuple[Path, ...]
    presentations: tuple[Path, ...]

    @property
    def primary_transcript(self) -> Path | None:
        return self.transcripts[0] if self.transcripts else None

    @property
    def all_files(self) -> tuple[Path, ...]:
        return self.transcripts + self.drafts + self.html_notes + self.presentations


@dataclass(frozen=True)
class SmartKonspektStats:
    duration_sec: float
    llm_calls: int
    input_chars: int
    output_chars: int
    cache_used: bool


@dataclass(frozen=True)
class SmartKonspektResult:
    lecture_dir: Path
    target_abs: Path
    action: str  # "generated" | "cached"
    source_sha256: str
    stats: SmartKonspektStats


def _settings_budgets() -> dict[str, int]:
    s = get_settings()
    return {
        "transcript": s.smart_konspekt_transcript_budget,
        "draft": s.smart_konspekt_draft_budget,
        "html": s.smart_konspekt_html_budget,
        "pdf": s.smart_konspekt_pdf_budget,
    }


def resolve_lecture_dir(lecture_dir: str | Path) -> Path:
    """Resolve a materials lecture path from absolute path or ``course/lecture``."""
    raw = Path(str(lecture_dir))
    if raw.is_absolute():
        return raw.resolve()
    s = get_settings()
    return (BASE_DIR / s.obsidian_export_materials_dir / raw).resolve()


def gather_lecture_inputs(lecture_dir: str | Path) -> LectureInputs:
    """Classify files in ``materials/<course>/<lecture>/`` by input role."""
    root = resolve_lecture_dir(lecture_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Lecture materials directory not found: {root}")

    files = sorted((p for p in root.iterdir() if p.is_file()), key=lambda p: p.name.lower())
    transcripts = sorted(
        (p for p in files if p.suffix.lower() == ".txt"),
        key=lambda p: (-p.stat().st_size, p.name.lower()),
    )
    drafts = tuple(p for p in files if p.suffix.lower() in {".md", ".markdown"})
    html_notes = tuple(p for p in files if p.suffix.lower() in {".html", ".htm"})
    presentations = tuple(p for p in files if p.suffix.lower() == ".pdf")
    return LectureInputs(
        lecture_dir=root,
        transcripts=tuple(transcripts),
        drafts=drafts,
        html_notes=html_notes,
        presentations=presentations,
    )


def _extract_text(path: Path) -> str:
    """Extract plain text from one supported smart-konspekt input file."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    if suffix in {".html", ".htm"}:
        docs = HTMLTextReader().load_data(path)
        reader_text = "\n\n".join(doc.text for doc in docs).strip()
        parser = _HTMLPlainTextParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        plain_text = "\n".join(parser.parts).strip()
        return plain_text if len(plain_text) > len(reader_text) else reader_text
    if suffix == ".pdf":
        docs = SimpleDirectoryReader(input_files=[str(path)], filename_as_id=True).load_data()
        return "\n\n".join(doc.text for doc in docs).strip()
    raise ValueError(f"Unsupported smart-konspekt input: {path}")


def _load_universal_prompt() -> str:
    """Load the universal prompt through ``app.prompts``."""
    return get_smart_lecture_konspekt_universal_prompt(get_settings().obsidian_export_prompt_path)


def _clip(value: str, budget: int) -> str:
    text = (value or "").strip()
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    return text[:budget].rstrip() + "\n\n[...обрезано до бюджета контекста...]"


def _build_compose_context(
    consolidated: str,
    draft: str,
    html: str,
    pdf: str,
    *,
    budgets: dict[str, int] | None = None,
) -> str:
    """Build the signed input-materials block for universal compose."""
    b = budgets or _settings_budgets()
    sections = [
        ("## Сжатый транскрипт", _clip(consolidated, b.get("transcript", 0))),
        ("## Черновой конспект / draft.md", _clip(draft, b.get("draft", 0))),
        ("## HTML-конспект как текст", _clip(html, b.get("html", 0))),
        ("## Презентация / PDF как текст", _clip(pdf, b.get("pdf", 0))),
    ]
    parts = ["# ВХОДНЫЕ МАТЕРИАЛЫ"]
    for heading, body in sections:
        if body:
            parts.extend([heading, body])
    return "\n\n".join(parts).strip()


def _complete(llm: Any, prompt: str, *, stage: str, **kwargs: Any) -> str:
    response = complete_with_resilience(llm, prompt, stage=stage, **kwargs)
    text = getattr(response, "text", None)
    return (text if text is not None else str(response)).strip()


def _sha256_inputs(inputs: LectureInputs) -> str:
    h = hashlib.sha256()
    for path in inputs.all_files:
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _target_path(inputs: LectureInputs) -> Path:
    s = get_settings()
    materials_root = (BASE_DIR / s.obsidian_export_materials_dir).resolve()
    try:
        rel = inputs.lecture_dir.resolve().relative_to(materials_root)
    except ValueError:
        rel = Path(inputs.lecture_dir.name)
    return (DATA_DIR / rel).with_suffix(".md").resolve()


def _reduce_notes(
    llm: Any,
    notes: list[str],
    progress: ProgressFn | None,
    *,
    compose_limit: int,
    max_tokens: int,
) -> tuple[str, int]:
    """Иерархически слить map-заметки, пока не влезут в compose."""
    calls = 0
    if not notes:
        return "", calls
    level = 1
    while True:
        combined = "\n\n".join(notes)
        if len(notes) == 1 or len(combined) <= compose_limit:
            return combined, calls
        groups = _group_by_chars(notes, REDUCE_GROUP_CHARS)
        if len(groups) >= len(notes):
            logger.warning(
                "_reduce_notes: guard triggered at level %d (%d notes, total %d chars) — "
                "merge outputs exceed REDUCE_GROUP_CHARS=%d; truncating to compose_limit=%d",
                level, len(notes), len(combined), REDUCE_GROUP_CHARS, compose_limit,
            )
            return combined[:compose_limit], calls
        merged: list[str] = []
        for i, group in enumerate(groups):
            if progress:
                progress(f"merge-{level}", i + 1, len(groups))
            merged.append(
                _complete(
                    llm,
                    OBSIDIAN_EXPORT_MERGE_PROMPT.format(notes="\n\n".join(group)),
                    stage="smart_konspekt.merge",
                    max_tokens=max_tokens,
                )
            )
            calls += 1
        notes = merged
        level += 1


def _frontmatter(source_rel: str, source_hash: str, presentations: tuple[Path, ...]) -> str:
    payload: dict[str, Any] = {
        "source": source_rel,
        "source_sha256": source_hash,
        "type": "konspekt",
        "tags": ["конспект", "lecture"],
    }
    if presentations:
        payload["presentation"] = ", ".join(p.name for p in presentations)
    return "---\n" + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False) + "---\n\n"


def _strip_frontmatter(markdown: str) -> str:
    text = markdown.strip()
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + len("\n---"):].strip()


def generate_smart_konspekt(
    lecture_dir: str | Path,
    *,
    force: bool = False,
    progress: ProgressFn | None = None,
) -> SmartKonspektResult:
    """Generate a local smart konspekt into ``data/<course>/<lecture>.md``."""
    started = time.perf_counter()
    inputs = gather_lecture_inputs(lecture_dir)
    if not inputs.all_files:
        raise ValueError(f"No supported smart-konspekt inputs found in {inputs.lecture_dir}")

    target = _target_path(inputs)
    source_hash = _sha256_inputs(inputs)
    if not force and _existing_source_hash(target) == source_hash:
        stats = SmartKonspektStats(
            duration_sec=time.perf_counter() - started,
            llm_calls=0,
            input_chars=0,
            output_chars=target.stat().st_size if target.exists() else 0,
            cache_used=True,
        )
        return SmartKonspektResult(inputs.lecture_dir, target, "cached", source_hash, stats)

    target.parent.mkdir(parents=True, exist_ok=True)
    cache_used = False
    llm_calls = 0
    llm = get_obsidian_export_llm()

    consolidated = _load_notes_cache(target, source_hash)
    if consolidated is not None:
        cache_used = True
    else:
        transcript = _extract_text(inputs.primary_transcript) if inputs.primary_transcript else ""
        map_chunk, map_overlap, compose_limit, compose_max_tokens = _export_settings()
        chunks = _split_chunks(transcript, size=map_chunk, overlap=map_overlap)
        notes: list[str] = []
        for i, chunk in enumerate(chunks):
            if progress:
                progress("map", i + 1, len(chunks))
            notes.append(
                _complete(
                    llm,
                    OBSIDIAN_EXPORT_MAP_PROMPT.format(idx=i + 1, total=len(chunks), chunk=chunk),
                    stage="smart_konspekt.map",
                )
            )
            llm_calls += 1
        consolidated, reduce_calls = _reduce_notes(
            llm,
            notes,
            progress,
            compose_limit=compose_limit,
            max_tokens=compose_max_tokens,
        )
        llm_calls += reduce_calls
        _save_notes_cache(target, source_hash, consolidated)

    draft_text = "\n\n".join(_extract_text(p) for p in inputs.drafts)
    html_text = "\n\n".join(_extract_text(p) for p in inputs.html_notes)
    pdf_text = "\n\n".join(_extract_text(p) for p in inputs.presentations)
    context = _build_compose_context(consolidated, draft_text, html_text, pdf_text)
    prompt = _load_universal_prompt().rstrip() + "\n\n" + context

    if progress:
        progress("compose", 1, 1)
    _map_chunk, _map_overlap, _compose_limit, compose_max_tokens = _export_settings()
    body = _strip_frontmatter(
        _strip_md_fence(
            _complete(
                llm,
                prompt,
                stage="smart_konspekt.compose",
                max_tokens=compose_max_tokens,
            )
        )
    )
    llm_calls += 1

    source_rel = str(inputs.lecture_dir).replace("\\", "/")
    final = _frontmatter(source_rel, source_hash, inputs.presentations) + body + "\n"
    target.write_text(final, encoding="utf-8")
    _delete_notes_cache(target)

    stats = SmartKonspektStats(
        duration_sec=time.perf_counter() - started,
        llm_calls=llm_calls,
        input_chars=sum(len(_extract_text(p)) for p in inputs.all_files),
        output_chars=len(final),
        cache_used=cache_used,
    )
    return SmartKonspektResult(inputs.lecture_dir, target, "generated", source_hash, stats)


def _export_settings() -> tuple[int, int, int, int]:
    s = get_settings()
    return (
        s.obsidian_export_map_chunk_chars,
        s.obsidian_export_map_overlap_chars,
        s.obsidian_export_compose_input_limit,
        s.obsidian_export_compose_max_tokens,
    )


__all__ = [
    "LectureInputs",
    "SmartKonspektResult",
    "SmartKonspektStats",
    "gather_lecture_inputs",
    "generate_smart_konspekt",
]
