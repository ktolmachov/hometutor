#!/usr/bin/env python3
"""Удаление призрачных (тестовых/fixture) следов из прогресса студента.

Призраки — строки в ``quiz_mastery``, ``spaced_repetition``, ``quiz_results``
и ``app_kv.emotional_heatmap_json``, чей концепт не принадлежит ни одному
активному графу знаний и совпадает с известными fixture-паттернами.

Режимы:
  ``--dry-run`` (по умолчанию) — показать, что будет удалено; БД не трогается.
  ``--confirm``             — создать резервную копию и выполнить очистку.

Требуется ``--confirm`` и явный токен подтверждения.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIRM_TOKEN = "CLEAN-PROGRESS-GHOSTS"

_KNOWN_FIXTURE_PATTERNS = frozenset({
    "topic_x",
    "topica",
    "topicb",
    "e2e_topic",
    "bind",
    "legacytopic",
    "test_",
    "fixture_",
})

_SINGLE_TOKEN_FIXTURES = frozenset({"t"})

_GHOST_TABLES = ("quiz_mastery", "spaced_repetition", "quiz_results")

_HEATMAP_KV_KEY = "emotional_heatmap_json"


def _utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def get_user_state_path() -> Path:
    from app.config import get_settings

    return Path(get_settings().user_state_db).resolve()


def _is_fixture_concept(concept: str) -> bool:
    c = concept.strip().lower()
    if not c:
        return False
    if c in _SINGLE_TOKEN_FIXTURES:
        return True
    for pat in _KNOWN_FIXTURE_PATTERNS:
        if pat in c:
            return True
    return False


def collect_ghost_snapshot(
    db_path: Path,
    active_ids: set[str],
) -> dict[str, list[dict[str, object]]]:
    """Возвращает {table: [rows]} — призрачные строки, подлежащие удалению."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    result: dict[str, list[dict[str, object]]] = {}

    for table in _GHOST_TABLES:
        try:
            rows = conn.execute(f"SELECT DISTINCT concept FROM {table} WHERE concept IS NOT NULL AND concept != ''").fetchall()
        except sqlite3.OperationalError:
            continue
        ghost_concepts: list[str] = []
        for row in rows:
            c = str(row["concept"]).strip()
            if c not in active_ids and _is_fixture_concept(c):
                ghost_concepts.append(c)
        if ghost_concepts:
            placeholders = ",".join("?" for _ in ghost_concepts)
            try:
                ghost_rows = conn.execute(
                    f"SELECT * FROM {table} WHERE concept IN ({placeholders})",
                    ghost_concepts,
                ).fetchall()
                result[table] = [dict(r) for r in ghost_rows]
            except sqlite3.OperationalError:
                continue

    raw = conn.execute(
        "SELECT value FROM app_kv WHERE key = ?", (_HEATMAP_KV_KEY,)
    ).fetchone()
    if raw:
        try:
            heatmap_data = json.loads(raw["value"])
        except (json.JSONDecodeError, TypeError):
            heatmap_data = []
        if isinstance(heatmap_data, list):
            ghost_entries = [
                e for e in heatmap_data
                if str(e.get("concept") or "").strip() not in active_ids
                and _is_fixture_concept(str(e.get("concept") or ""))
            ]
            if ghost_entries:
                result["app_kv_emotional_heatmap"] = ghost_entries

    conn.close()
    return result


