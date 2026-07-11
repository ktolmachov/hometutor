#!/usr/bin/env python3
# test_open_notebook_manifest.py

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Open Notebook bridge manifest.")
    parser.add_argument("--pack", required=True)
    args = parser.parse_args()

    pack = Path(args.pack).resolve()
    manifest_path = pack / "manifest.json"

    if not manifest_path.exists():
        raise SystemExit(f"MANIFEST_NOT_FOUND: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    required_root = ["export_id", "exported_at", "source_system", "notebook_title", "sources"]
    for field in required_root:
        if field not in manifest:
            raise SystemExit(f"ROOT_FIELD_MISSING: {field}")

    if manifest["source_system"] != "open_notebook":
        raise SystemExit("SOURCE_SYSTEM_MUST_BE_open_notebook")

    if not manifest["sources"]:
        raise SystemExit("NO_SOURCES")

    authoritative_count = 0
    derived_count = 0

    for item in manifest["sources"]:
        for field in [
            "source_id", "title", "source_type", "exported_path",
            "content_sha256", "is_ai_generated", "citation_policy"
        ]:
            if field not in item:
                raise SystemExit(f"SOURCE_FIELD_MISSING: {field}")

        if not str(item["source_id"]).startswith("onb:"):
            raise SystemExit(f"SOURCE_ID_NOT_STABLE_ONB_PREFIX: {item['source_id']}")

        path = pack / item["exported_path"]
        if not path.exists():
            raise SystemExit(f"EXPORTED_FILE_NOT_FOUND: {path}")

        actual = sha256_file(path)
        if actual.lower() != str(item["content_sha256"]).lower():
            raise SystemExit(f"SHA256_MISMATCH: {path}")

        if item["citation_policy"] == "authoritative" and item["is_ai_generated"] is False:
            authoritative_count += 1
        else:
            derived_count += 1

    if authoritative_count < 1:
        raise SystemExit("NO_AUTHORITATIVE_SOURCES")

    print("OPEN_NOTEBOOK_MANIFEST_TEST=PASS")
    print(f"sources_total={len(manifest['sources'])}")
    print(f"authoritative_count={authoritative_count}")
    print(f"derived_count={derived_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
