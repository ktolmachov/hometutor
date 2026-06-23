"""ChromaDB node-content health check.

Queries chroma.sqlite3 directly (no LlamaIndex / embedding model needed) and
reports p50 / p95 / max _node_content sizes.  Exits non-zero when any threshold
is breached so it can be used as a post-ingest gate.

Usage:
    python scripts/check_chroma_health.py               # uses default chroma_db/
    python scripts/check_chroma_health.py --db path/to/chroma.sqlite3
    python scripts/check_chroma_health.py --warn-kb 10 --fail-kb 50

Thresholds (defaults):
    --warn-kb 8   warn  when median _node_content exceeds  8 KB  (normal ~3 KB)
    --fail-kb 30  error when median _node_content exceeds 30 KB  (bloat threshold)
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from pathlib import Path

_DEFAULT_DB = Path(__file__).parent.parent / "chroma_db" / "chroma.sqlite3"
_WARN_KB = 8
_FAIL_KB = 30


def _sizeof_fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def check(db_path: Path, warn_kb: int, fail_kb: int) -> int:
    if not db_path.exists():
        print(f"[SKIP] ChromaDB not found at {db_path} — nothing indexed yet.")
        return 0

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # _node_content is stored in embedding_metadata as a string_value with key '_node_content'
    rows = cur.execute(
        "SELECT length(string_value) FROM embedding_metadata WHERE key='_node_content'"
    ).fetchall()
    con.close()

    if not rows:
        print("[SKIP] No _node_content rows found — index may be empty.")
        return 0

    sizes = [r[0] for r in rows if r[0] is not None]
    median_b = int(statistics.median(sizes))
    p95_b = int(sorted(sizes)[int(len(sizes) * 0.95)])
    max_b = max(sizes)
    count = len(sizes)

    db_size_b = db_path.stat().st_size

    print(f"ChromaDB health check — {db_path}")
    print(f"  DB file size : {_sizeof_fmt(db_size_b)}")
    print(f"  Nodes        : {count}")
    print(f"  _node_content  median={_sizeof_fmt(median_b)}  p95={_sizeof_fmt(p95_b)}  max={_sizeof_fmt(max_b)}")

    warn_b = warn_kb * 1024
    fail_b = fail_kb * 1024

    if median_b > fail_b:
        print(
            f"\n[FAIL] Median _node_content {_sizeof_fmt(median_b)} exceeds fail threshold "
            f"{_sizeof_fmt(fail_b)}.\n"
            "       Likely cause: full source document stored in chunk metadata "
            "(original_text / relationship blobs).\n"
            "       Fix: run fresh_start.py after verifying the ingestion pipeline fix."
        )
        return 2

    if median_b > warn_b:
        print(
            f"\n[WARN] Median _node_content {_sizeof_fmt(median_b)} exceeds warn threshold "
            f"{_sizeof_fmt(warn_b)}.\n"
            "       Investigate metadata keys: "
            "original_text, window, relationship node blobs."
        )
        return 1

    print(f"\n[OK] Node content sizes are within healthy bounds (warn={warn_kb} KB, fail={fail_kb} KB).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB, metavar="PATH", help="Path to chroma.sqlite3")
    parser.add_argument("--warn-kb", type=int, default=_WARN_KB, metavar="N", help="Warn threshold in KB (default 8)")
    parser.add_argument("--fail-kb", type=int, default=_FAIL_KB, metavar="N", help="Fail threshold in KB (default 30)")
    args = parser.parse_args()

    rc = check(args.db, args.warn_kb, args.fail_kb)
    sys.exit(rc)


if __name__ == "__main__":
    main()
