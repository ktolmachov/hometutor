"""Ingestion status, progress lines, page-range helpers (split from ``app.ingestion``)."""

import concurrent.futures
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable

from llama_index.core.schema import QueryBundle

from app.course_cache import (
    list_course_candidates,
    normalize_source_paths,
    save_first_session_artifact,
)
from app.services.first_session_builder import build_first_session_artifact

_COURSE_SOURCE_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".docx", ".html"})

_ingestion_status: dict[str, object] = {
    "status": "idle",
    "lifecycle_phase": "idle",
    "total_files": 0,
    "processed_files": 0,
    "current_file": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "ingest_run_summary": None,
}


def get_ingestion_status() -> dict[str, object]:
    return dict(_ingestion_status)


def format_ingest_progress_line(
    *,
    phase: str,
    processed: int,
    total: int,
    current: str | None,
    started_monotonic: float,
    extra: str = "",
) -> str:
    """US-2.1: стабильная строка прогресса для CLI и узких тестов (префикс INGEST_PROGRESS)."""
    elapsed = max(time.perf_counter() - started_monotonic, 1e-9)
    thr = processed / elapsed if processed else 0.0
    rem = max(0, int(total) - int(processed))
    eta_sec = int(rem / thr) if thr > 0 and rem > 0 else 0
    cur = (current or "").replace("\n", " ").replace("\r", "")[:200]
    tail = f" {extra}".rstrip() if extra else ""
    return (
        f"INGEST_PROGRESS phase={phase} processed={int(processed)} total={int(total)} "
        f"items_per_s={thr:.4f} eta_sec={eta_sec} current={cur!r}{tail}"
    )


def _ascii_console_fragment(text: str, max_len: int) -> str:
    """For tqdm/postfix on Windows cp1252 streams — avoids UnicodeEncodeError."""
    frag = (text or "")[:max_len]
    return frag.encode("ascii", errors="backslashreplace").decode("ascii")


def _print_ingest_progress(**kwargs: Any) -> None:
    line = format_ingest_progress_line(**kwargs)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Windows worker threads often use cp1252 stdout — doc paths may be non-Latin.
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, errors="replace").decode(enc), flush=True)


def build_ingest_run_summary(
    *,
    run_kind: str,
    unique_documents: int,
    source_fragments: int,
    nodes_count: int,
    partial_rebuilt_docs: int | None = None,
    partial_unchanged_docs: int | None = None,
) -> dict[str, object]:
    """E9.6 / US-2.2: структурированная сводка прогона для API/UI/CLI (без новых зависимостей)."""
    uk = str(run_kind).strip().lower()
    if uk not in {"partial", "full", "noop"}:
        uk = "full"
    ud = max(0, int(unique_documents))
    sf = max(0, int(source_fragments))
    nc = max(0, int(nodes_count))
    pr = max(0, int(partial_rebuilt_docs or 0))
    pu = max(0, int(partial_unchanged_docs or 0))
    if uk == "noop":
        human = (
            f"Индекс уже актуален: уникальных документов {ud}, "
            f"фрагментов в последнем индексе {sf}, узлов в индексе {nc}."
        )
        line = f"INGEST_SUMMARY run_kind=noop unique_docs={ud} source_fragments={sf} nodes={nc}"
    elif uk == "partial":
        human = (
            f"Частичная переиндексация: пересобрано документов {pr}, без изменений {pu}; "
            f"всего уникальных документов {ud}; фрагментов в data/ {sf}; узлов в индексе {nc}."
        )
        line = (
            f"INGEST_SUMMARY run_kind=partial unique_docs={ud} rebuilt_docs={pr} "
            f"unchanged_docs={pu} source_fragments={sf} nodes={nc}"
        )
    else:
        human = (
            f"Полная переиндексация: уникальных документов {ud}, фрагментов в data/ {sf}, узлов в индексе {nc}."
        )
        line = f"INGEST_SUMMARY run_kind=full unique_docs={ud} source_fragments={sf} nodes={nc}"
    return {
        "run_kind": uk,
        "unique_documents": ud,
        "source_fragments": sf,
        "nodes_count": nc,
        "partial_rebuilt_documents": pr if uk == "partial" else None,
        "partial_unchanged_documents": pu if uk == "partial" else None,
        "human_ru": human,
        "summary_line": line,
    }


def _print_ingest_run_summary(summary: dict[str, object]) -> None:
    sl = summary.get("summary_line")
    if isinstance(sl, str) and sl:
        print(sl, flush=True)
    hr = summary.get("human_ru")
    if isinstance(hr, str) and hr:
        print(hr, flush=True)


def normalize_page_range_string(page_label: object) -> str | None:
    """Canonical ``N-M`` page span from a LlamaIndex ``page_label`` (PDF) or similar.

    HTML/Markdown without pages: returns None. Single page ``k`` becomes ``k-k``.
    """
    if page_label is None:
        return None
    s = str(page_label).strip()
    if not s:
        return None
    if "-" in s:
        parts = s.split("-", 1)
        try:
            lo, hi = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None
        a, b = min(lo, hi), max(lo, hi)
        return f"{a}-{b}"
    try:
        n = int(s)
        return f"{n}-{n}"
    except ValueError:
        return None


