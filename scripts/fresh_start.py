#!/usr/bin/env python3
"""
Full reset + re-ingest: wipes all local databases and rebuilds the vector index
from documents in data/.

Usage
-----
  python scripts/fresh_start.py --confirm-token DELETE-ALL-LOCAL-HOME-RAG-DATA

Steps performed
---------------
1. Delete all local data (Chroma, user_state.db, index metadata, logs, caches).
2. Verify deletion is complete.
3. Re-index all documents from data/ via build_index(reset=True).

Stop the API server and Telegram bot before running.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.delete_all_data import CONFIRM_TOKEN, delete_all_local_data, verify_deletion_complete


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wipe all local hometutor data and re-index documents from data/.",
    )
    parser.add_argument(
        "--confirm-token",
        required=True,
        help=f"Required safety token: {CONFIRM_TOKEN!r}",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Only delete data, do not run re-ingestion.",
    )
    args = parser.parse_args(argv)

    # ── Step 1: delete ───────────────────────────────────────────────────────
    print("=== Step 1/3: Deleting all local data ===")
    try:
        result = delete_all_local_data(confirm_token=args.confirm_token)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"  Removed dirs  : {len(result['removed_dirs'])}")
    print(f"  Removed files : {len(result['removed_files'])}")
    for p in result["removed_dirs"] + result["removed_files"]:
        print(f"    - {p}")

    # ── Step 2: verify ───────────────────────────────────────────────────────
    print("\n=== Step 2/3: Verifying deletion ===")
    ok, remaining = verify_deletion_complete()
    if not ok:
        print("ERROR: deletion incomplete — remaining paths:", file=sys.stderr)
        for p in remaining:
            print(f"  {p}", file=sys.stderr)
        return 2
    print("  OK — all targets cleared.")

    if args.skip_ingest:
        print("\nSkipped ingestion (--skip-ingest). Ready for manual upload.")
        return 0

    # ── Step 3: ingest ───────────────────────────────────────────────────────
    print("\n=== Step 3/3: Re-indexing documents from data/ ===")
    from app.ingestion import build_index

    build_index(reset=True)
    print("\nDone. Fresh index is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
