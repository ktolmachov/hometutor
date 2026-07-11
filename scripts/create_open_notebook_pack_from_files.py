#!/usr/bin/env python3
# create_open_notebook_pack_from_files.py

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


TEXT_EXTENSIONS = {
    ".md": "markdown",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
}


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9а-яё]+", "-", value, flags=re.IGNORECASE)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "source"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Open Notebook bridge source pack from files.")
    parser.add_argument("--input-dir", required=True, help="Directory with selected source files.")
    parser.add_argument("--output-pack", required=True, help="Output source pack directory.")
    parser.add_argument("--notebook-title", required=True, help="Notebook title.")
    parser.add_argument("--export-id", default=None, help="Optional export id.")
    parser.add_argument("--include-derived-dir", default=None, help="Optional dir with AI-generated derived notes.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_pack = Path(args.output_pack).resolve()
    sources_dir = output_pack / "sources"
    derived_dir = output_pack / "derived"

    if not input_dir.exists():
        raise SystemExit(f"INPUT_DIR_NOT_FOUND: {input_dir}")

    if output_pack.exists():
        shutil.rmtree(output_pack)

    sources_dir.mkdir(parents=True, exist_ok=True)
    derived_dir.mkdir(parents=True, exist_ok=True)

    notebook_slug = slugify(args.notebook_title)
    export_id = args.export_id or f"open_notebook_export_{notebook_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    manifest_sources = []

    for src in sorted(input_dir.iterdir()):
        if not src.is_file():
            continue

        ext = src.suffix.lower()
        source_type = TEXT_EXTENSIONS.get(ext)
        if source_type is None:
            continue

        source_slug = slugify(src.stem)
        dst_name = f"{source_slug}{ext}"
        dst = sources_dir / dst_name
        shutil.copy2(src, dst)

        digest = sha256_file(dst)
        manifest_sources.append({
            "source_id": f"onb:{notebook_slug}:{source_slug}:{digest[:8]}",
            "title": src.stem,
            "source_type": source_type,
            "original_url": None,
            "exported_path": f"sources/{dst_name}",
            "content_sha256": digest,
            "is_ai_generated": False,
            "citation_policy": "authoritative",
        })

    if args.include_derived_dir:
        derived_input = Path(args.include_derived_dir).resolve()
        if derived_input.exists():
            for src in sorted(derived_input.iterdir()):
                if not src.is_file():
                    continue
                ext = src.suffix.lower()
                source_type = TEXT_EXTENSIONS.get(ext)
                if source_type is None:
                    continue

                source_slug = slugify(src.stem)
                dst_name = f"{source_slug}{ext}"
                dst = derived_dir / dst_name
                shutil.copy2(src, dst)

                digest = sha256_file(dst)
                manifest_sources.append({
                    "source_id": f"onb:{notebook_slug}:{source_slug}:{digest[:8]}",
                    "title": src.stem,
                    "source_type": source_type,
                    "original_url": None,
                    "exported_path": f"derived/{dst_name}",
                    "content_sha256": digest,
                    "is_ai_generated": True,
                    "citation_policy": "derived_non_authoritative",
                })

    if not manifest_sources:
        raise SystemExit("NO_SUPPORTED_SOURCE_FILES_FOUND")

    manifest = {
        "export_id": export_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "open_notebook",
        "notebook_title": args.notebook_title,
        "sources": manifest_sources,
    }

    (output_pack / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("OPEN_NOTEBOOK_PACK_CREATE=PASS")
    print(f"pack={output_pack}")
    print(f"sources_total={len(manifest_sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
