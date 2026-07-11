#!/usr/bin/env python3
# import_open_notebook_pack.py

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(path: str) -> Path:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Unsafe exported_path: {path}")
    return p


def ensure_props(item: dict, required: list[str]) -> None:
    missing = [k for k in required if k not in item]
    if missing:
        raise ValueError(f"Missing required fields {missing} in source item: {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Open Notebook source pack into hometutor canonical folders.")
    parser.add_argument("--pack", required=True, help="Open Notebook source pack directory.")
    parser.add_argument("--hometutor-root", default=".", help="hometutor repository root.")
    parser.add_argument("--target-corpus", default="open_notebook", help="Canonical corpus name.")
    parser.add_argument("--report-dir", default="D:/AI/logs", help="Report directory.")
    parser.add_argument("--allow-derived-index", action="store_true", help="Also copy derived sources as indexable. Default: false.")
    args = parser.parse_args()

    pack = Path(args.pack).resolve()
    root = Path(args.hometutor_root).resolve()
    report_dir = Path(args.report_dir).resolve()

    manifest_path = pack / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"MANIFEST_NOT_FOUND: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for field in ["export_id", "exported_at", "source_system", "notebook_title", "sources"]:
        if field not in manifest:
            raise SystemExit(f"MANIFEST_FIELD_MISSING: {field}")

    if manifest["source_system"] != "open_notebook":
        raise SystemExit(f"UNSUPPORTED_SOURCE_SYSTEM: {manifest['source_system']}")

    canonical_sources = root / "data" / "sources" / args.target_corpus
    canonical_derived = root / "data" / "derived" / args.target_corpus
    manifest_dir = root / "data" / "manifests" / args.target_corpus
    registry_path = manifest_dir / "source_registry_open_notebook.jsonl"

    canonical_sources.mkdir(parents=True, exist_ok=True)
    canonical_derived.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    imported = []
    skipped_derived = []
    errors = []

    required = [
        "source_id", "title", "source_type", "exported_path",
        "content_sha256", "is_ai_generated", "citation_policy",
    ]

    for item in manifest["sources"]:
        try:
            ensure_props(item, required)
            rel = safe_rel(item["exported_path"])
            src_path = pack / rel
            if not src_path.exists():
                raise FileNotFoundError(f"Exported source file missing: {src_path}")

            actual_sha = sha256_file(src_path)
            if actual_sha.lower() != str(item["content_sha256"]).lower():
                raise ValueError(f"SHA256 mismatch for {src_path}: expected={item['content_sha256']} actual={actual_sha}")

            is_derived = bool(item["is_ai_generated"]) or item["citation_policy"] != "authoritative"
            if is_derived and not args.allow_derived_index:
                dst_root = canonical_derived
                skipped_derived.append(item["source_id"])
            else:
                dst_root = canonical_sources

            # keep source_id stable but avoid filesystem-problematic chars
            safe_name = item["source_id"].replace(":", "__").replace("/", "_").replace("\\", "_")
            dst = dst_root / f"{safe_name}{src_path.suffix.lower()}"
            shutil.copy2(src_path, dst)

            record = {
                **item,
                "canonical_path": str(dst.relative_to(root)).replace("\\", "/"),
                "canonical_absolute_path": str(dst),
                "target_corpus": args.target_corpus,
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "indexed_as_authoritative": (not is_derived or args.allow_derived_index),
            }
            imported.append(record)

        except Exception as exc:
            errors.append({"source": item, "error": str(exc)})

    manifest_out = manifest_dir / f"{manifest['export_id']}.manifest.imported.json"
    manifest_out.write_text(json.dumps({
        "manifest": manifest,
        "imported": imported,
        "errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    with registry_path.open("a", encoding="utf-8") as f:
        for record in imported:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    report = {
        "status": "PASS" if not errors and imported else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pack": str(pack),
        "hometutor_root": str(root),
        "target_corpus": args.target_corpus,
        "manifest_out": str(manifest_out),
        "registry_path": str(registry_path),
        "sources_total": len(manifest["sources"]),
        "imported_total": len(imported),
        "skipped_derived_total": len(skipped_derived),
        "skipped_derived": skipped_derived,
        "errors": errors,
    }

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = report_dir / f"open_notebook_import_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OPEN_NOTEBOOK_IMPORT={report['status']}")
    print(f"sources_total={report['sources_total']}")
    print(f"imported_total={report['imported_total']}")
    print(f"skipped_derived_total={report['skipped_derived_total']}")
    print(f"report={report_path}")

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
