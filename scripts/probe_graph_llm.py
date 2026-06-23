#!/usr/bin/env python3
"""Full diagnostic probe for Course Graph Compiler LLM (GRAPH_* settings).

Checks config, OpenAI-compatible /v1/models, client wiring, JSON extraction
on a tiny synthetic document, and optional live extraction on one real course file.

Usage::

    .\\.venv\\Scripts\\python.exe scripts/probe_graph_llm.py
    .\\.venv\\Scripts\\python.exe scripts/probe_graph_llm.py --model qwen3.6-27b
    .\\.venv\\Scripts\\python.exe scripts/probe_graph_llm.py --compare qwen3.6-27b gemma-4-26b-a4b-it-q4-0
    .\\.venv\\Scripts\\python.exe scripts/probe_graph_llm.py --live-doc
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SYNTHETIC_DOC_ID = "probe_synthetic.md"
_SYNTHETIC_ROWS = [
    {
        "doc_id": _SYNTHETIC_DOC_ID,
        "relative_path": "probe/synthetic.md",
        "file_name": "synthetic.md",
        "title": "RAG basics probe",
        "text": (
            "Retrieval-Augmented Generation combines a retriever and a generator. "
            "Embeddings map text to vectors. Chunking splits documents for indexing. "
            "Prerequisites: embeddings before hybrid retrieval."
        ),
        "section_title": "Intro",
    }
]

_CANDIDATE_QWEN_IDS = (
    "qwen3.6-27b",
    "qwen/qwen3.6-27b",
    "Qwen3.6-27B",
    "qwen3-27b",
)


@dataclass
class ProbeStep:
    name: str
    status: str  # pass | warn | fail | skip
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelProbeResult:
    model: str
    api_base: str
    steps: list[ProbeStep] = field(default_factory=list)
    json_valid: bool = False
    concept_count: int = 0
    relation_count: int = 0
    latency_ms: int | None = None
    recommendation: str = ""


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> tuple[int | None, Any, str | None]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(body) if body.strip().startswith("{") else body
        except Exception:  # noqa: BLE001
            payload = None
        return exc.code, payload, str(exc)
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


def _models_list(api_base: str, api_key: str) -> tuple[list[str], str | None]:
    base = api_base.rstrip("/")
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    status, payload, err = _http_get_json(url, headers={"Authorization": f"Bearer {api_key}"})
    if err and status is None:
        return [], err
    if not isinstance(payload, dict):
        return [], f"unexpected /models payload (status={status})"
    ids: list[str] = []
    for item in payload.get("data") or []:
        if isinstance(item, dict):
            mid = str(item.get("id") or "").strip()
            if mid:
                ids.append(mid)
    return ids, None


def _resolve_model_id(requested: str, available: list[str]) -> tuple[str | None, str]:
    req = requested.strip()
    if not req:
        return None, "empty model id"
    if req in available:
        return req, "exact"
    lower = {m.lower(): m for m in available}
    if req.lower() in lower:
        return lower[req.lower()], "case_insensitive"
    tail = req.split("/")[-1].lower()
    for mid in available:
        if mid.lower() == tail or mid.lower().endswith(tail):
            return mid, "suffix_match"
    for mid in available:
        if tail in mid.lower() or mid.lower() in tail:
            return mid, "fuzzy"
    return None, "not_listed"


def _probe_settings() -> tuple[Any, list[ProbeStep]]:
    from app.config import get_settings

    s = get_settings()
    steps: list[ProbeStep] = []
    api_key_ok = bool((s.openai_api_key or "").strip())
    steps.append(
        ProbeStep(
            "openai_api_key",
            "pass" if api_key_ok else "fail",
            "OPENAI_API_KEY задан" if api_key_ok else "OPENAI_API_KEY пуст — get_graph_llm() упадёт",
        )
    )
    base = (s.graph_llm_api_base or "").strip()
    model = (s.graph_model or s.llm_model or "").strip()
    steps.append(
        ProbeStep(
            "graph_config",
            "pass" if base and model else "fail",
            f"GRAPH_LLM_API_BASE={base or '(unset)'} | GRAPH_MODEL={model or '(unset)'}",
            {"llm_model": s.llm_model, "graph_llm_api_base": base, "graph_model": model},
        )
    )
    try:
        from app.course_cache import graph_llm_probe_ok

        probe_ok = graph_llm_probe_ok(settings=s)
        steps.append(
            ProbeStep(
                "graph_llm_probe_ok",
                "pass" if probe_ok else "fail",
                "graph_llm_probe_ok()=True" if probe_ok else "graph_llm_probe_ok()=False",
            )
        )
    except Exception as exc:  # noqa: BLE001
        steps.append(ProbeStep("graph_llm_probe_ok", "fail", f"graph_llm_probe_ok raised: {exc}"))
    return s, steps


def _with_graph_model(model: str, fn):
    import os

    from app.config import reset_settings_cache

    old = os.environ.get("GRAPH_MODEL")
    os.environ["GRAPH_MODEL"] = model
    reset_settings_cache()
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("GRAPH_MODEL", None)
        else:
            os.environ["GRAPH_MODEL"] = old
        reset_settings_cache()


def _extract_with_model(model_override: str | None, rows: list[dict[str, Any]]) -> ModelProbeResult:
    from app.config import get_settings
    from app.course_graph_compiler import _default_llm_extract

    s = get_settings()
    api_base = (s.graph_llm_api_base or "").strip()
    model = (model_override or s.graph_model or s.llm_model or "").strip()
    result = ModelProbeResult(model=model, api_base=api_base)

    api_key = (s.openai_api_key or "").strip()
    available, models_err = _models_list(api_base, api_key)
    if models_err:
        result.steps.append(
            ProbeStep("models_endpoint", "fail", f"/v1/models недоступен: {models_err}")
        )
        result.recommendation = "Поднимите llama.cpp/LM Studio на GRAPH_LLM_API_BASE и загрузите модель."
        return result

    result.steps.append(
        ProbeStep(
            "models_endpoint",
            "pass",
            f"/v1/models OK — {len(available)} model(s)",
            {"models": available[:20]},
        )
    )
    resolved, match_kind = _resolve_model_id(model, available)
    if resolved is None:
        result.steps.append(
            ProbeStep(
                "model_registered",
                "fail",
                f"GRAPH_MODEL={model!r} не найден среди {available!r}",
                {"match_kind": match_kind},
            )
        )
        result.recommendation = "Исправьте GRAPH_MODEL на id из /v1/models или загрузите нужный weights."
        return result

    if resolved != model:
        result.steps.append(
            ProbeStep(
                "model_registered",
                "warn",
                f"Запрошен {model!r}, используем {resolved!r} ({match_kind})",
            )
        )
        model = resolved
        result.model = model
    else:
        result.steps.append(ProbeStep("model_registered", "pass", f"Модель {model!r} зарегистрирована"))

    if not available:
        result.steps.append(
            ProbeStep("model_loaded", "fail", "Список моделей пуст — вероятно, weights не загружены")
        )
        result.recommendation = "Загрузите модель в llama.cpp (lms load / UI Load)."
        return result

    doc_id = str(rows[0].get("doc_id") or _SYNTHETIC_DOC_ID)
    t0 = time.perf_counter()

    def _run_extract() -> tuple[dict[str, Any], str | None]:
        return _default_llm_extract(doc_id, rows)

    try:
        if model_override:
            payload, finish = _with_graph_model(model, _run_extract)
        else:
            payload, finish = _run_extract()
    except Exception as exc:  # noqa: BLE001
        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        msg = str(exc)
        result.steps.append(
            ProbeStep(
                "extraction_call",
                "fail",
                f"extract failed: {msg[:500]}",
                {"latency_ms": result.latency_ms},
            )
        )
        if "No models loaded" in msg:
            result.recommendation = "Сервер жив, но модель не в RAM — загрузите weights перед ingest/rebuild."
        elif "Expecting" in msg or "JSON" in msg:
            result.recommendation = "Модель отвечает, но JSON невалиден — смените GRAPH_MODEL на Qwen3.6-27B или включите JSON mode."
        else:
            result.recommendation = "Проверьте логи llama.cpp и соответствие GRAPH_LLM_API_BASE порту сервера."
        return result

    result.latency_ms = int((time.perf_counter() - t0) * 1000)
    concepts = payload.get("concepts") if isinstance(payload, dict) else None
    relations = payload.get("relations") if isinstance(payload, dict) else None
    result.concept_count = len(concepts) if isinstance(concepts, list) else 0
    result.relation_count = len(relations) if isinstance(relations, list) else 0
    result.json_valid = True

    result.steps.append(
        ProbeStep(
            "extraction_call",
            "pass",
            f"JSON OK | concepts={result.concept_count} relations={result.relation_count} finish={finish!r}",
            {"latency_ms": result.latency_ms},
        )
    )

    if result.concept_count < 2:
        result.steps.append(
            ProbeStep("extraction_quality", "warn", "Мало концептов на synthetic probe (<2)")
        )
    else:
        result.steps.append(ProbeStep("extraction_quality", "pass", "Synthetic probe: достаточно концептов"))

    if result.relation_count < 1:
        result.steps.append(
            ProbeStep("extraction_quality_relations", "warn", "Нет relations на synthetic probe")
        )
    else:
        result.steps.append(ProbeStep("extraction_quality_relations", "pass", "Есть relations"))

    result.recommendation = (
        "Подходит для compiler-графа (synthetic probe прошёл)."
        if result.json_valid and result.concept_count >= 2
        else "JSON валиден, но качество слабое — проверьте live-doc и gate metrics."
    )
    return result


def _load_one_live_row() -> list[dict[str, Any]] | None:
    from app.config import DATA_DIR
    from app.ingestion import get_doc_supported_exts
    from app.ingestion_content_state import build_file_manifest
    import app.ingestion as ing

    manifest = build_file_manifest(DATA_DIR, ing.get_doc_supported_exts())
    files = manifest.get("files") or {}
    if not files:
        return None
    from app.config import CHROMA_DIR

    docs = ing._load_documents_with_extraction_cache(  # noqa: SLF001
        data_dir=DATA_DIR,
        chroma_dir=CHROMA_DIR,
        file_manifest=manifest,
    )
    if not docs:
        return None
    doc = docs[0]
    meta = dict(doc.metadata or {})
    meta["text"] = str(getattr(doc, "text", "") or "")[:4000]
    doc_id = str(meta.get("doc_id") or meta.get("relative_path") or "live")
    meta["doc_id"] = doc_id
    return [meta]


def _graph_bundle_status() -> ProbeStep:
    from app.graph_generation_paths import generation_bundle_dir
    from app.index_registry import get_active_generation_view
    from app.knowledge_graph_bundle import load_graph_quality_report

    view = get_active_generation_view()
    gid = str(view.generation_id or "")
    bundle = generation_bundle_dir(gid)
    report = load_graph_quality_report(bundle) or {}
    kg = bundle / "kg.sqlite"
    return ProbeStep(
        "active_graph_bundle",
        "pass" if kg.is_file() else "warn",
        f"generation={gid} | kg.sqlite={'yes' if kg.is_file() else 'no'} | gate_passed={report.get('gate_passed')} | heuristic={report.get('heuristic_fallback')}",
        {
            "bundle_dir": str(bundle),
            "fail_reasons": list(report.get("fail_reasons") or [])[:5],
            "metrics": dict(report.get("metrics") or {}),
        },
    )


def _disable_llm_cache_for_probe() -> None:
    import os

    from app.config import reset_settings_cache

    os.environ["LLM_REQUEST_CACHE_PERSIST"] = "false"
    reset_settings_cache()
    import app.request_cache as rc

    rc._request_cache = None


def _recommend_primary(
    results: list[ModelProbeResult],
    configured_model: str,
    live_doc: ModelProbeResult | None,
    available_models: list[str],
) -> str:
    qwen_loaded = any("qwen" in m.lower() for m in available_models)
    lines: list[str] = []

    if live_doc and not live_doc.json_valid:
        lines.append(
            f"Live-doc probe FAILED для {live_doc.model!r} "
            f"({live_doc.steps[-1].message if live_doc.steps else 'unknown'}) — "
            "synthetic OK не гарантирует compiler на реальных уроках."
        )
    elif live_doc and live_doc.json_valid:
        lines.append(
            f"Live-doc probe OK: concepts={live_doc.concept_count}, relations={live_doc.relation_count}."
        )

    if not qwen_loaded:
        lines.append(
            "Qwen3.6-27B не загружена в llama.cpp: /v1/models возвращает только "
            f"{available_models!r}. Сначала загрузите Qwen, затем повторите probe."
        )

    ok = [r for r in results if r.json_valid]
    if not ok:
        lines.append(
            "Ни одна probed-модель не вернула валидный JSON на synthetic probe. "
            "Проверьте сервер и GRAPH_LLM_API_BASE."
        )
        return " ".join(lines)

    best = max(ok, key=lambda r: (r.relation_count, r.concept_count, -(r.latency_ms or 999999)))
    qwen_results = [r for r in results if "qwen" in r.model.lower() and r.json_valid]
    if qwen_results:
        q = max(qwen_results, key=lambda r: (r.relation_count, r.concept_count))
        lines.append(
            f"Рекомендация: GRAPH_MODEL={q.model!r} "
            f"(synthetic: {q.concept_count} concepts, {q.relation_count} relations, {q.latency_ms}ms)."
        )
    elif qwen_loaded:
        lines.append(
            "Qwen в /v1/models есть, но probe не запускался с правильным id — "
            "используйте --model <точный id из /v1/models>."
        )
    else:
        lines.append(
            f"Сейчас доступна только {best.model!r} (synthetic OK). "
            "Для возврата к Qwen3.6-27B: загрузите weights → probe --live-doc --no-cache → rebuild."
        )

    if configured_model != best.model and not qwen_results:
        lines.append(f"Текущий GRAPH_MODEL={configured_model!r}.")

    return " ".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe graph LLM for Course Graph Compiler.")
    parser.add_argument("--model", help="Override GRAPH_MODEL for this probe only.")
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="MODEL",
        help="Probe multiple model ids (does not change .env).",
    )
    parser.add_argument("--live-doc", action="store_true", help="Also run extraction on first indexed document.")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable LLM request cache for extraction probes (accurate live-doc test).",
    )
    parser.add_argument("--json-out", type=Path, help="Write full report JSON to path.")
    args = parser.parse_args(argv)

    if args.no_cache:
        _disable_llm_cache_for_probe()

    _, setting_steps = _probe_settings()
    from app.config import get_settings

    configured = (get_settings().graph_model or get_settings().llm_model or "").strip()

    report: dict[str, Any] = {
        "configured_graph_model": configured,
        "steps": [asdict(s) for s in setting_steps],
        "models": [],
        "recommendation": "",
    }
    report["steps"].append(asdict(_graph_bundle_status()))

    models_to_try: list[str | None]
    if args.compare:
        models_to_try = list(args.compare)
    elif args.model:
        models_to_try = [args.model]
    else:
        models_to_try = [None, configured]
        for qid in _CANDIDATE_QWEN_IDS:
            if qid not in models_to_try:
                models_to_try.append(qid)

    seen: set[str] = set()
    results: list[ModelProbeResult] = []
    rows = _SYNTHETIC_ROWS

    for mid in models_to_try:
        key = mid or configured
        if key in seen:
            continue
        seen.add(key)
        print(f"\n=== Probe model: {key} ===", flush=True)
        res = _extract_with_model(mid, rows)
        for step in res.steps:
            print(f"  [{step.status.upper():4}] {step.name}: {step.message}")
        print(f"  -> {res.recommendation}")
        results.append(res)
        report["models"].append(asdict(res))

    live_result: ModelProbeResult | None = None
    if args.live_doc:
        live_rows = _load_one_live_row()
        if live_rows:
            print("\n=== Live document probe (configured model) ===", flush=True)
            live_result = _extract_with_model(args.model, live_rows)
            for step in live_result.steps:
                print(f"  [{step.status.upper():4}] {step.name}: {step.message}")
            report["live_doc"] = asdict(live_result)
        else:
            report["live_doc"] = {"error": "no indexed documents in DATA_DIR"}

    available_models: list[str] = []
    if results and results[0].steps:
        detail = results[0].steps[0].detail or {}
        available_models = list(detail.get("models") or [])

    report["recommendation"] = _recommend_primary(
        results,
        configured,
        live_result,
        available_models,
    )
    print(f"\n=== Итог ===\n{report['recommendation']}\n")

    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report written: {args.json_out}")

    any_pass = any(r.json_valid for r in results)
    configured_pass = any(r.json_valid for r in results if r.model == configured or (not args.compare and not args.model))
    return 0 if any_pass and (configured_pass or args.compare or args.model) else 1


if __name__ == "__main__":
    raise SystemExit(main())