def execute_cleanup(db_path: Path, active_ids: set[str]) -> dict[str, int]:
    """Удаляет призрачные строки; возвращает {table: deleted_count}."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    deleted: dict[str, int] = {}

    try:
        conn.execute("BEGIN")
        for table in _GHOST_TABLES:
            try:
                rows = conn.execute(
                    f"SELECT DISTINCT concept FROM {table} WHERE concept IS NOT NULL AND concept != ''"
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            ghost_concepts: list[str] = []
            for row in rows:
                c = str(row["concept"]).strip()
                if c not in active_ids and _is_fixture_concept(c):
                    ghost_concepts.append(c)
            if ghost_concepts:
                placeholders = ",".join("?" for _ in ghost_concepts)
                count = conn.execute(
                    f"DELETE FROM {table} WHERE concept IN ({placeholders})",
                    ghost_concepts,
                ).rowcount
                deleted[table] = count

        raw = conn.execute(
            "SELECT value FROM app_kv WHERE key = ?", (_HEATMAP_KV_KEY,)
        ).fetchone()
        if raw:
            try:
                heatmap_data = json.loads(raw["value"])
            except (json.JSONDecodeError, TypeError):
                heatmap_data = []
            if isinstance(heatmap_data, list):
                cleaned = [
                    e for e in heatmap_data
                    if str(e.get("concept") or "").strip() in active_ids
                    or not _is_fixture_concept(str(e.get("concept") or ""))
                ]
                if len(cleaned) != len(heatmap_data):
                    new_value = json.dumps(cleaned, ensure_ascii=False)
                    conn.execute(
                        "UPDATE app_kv SET value = ?, updated_at = ? WHERE key = ?",
                        (new_value, _utc_iso(), _HEATMAP_KV_KEY),
                    )
                    deleted["app_kv_emotional_heatmap"] = len(heatmap_data) - len(cleaned)

        conn.execute("COMMIT")
    except Exception:  # noqa: BLE001 — rollback must catch any error to prevent partial cleanup
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return deleted


def make_backup(db_path: Path) -> Path:
    backup = db_path.with_name(f"{db_path.stem}_backup_{_utc_iso().replace(':', '-')}.db")
    shutil.copy2(db_path, backup)
    return backup


def get_active_graph_ids() -> set[str]:
    try:
        from app.knowledge_graph import get_active_knowledge_graph

        kg = get_active_knowledge_graph()
        return {
            str(cid).strip()
            for cid, node in kg.get_concepts().items()
            if isinstance(node, dict) and str(cid).strip()
        }
    except Exception:  # noqa: BLE001 — graph load may fail; empty set = no cleanup, safe
        return set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Удаление призрачных (тестовых/fixture) следов из прогресса студента."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Показать, что будет удалено, без изменений (по умолчанию).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Выполнить очистку (требует --confirm-token).",
    )
    parser.add_argument(
        "--confirm-token",
        type=str,
        default=None,
        help=f"Токен подтверждения: {CONFIRM_TOKEN}",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        default=False,
        help="Пропустить создание резервной копии (НЕ рекомендуется).",
    )
    args = parser.parse_args(argv)

    db_path = get_user_state_path()
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 0

    active_ids = get_active_graph_ids()
    print(f"Active graph concept ids: {len(active_ids)}")
    if not active_ids:
        print("WARNING: empty active graph — no cleanup possible without concept references.")
        return 1

    snapshot = collect_ghost_snapshot(db_path, active_ids)

    total_ghosts = sum(len(v) for v in snapshot.values())
    if total_ghosts == 0:
        print("No ghost rows found.")
        return 0

    for table, rows in snapshot.items():
        print(f"\n{table}: {len(rows)} ghost rows")
        if table == "app_kv_emotional_heatmap":
            for r in rows[:10]:
                c = str(r.get("concept") or "")[:30]
                d = str(r.get("date") or "")[:10]
                print(f"  concept={c} date={d}")
            if len(rows) > 10:
                print(f"  ... and {len(rows) - 10} more")
        else:
            concepts = sorted({str(r.get("concept") or "") for r in rows})
            for c in concepts[:15]:
                print(f"  concept={c}")
            if len(concepts) > 15:
                print(f"  ... and {len(concepts) - 15} more concepts")

    if args.confirm:
        if args.confirm_token != CONFIRM_TOKEN:
            print(f"\nERROR: --confirm requires --confirm-token {CONFIRM_TOKEN}")
            return 2
        if not args.no_backup:
            backup = make_backup(db_path)
            print(f"\nBackup created: {backup}")
        deleted = execute_cleanup(db_path, active_ids)
        print("\nCleanup completed:")
        for table, count in deleted.items():
            print(f"  {table}: {count} rows deleted")
    else:
        print(f"\nDRY RUN — no changes made. Total ghost rows: {total_ghosts}")
        print("Re-run with --confirm --confirm-token CLEAN-PROGRESS-GHOSTS to execute.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
