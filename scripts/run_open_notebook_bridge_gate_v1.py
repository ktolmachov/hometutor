#!/usr/bin/env python3
# run_open_notebook_bridge_gate_v1.py

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


TRANSIENT_SOURCE_PATTERN = re.compile(r"source:[a-zA-Z0-9]{8,}")


def read_all_authoritative(root: Path) -> tuple[str, list[Path]]:
    sources_dir = root / "data" / "sources" / "open_notebook"
    files: list[Path] = []
    text_parts: list[str] = []

    if sources_dir.exists():
        for path in sorted(sources_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".html", ".htm"}:
                files.append(path)
                text_parts.append(path.read_text(encoding="utf-8", errors="replace"))

    return "\n\n".join(text_parts), files


def load_registry(root: Path) -> list[dict]:
    registry = root / "data" / "manifests" / "open_notebook" / "source_registry_open_notebook.jsonl"
    if not registry.exists():
        return []

    rows = []
    for line in registry.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenNotebook -> HomeTutor bridge gate v1.")
    parser.add_argument("--hometutor-root", default=".", help="hometutor repository root.")
    parser.add_argument("--cases", required=True, help="Bridge gate cases JSON.")
    parser.add_argument("--report-dir", default="D:/AI/logs", help="Report directory.")
    args = parser.parse_args()

    root = Path(args.hometutor_root).resolve()
    cases_path = Path(args.cases).resolve()
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    corpus_text, source_files = read_all_authoritative(root)
    registry = load_registry(root)

    results = []
    fail_count = 0

    # Structural checks
    structural = []

    structural.append({
        "id": "registry_exists",
        "pass": bool(registry),
        "details": f"registry_rows={len(registry)}",
    })

    stable_ids_ok = all(str(r.get("source_id", "")).startswith("onb:") for r in registry)
    structural.append({
        "id": "stable_source_ids",
        "pass": stable_ids_ok,
        "details": "all source_id must start with onb:",
    })

    no_transient_ids = not any(TRANSIENT_SOURCE_PATTERN.search(json.dumps(r, ensure_ascii=False)) for r in registry)
    structural.append({
        "id": "no_open_notebook_transient_ids_in_registry",
        "pass": no_transient_ids,
        "details": "must not contain source:56erm... style ids",
    })

    derived_not_authoritative = all(
        not (r.get("is_ai_generated") is True and r.get("indexed_as_authoritative") is True)
        for r in registry
    )
    structural.append({
        "id": "derived_sources_not_authoritative",
        "pass": derived_not_authoritative,
        "details": "AI-generated derived files must not be indexed as authoritative by default",
    })

    for check in structural:
        if not check["pass"]:
            fail_count += 1
        results.append({"type": "structural", **check})

    # Evidence checks
    for case in cases.get("cases", []):
        case_id = case["id"]
        expected_contains = case.get("expected_contains", [])
        must_not_contain = case.get("must_not_contain", [])
        expected_refusal = bool(case.get("expected_refusal", False))

        if expected_refusal:
            # Static evidence gate: refusal case should not have expected forbidden evidence terms in authoritative corpus.
            forbidden_evidence = case.get("forbidden_evidence_contains", [])
            passed = not any(term.lower() in corpus_text.lower() for term in forbidden_evidence)
            details = {
                "expected_refusal": True,
                "forbidden_evidence_contains": forbidden_evidence,
            }
        else:
            passed = all(term.lower() in corpus_text.lower() for term in expected_contains)
            details = {
                "expected_contains": expected_contains,
            }

        if must_not_contain:
            passed = passed and not any(term.lower() in corpus_text.lower() for term in must_not_contain)
            details["must_not_contain"] = must_not_contain

        if not passed:
            fail_count += 1

        results.append({
            "type": "case",
            "id": case_id,
            "pass": passed,
            "question": case.get("question"),
            "details": details,
        })

    report = {
        "status": "PASS" if fail_count == 0 else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hometutor_root": str(root),
        "cases": str(cases_path),
        "source_files": [str(p) for p in source_files],
        "registry_rows": len(registry),
        "fail_count": fail_count,
        "results": results,
    }

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = report_dir / f"open_notebook_bridge_gate_v1_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OPEN_NOTEBOOK_BRIDGE_GATE_V1={report['status']}")
    print(f"registry_rows={len(registry)}")
    print(f"source_files={len(source_files)}")
    print(f"fail_count={fail_count}")
    print(f"report={report_path}")

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
