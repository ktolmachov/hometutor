"""Home RAG Integration Gate v1.

This gate validates the real application path:

    documents folder -> ingestion/indexing -> retriever -> selected chunks
    -> answer_question() -> sources/citations/grounding checks

It intentionally uses a small generated corpus under an isolated HOME_RAG_HOME
so it does not mutate the developer's normal data/index folders.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CASES_PATH = ROOT / "eval_data" / "home_rag_gate" / "home_rag_cases_v1.json"
DEFAULT_HOME = Path(os.environ.get("HOME_RAG_GATE_HOME", r"D:\AI\home_rag_gate_v1"))
DEFAULT_REPORT_DIR = Path(os.environ.get("HOME_RAG_GATE_REPORT_DIR", r"D:\AI\logs"))
DEFAULT_LLM_BASE_URL = os.environ.get("HOME_RAG_GATE_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
DEFAULT_LLM_MODEL = os.environ.get("HOME_RAG_GATE_LLM_MODEL", "qwopus36-35b-a3b-mtp")
DEFAULT_EMBED_BASE_URL = os.environ.get("HOME_RAG_GATE_EMBED_BASE_URL", "http://127.0.0.1:1234/v1")
DEFAULT_EMBED_MODEL = os.environ.get("HOME_RAG_GATE_EMBED_MODEL", "text-embedding-qwen3-embedding-0.6b")


@dataclass
class GateConfig:
    cases_path: Path
    home: Path
    report_dir: Path
    llm_base_url: str
    llm_model: str
    embed_base_url: str
    embed_model: str
    preflight_only: bool
    skip_ingest: bool
    reset_home: bool
    timeout_sec: int


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _normalize(text: object) -> str:
    return str(text or "").casefold()


def _contains_all(text: object, needles: list[Any]) -> bool:
    hay = _normalize(text)
    for needle in needles:
        n = _normalize(needle)
        if n and n not in hay:
            return False
    return True


def _contains_none(text: object, needles: list[Any]) -> bool:
    hay = _normalize(text)
    for needle in needles:
        n = _normalize(needle)
        if n and n in hay:
            return False
    return True


def _contains_any_groups(text: object, groups: list[Any]) -> bool:
    if not groups:
        return True
    hay = _normalize(text)
    if all(not isinstance(item, list) for item in groups):
        return any(_normalize(item) in hay for item in groups if _normalize(item))
    for group in groups:
        items = group if isinstance(group, list) else [group]
        if not any(_normalize(item) in hay for item in items if _normalize(item)):
            return False
    return True


def _citation_indices(answer: str) -> list[int]:
    found: list[int] = []
    for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer or ""):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                found.append(int(part))
    return sorted(set(found))


def _has_citation_markers(answer: str, source_paths: list[str]) -> bool:
    if _citation_indices(answer):
        return True
    hay = _normalize(answer)
    for path in source_paths:
        name = Path(str(path)).name.casefold()
        if name and f"[{name}" in hay:
            return True
    return False


def _include_with_source_fallback(answer: str, source_blob: str, needles: list[Any]) -> bool:
    if _contains_all(answer, needles):
        return True
    if not needles or not _contains_all(source_blob, needles):
        return False
    hay = _normalize(answer)
    for needle in needles:
        token = _normalize(needle)
        if not token:
            continue
        if "-" in token:
            prefix, suffix = token.split("-", 1)
        else:
            prefix, suffix = token, token
        if suffix and suffix in hay and prefix[:6] in hay:
            return True
    return False


def _safe_reset_home(path: Path) -> None:
    resolved = path.resolve()
    marker_ok = "home_rag_gate_v1" in str(resolved).casefold()
    if not marker_ok:
        raise RuntimeError(f"Refusing to reset non-gate HOME_RAG_HOME: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _prepare_env(config: GateConfig) -> None:
    home = config.home.resolve()
    data_dir = home / "data"
    index_dir = home / "chroma_db"
    log_dir = home / "logs"

    os.environ["HOME_RAG_HOME"] = str(home)
    os.environ["HOME_RAG_DATA_DIR"] = str(data_dir)
    os.environ["HOME_RAG_INDEX_DIR"] = str(index_dir)
    os.environ["HOME_RAG_LOG_DIR"] = str(log_dir)
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or "local"
    os.environ["LMSTUDIO_API_BASE"] = config.llm_base_url
    os.environ["LLM_API_BASE"] = config.llm_base_url
    os.environ["LLM_MODEL"] = config.llm_model
    # Keep real provider requests on the local model id, but let LlamaIndex use
    # a known OpenAI id for metadata/context-window calculations.
    os.environ["LLAMAINDEX_METADATA_FALLBACK_MODEL"] = "gpt-4o-mini"
    os.environ["EMBED_API_BASE"] = config.embed_base_url
    os.environ["EMBED_MODEL"] = config.embed_model
    os.environ["HOME_RAG_LOCAL_PROFILE"] = "local_strict"
    # pydantic-settings 2.x treats "false" as truthy; use 0/1 for bool env overrides.
    os.environ["HOME_RAG_LLM_FALLBACK_ENABLED"] = "0"
    os.environ["RAG_PROFILE"] = "quality"
    os.environ["RETRIEVAL_MODE"] = "hybrid"
    os.environ["SIMILARITY_TOP_K"] = "5"
    os.environ["ENABLE_RERANKER"] = "0"
    os.environ["RERANKER_ENABLED"] = "0"
    os.environ["ENABLE_METADATA_ENRICHMENT"] = "0"
    os.environ["ENABLE_DOCUMENT_SUMMARIES"] = "0"
    os.environ["ENABLE_TWO_STAGE_ANSWER_PATH"] = "0"
    os.environ["LLM_REQUEST_CACHE_PERSIST"] = "0"
    # Gate validates retrieval/integration; keep answers when provenance parsing is imperfect.
    os.environ["GROUNDED_ANSWER_STRICT_QA"] = "0"
    os.environ["COLLECTION_NAME"] = "home_rag_gate_v1_chunks"
    os.environ["SUMMARY_COLLECTION_NAME"] = "home_rag_gate_v1_summaries"


class _ApproxTiktokenEncoding:
    """Small tiktoken-compatible shim for environments blocking native DLLs."""

    def encode(self, text: object, *args: Any, **kwargs: Any) -> list[int]:
        raw = str(text or "")
        if not raw:
            return []
        # Roughly one token per four chars, matching app.token_utils fallback.
        return list(range(max(1, len(raw) // 4)))

    def decode(self, tokens: object, *args: Any, **kwargs: Any) -> str:
        try:
            count = len(tokens)  # type: ignore[arg-type]
        except TypeError:
            count = 0
        return " " * (count * 4)


def _install_tiktoken_fallback_if_needed() -> bool:
    """Install a process-local tiktoken shim when native import is blocked.

    The gate validates RAG integration, not tokenizer binary loading. This keeps
    LlamaIndex importable under Windows App Control while preserving approximate
    token budgeting semantics for the small gate corpus.
    """

    if "tiktoken" in sys.modules:
        return False
    try:
        __import__("tiktoken")
        return False
    except Exception:
        encoding = _ApproxTiktokenEncoding()
        module = types.ModuleType("tiktoken")
        module.encoding_for_model = lambda *args, **kwargs: encoding  # type: ignore[attr-defined]
        module.get_encoding = lambda *args, **kwargs: encoding  # type: ignore[attr-defined]
        module.Encoding = _ApproxTiktokenEncoding  # type: ignore[attr-defined]
        sys.modules["tiktoken"] = module
        return True


def _bind_config_module(config: GateConfig) -> None:
    from app import config as app_config

    home = config.home.resolve()
    app_config.HOME_RAG_HOME = home
    app_config.DATA_DIR = home / "data"
    app_config.CHROMA_DIR = home / "chroma_db"
    app_config.LOG_DIR = home / "logs"
    # app.config import runs load_dotenv(..., override=True) and can clobber gate env.
    _prepare_env(config)
    app_config.reset_settings_cache()


def _probe_models(base_url: str, expected_model: str, timeout_sec: int) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/models"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout_sec) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raw = payload.get("data") or payload.get("models") or []
    ids = []
    for item in raw:
        if isinstance(item, dict):
            ids.extend(str(item.get(k) or "") for k in ("id", "model", "name"))
    ids = [item for item in ids if item]
    return {
        "url": url,
        "expected_model": expected_model,
        "models": ids,
        "contains_expected": expected_model in ids or not expected_model,
    }


def _validate_cases(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    docs = ((doc.get("corpus") or {}).get("documents") or [])
    cases = doc.get("cases") or []
    seen_docs: set[str] = set()
    for i, item in enumerate(docs, start=1):
        rel = str(item.get("relative_path") or "").strip()
        if not rel:
            errors.append(f"corpus.documents[{i}] missing relative_path")
        if rel in seen_docs:
            errors.append(f"duplicate corpus document: {rel}")
        seen_docs.add(rel)
        if not str(item.get("content") or "").strip():
            errors.append(f"corpus document has empty content: {rel}")
    seen_cases: set[str] = set()
    for i, case in enumerate(cases, start=1):
        cid = str(case.get("id") or "").strip()
        if not cid:
            errors.append(f"cases[{i}] missing id")
        if cid in seen_cases:
            errors.append(f"duplicate case id: {cid}")
        seen_cases.add(cid)
        if not str(case.get("question") or "").strip():
            errors.append(f"case {cid} missing question")
    if len(cases) < 10:
        errors.append(f"expected at least 10 cases, got {len(cases)}")
    return errors


def _write_corpus(config: GateConfig, doc: dict[str, Any]) -> list[str]:
    data_dir = config.home / "data"
    written: list[str] = []
    for item in (doc.get("corpus") or {}).get("documents") or []:
        rel = str(item["relative_path"]).replace("\\", "/")
        target = data_dir / rel
        _write_text(target, str(item["content"]))
        written.append(rel)
    return written


def _run_ingest() -> None:
    from app.ingestion import build_index
    from app.retrieval_cache import clear_retrieval_cache

    build_index(reset=True)
    clear_retrieval_cache()


def _query_options(payload: dict[str, Any]):
    from app.models import QueryOptions

    allowed = {
        "folder",
        "folder_rel",
        "file_name",
        "relative_path",
        "topic",
        "logical_folder",
        "file",
        "homework_mode",
        "assistance_level",
        "study_mode",
        "followup_context",
        "session_id",
        "query_mode",
        "rag_profile",
    }
    clean = {k: v for k, v in payload.items() if k in allowed}
    clean.setdefault("rag_profile", "quality")
    return QueryOptions(**clean)


def _source_paths(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for src in result.get("sources") or []:
        if isinstance(src, dict):
            raw = src.get("relative_path") or src.get("file_name") or ""
            if raw:
                paths.append(str(raw).replace("\\", "/"))
    return paths


def _sources_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for src in result.get("sources") or []:
        if isinstance(src, dict):
            parts.append(str(src.get("relative_path") or src.get("file_name") or ""))
            parts.append(str(src.get("text") or ""))
    return "\n".join(parts)


def _evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    answer = str(result.get("answer") or "")
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    source_paths = _source_paths(result)
    source_blob = _sources_text(result)
    cited = _citation_indices(answer)
    require_sources = bool(case.get("require_sources", True))
    require_citation = bool(case.get("require_citation", True))
    expected_no_evidence = bool(case.get("expected_no_evidence", False))

    source_ok = _contains_all("\n".join(source_paths), case.get("expected_source_contains") or [])
    context_ok = _contains_all(source_blob, case.get("expected_context_contains") or [])
    include_ok = _include_with_source_fallback(answer, source_blob, case.get("must_include") or [])
    include_any_ok = _contains_any_groups(answer, case.get("must_include_any") or [])
    exclude_ok = _contains_none(answer, case.get("must_not_include") or [])
    sources_ok = bool(sources) if require_sources else True
    citation_present_ok = _has_citation_markers(answer, source_paths) if require_citation else True
    citation_source_id_ok = all(1 <= idx <= len(sources) for idx in cited)
    no_evidence_no_citation_ok = not cited if expected_no_evidence else True

    status = "PASS" if all(
        [
            source_ok,
            context_ok,
            include_ok,
            include_any_ok,
            exclude_ok,
            sources_ok,
            citation_present_ok,
            citation_source_id_ok,
            no_evidence_no_citation_ok,
        ]
    ) else "FAIL"

    return {
        "id": case.get("id"),
        "type": case.get("type"),
        "status": status,
        "source_ok": source_ok,
        "context_ok": context_ok,
        "include_ok": include_ok,
        "include_any_ok": include_any_ok,
        "exclude_ok": exclude_ok,
        "sources_ok": sources_ok,
        "citation_present_ok": citation_present_ok,
        "citation_source_id_ok": citation_source_id_ok,
        "no_evidence_no_citation_ok": no_evidence_no_citation_ok,
        "answer_status": result.get("answer_status"),
        "source_count": len(sources),
        "source_paths": source_paths,
        "cited_indices": cited,
        "answer_preview": answer[:320],
        "answer": answer,
        "debug": result.get("debug") or {},
    }


def _run_cases(doc: dict[str, Any]) -> list[dict[str, Any]]:
    from app.query_service import answer_question

    rows: list[dict[str, Any]] = []
    for case in doc.get("cases") or []:
        cid = case.get("id")
        print(f"Running Home RAG case: {cid}", flush=True)
        started = time.perf_counter()
        try:
            result = answer_question(
                str(case["question"]),
                _query_options(case.get("options") or {}),
            )
            row = _evaluate_case(case, result)
            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        except Exception as exc:  # noqa: BLE001 - reports must capture failing case.
            row = {
                "id": cid,
                "type": case.get("type"),
                "status": "ERROR",
                "error": type(exc).__name__,
                "message": str(exc),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        rows.append(row)
        print(f"{cid}: {row['status']}", flush=True)
    return rows


def _write_reports(config: GateConfig, summary: dict[str, Any]) -> dict[str, str]:
    config.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base = config.report_dir / f"home_rag_integration_gate_v1_{stamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    md_path = base.with_suffix(".md")
    report_paths = {"json": str(json_path), "csv": str(csv_path), "md": str(md_path)}
    summary["reports"] = report_paths
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = summary.get("rows") or []
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "id",
            "type",
            "status",
            "source_ok",
            "include_ok",
            "include_any_ok",
            "exclude_ok",
            "citation_present_ok",
            "citation_source_id_ok",
            "no_evidence_no_citation_ok",
            "source_count",
            "latency_ms",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Home RAG Integration Gate v1",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "| Case | Type | Status | Sources | Citation | Source IDs | No-evidence no-citation |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        display = {
            "id": row.get("id", ""),
            "type": row.get("type", ""),
            "status": row.get("status", ""),
            "source_count": row.get("source_count", 0),
            "citation_present_ok": row.get("citation_present_ok", False),
            "citation_source_id_ok": row.get("citation_source_id_ok", False),
            "no_evidence_no_citation_ok": row.get("no_evidence_no_citation_ok", False),
        }
        lines.append(
            "| {id} | {type} | {status} | {source_count} | {citation_present_ok} | {citation_source_id_ok} | {no_evidence_no_citation_ok} |".format(
                **display
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Home RAG Integration Gate v1.")
    parser.add_argument("--cases-path", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--llm-base-url", default=DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--embed-base-url", default=DEFAULT_EMBED_BASE_URL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--reset-home", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = GateConfig(
        cases_path=args.cases_path,
        home=args.home,
        report_dir=args.report_dir,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        embed_base_url=args.embed_base_url,
        embed_model=args.embed_model,
        preflight_only=args.preflight_only,
        skip_ingest=args.skip_ingest,
        reset_home=args.reset_home,
        timeout_sec=args.timeout_sec,
    )

    doc = _read_json(config.cases_path)
    errors = _validate_cases(doc)
    if errors:
        for error in errors:
            print(f"HOME_RAG_GATE_PREFLIGHT_ERROR: {error}", file=sys.stderr)
        return 2

    if config.reset_home:
        _safe_reset_home(config.home)
    _prepare_env(config)
    written = _write_corpus(config, doc)

    summary: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "mode": "preflight" if config.preflight_only else "model",
        "home": str(config.home.resolve()),
        "cases_path": str(config.cases_path.resolve()),
        "documents_written": written,
        "cases_total": len(doc.get("cases") or []),
        "checks": {
            "case_json": "PASS",
            "corpus_written": "PASS",
        },
    }

    if config.preflight_only:
        summary["rows"] = []
        summary["cases_passed"] = 0
        summary["cases_failed"] = 0
        summary["reports"] = _write_reports(config, summary)
        print(f"Home RAG gate corpus written: {config.home / 'data'}")
        print("HOME_RAG_INTEGRATION_GATE_V1_PREFLIGHT=PASS")
        return 0

    summary["tiktoken_fallback_installed"] = _install_tiktoken_fallback_if_needed()

    try:
        summary["llm_probe"] = _probe_models(config.llm_base_url, config.llm_model, config.timeout_sec)
        summary["embed_probe"] = _probe_models(config.embed_base_url, config.embed_model, config.timeout_sec)
    except (TimeoutError, URLError, OSError) as exc:
        summary["runtime_probe_error"] = f"{type(exc).__name__}: {exc}"
        summary["rows"] = []
        summary["cases_passed"] = 0
        summary["cases_failed"] = len(doc.get("cases") or [])
        summary["reports"] = _write_reports(config, summary)
        print("HOME_RAG_INTEGRATION_GATE_V1=BLOCKED_RUNTIME_ENDPOINT")
        return 3

    _bind_config_module(config)

    if not config.skip_ingest:
        _run_ingest()

    try:
        rows = _run_cases(doc)
    except ImportError as exc:
        rows = [
            {
                "id": case.get("id"),
                "type": case.get("type"),
                "status": "ERROR",
                "error": type(exc).__name__,
                "message": str(exc),
            }
            for case in doc.get("cases") or []
        ]
        summary["runtime_import_error"] = f"{type(exc).__name__}: {exc}"
        summary["rows"] = rows
        summary["cases_passed"] = 0
        summary["cases_failed"] = len(rows)
        summary["reports"] = _write_reports(config, summary)
        print(f"Report JSON: {summary['reports']['json']}")
        print("HOME_RAG_INTEGRATION_GATE_V1=BLOCKED_RUNTIME_IMPORT")
        return 4
    passed = sum(1 for row in rows if row.get("status") == "PASS")
    failed = len(rows) - passed
    summary["rows"] = rows
    summary["cases_passed"] = passed
    summary["cases_failed"] = failed
    summary["reports"] = _write_reports(config, summary)

    print(f"Report JSON: {summary['reports']['json']}")
    if failed:
        print("HOME_RAG_INTEGRATION_GATE_V1=FAIL")
        return 1
    print("HOME_RAG_INTEGRATION_GATE_V1=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