def aggregate_page_range_for_doc_group(page_labels: list[object]) -> str | None:
    """Document-level span across PDF pages sharing one ``doc_id`` (for summaries)."""
    bounds: list[int] = []
    for pl in page_labels:
        r = normalize_page_range_string(pl)
        if not r:
            continue
        parts = r.split("-", 1)
        try:
            bounds.append(int(parts[0].strip()))
            if len(parts) == 2:
                bounds.append(int(parts[1].strip()))
        except ValueError:
            continue
    if not bounds:
        return None
    lo, hi = min(bounds), max(bounds)
    return f"{lo}-{hi}"


_FIRST_SESSION_CANDIDATE_TIMEOUT_SEC = 45.0


def _source_paths_for_candidate(docs_root: Path, folder_rel: str) -> list[str]:
    course_dir = docs_root / folder_rel
    if not course_dir.is_dir():
        return []
    paths: list[str] = []
    for path in sorted(course_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _COURSE_SOURCE_EXTENSIONS:
            continue
        try:
            rel = str(path.relative_to(docs_root)).replace("\\", "/")
        except ValueError:
            rel = path.name
        paths.append(rel)
    return normalize_source_paths(paths)


def build_ingest_tail_retrieve_fn() -> Callable[[str, list[str], int], list[dict[str, Any]]]:
    """Hybrid retrieval on the warm post-ingest index (no HTTP ``/ask``)."""
    from app.config import get_retrieval_settings
    from app.hybrid_retrieval import build_hybrid_retriever
    from app.retrieval_cache import get_base_services

    services = get_base_services()
    index = services["index"]
    collection = services["collection"]
    rs = get_retrieval_settings()
    default_top_k = max(1, int(getattr(rs, "similarity_top_k", 5) or 5))

    def retrieve_fn(query: str, source_paths: list[str], top_k: int) -> list[dict[str, Any]]:
        k = max(1, int(top_k or default_top_k))
        retriever = build_hybrid_retriever(index, collection, similarity_top_k=k, filters=None)
        nodes = retriever.retrieve(QueryBundle(query_str=query))
        hits: list[dict[str, Any]] = []
        for node in nodes:
            meta = getattr(node, "metadata", {}) or {}
            rel_path = str(meta.get("relative_path") or meta.get("file_path") or "").replace("\\", "/")
            chunk_id = str(meta.get("doc_id") or getattr(node, "node_id", "") or "")
            hits.append(
                {
                    "source_paths": [rel_path] if rel_path else [],
                    "chunk_ids": [chunk_id] if chunk_id else [],
                }
            )
        return hits

    return retrieve_fn


def _noop_retrieve_fn(_query: str, _source_paths: list[str], _top_k: int) -> list[dict[str, Any]]:
    return []


def _build_and_save_first_session_candidate(
    *,
    candidate: dict[str, Any],
    docs_root: Path,
    retrieve_fn: Callable[[str, list[str], int], list[dict[str, Any]]],
    logger: logging.Logger,
) -> None:
    folder_rel = str(candidate.get("folder_rel") or "").strip()
    if not folder_rel:
        return
    source_paths = _source_paths_for_candidate(docs_root, folder_rel)
    if not source_paths:
        logger.warning("first_session_precompute_skip | course_id=%s | reason=no_source_paths", folder_rel)
        return

    def _build() -> None:
        artifact = build_first_session_artifact(
            course_id=folder_rel,
            source_paths=source_paths,
            retrieve_fn=retrieve_fn,
        )
        save_first_session_artifact(folder_rel, artifact)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_build)
        try:
            future.result(timeout=_FIRST_SESSION_CANDIDATE_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "first_session_precompute_timeout | course_id=%s | timeout_sec=%s",
                folder_rel,
                _FIRST_SESSION_CANDIDATE_TIMEOUT_SEC,
            )
            raise


def run_first_session_precompute_tail(
    *,
    docs_root: Path,
    retrieve_fn: Callable[[str, list[str], int], list[dict[str, Any]]] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Non-fatal ingest tail: precompute First Session Artifact per course candidate."""
    log = logger or logging.getLogger(__name__)
    fn = retrieve_fn or _noop_retrieve_fn
    try:
        candidates = list_course_candidates(docs_root=docs_root)
    except Exception as exc:  # noqa: BLE001 - tail must never abort ingest finalize.
        log.warning("first_session_precompute_list_failed | error=%s", exc)
        return
    for candidate in candidates:
        folder_rel = str(candidate.get("folder_rel") or "").strip()
        try:
            _build_and_save_first_session_candidate(
                candidate=candidate,
                docs_root=docs_root,
                retrieve_fn=fn,
                logger=log,
            )
            log.info("first_session_precompute_ok | course_id=%s", folder_rel)
        except Exception as exc:  # noqa: BLE001 - per-candidate failure is non-fatal.
            log.warning("first_session_precompute_failed | course_id=%s | error=%s", folder_rel, exc)
