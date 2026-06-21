"""Build First Session Artifact payloads at ingest tail (Move 1 / balance plan §11.1)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from app.config import get_settings
from app.course_cache import course_scope_hash, normalize_source_paths
from app.llm_local_circuit import is_open
from app.provider import _lmstudio_api_base, get_llm, normalize_openai_compatible_api_base

logger = logging.getLogger(__name__)

RetrieveFn = Callable[[str, list[str], int], list[dict[str, Any]]]

_MAX_SEED_QUESTIONS = 3
_DEFAULT_SEED_TEMPLATES = (
    "С чего начать изучение курса «{title}»?",
    "Какие ключевые темы охватывает курс «{title}»?",
    "Какие основные понятия нужно понять в начале курса «{title}»?",
)


def _local_profile() -> str:
    s = get_settings()
    return str(getattr(s, "home_rag_local_profile", "balanced") or "balanced").strip().lower()


def _local_base_url() -> str | None:
    s = get_settings()
    raw = _lmstudio_api_base(s)
    return normalize_openai_compatible_api_base(raw) if raw else None


def _local_llm_healthy() -> bool:
    base = _local_base_url()
    if not base:
        return False
    return not is_open(base)


def should_attempt_draft_answer() -> bool:
    """Local-only draft at ingest tail; never under LOCAL_STRICT or open CB."""
    profile = _local_profile()
    if profile == "local_strict":
        return False
    if profile == "balanced" and not _local_llm_healthy():
        return False
    return profile == "balanced"


def _course_title(course_id: str) -> str:
    name = PurePosixPath(course_id.replace("\\", "/")).name
    return name or course_id


def _build_outline_blocks(source_paths: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for idx, path in enumerate(source_paths[:8], start=1):
        blocks.append(
            {
                "id": f"b{idx}",
                "title": PurePosixPath(path).stem or path,
                "source_paths": [path],
            }
        )
    return blocks


def _path_in_course_scope(relative_path: str, source_paths: list[str]) -> bool:
    rel = relative_path.replace("\\", "/").strip()
    if not rel:
        return False
    normalized = set(normalize_source_paths(source_paths))
    if rel in normalized:
        return True
    prefixes = {p.rsplit("/", 1)[0] for p in normalized if "/" in p}
    if not prefixes and source_paths:
        folder = str(source_paths[0]).replace("\\", "/").split("/", 1)[0]
        prefixes.add(folder)
    return any(rel == pref or rel.startswith(f"{pref}/") for pref in prefixes)


def _retrieval_trace_from_hits(hits: list[dict[str, Any]]) -> dict[str, Any]:
    source_paths: list[str] = []
    chunk_ids: list[str] = []
    for hit in hits:
        for path in hit.get("source_paths") or []:
            p = str(path).strip()
            if p and p not in source_paths:
                source_paths.append(p)
        for cid in hit.get("chunk_ids") or []:
            c = str(cid).strip()
            if c and c not in chunk_ids:
                chunk_ids.append(c)
    return {"source_paths": source_paths, "chunk_ids": chunk_ids}


def _filter_retrieval_hits(hits: list[dict[str, Any]], source_paths: list[str]) -> list[dict[str, Any]]:
    if not source_paths:
        return list(hits)
    filtered: list[dict[str, Any]] = []
    for hit in hits:
        paths = [str(p) for p in (hit.get("source_paths") or []) if str(p).strip()]
        if any(_path_in_course_scope(p, source_paths) for p in paths):
            filtered.append(hit)
    return filtered


def _deterministic_baseline_mission(course_id: str) -> dict[str, Any]:
    title = _course_title(course_id)
    return {
        "title": f"Первая сессия: {title}",
        "primary_cta": "Выберите стартовый вопрос ниже",
        "deterministic": True,
    }


def _generate_draft_answer(question: str, retrieval_trace: dict[str, Any]) -> str | None:
    if not should_attempt_draft_answer():
        return None
    paths = retrieval_trace.get("source_paths") or []
    context = ", ".join(str(p) for p in paths[:3])
    prompt = (
        f"Кратко ответь на вопрос учебного курса (2–3 предложения): {question}\n"
        f"Источники: {context or 'не указаны'}"
    )
    try:
        llm = get_llm()
        response = llm.complete(prompt, max_tokens=180)
        text = str(getattr(response, "text", response) or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - ingest-tail draft is best-effort only.
        logger.warning("first_session_draft_skipped | error=%s", exc)
        return None


def build_first_session_artifact(
    *,
    course_id: str,
    source_paths: list[str],
    retrieve_fn: RetrieveFn,
    top_k: int = 5,
) -> dict[str, Any]:
    """Pure builder: retrieval seeds + optional local draft + deterministic mission."""
    normalized_paths = normalize_source_paths(source_paths)
    scope_hash = course_scope_hash(normalized_paths)
    title = _course_title(course_id)
    outline_blocks = _build_outline_blocks(normalized_paths)

    seed_questions: list[dict[str, Any]] = []
    for template in _DEFAULT_SEED_TEMPLATES[:_MAX_SEED_QUESTIONS]:
        question = template.format(title=title)
        raw_hits = retrieve_fn(question, normalized_paths, top_k)
        hits = _filter_retrieval_hits(raw_hits, normalized_paths)
        trace = _retrieval_trace_from_hits(hits)
        draft = _generate_draft_answer(question, trace)
        seed_questions.append(
            {
                "q": question,
                "retrieval_trace": trace,
                "draft_answer": draft,
            }
        )

    return {
        "course_id": course_id,
        "scope_hash": scope_hash,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "outline_blocks": outline_blocks,
        "seed_questions": seed_questions,
        "baseline_mission": _deterministic_baseline_mission(course_id),
        "candidate_flashcards": [],
    }
