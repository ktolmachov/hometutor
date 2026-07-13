"""Domain service for the Living Konspekt workbench row contract v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from app.path_safety import data_relative_from_path, resolve_data_relative_path
from app.section_index import IndexedSection, section_to_row

WORKBENCH_KV_KEY = "living_konspekt_workbench_json"
WORKBENCH_GOAL_KV_KEY = "living_konspekt_goal_json"
WORKBENCH_SECTIONS_KEY = "workbench_sections"
ROW_VERSION = 2
PORTABLE = "portable"
NON_PORTABLE = "non_portable"

_CONTENT_FIELDS = (
    "heading_text",
    "slug",
    "level",
    "line_start",
    "line_end",
    "text",
    "own_text",
    "concept",
)
_RESERVED_FIELDS = ("note", "read_at", "listened_at", "knowledge_status", "open_question")


class _UnsetValue:
    pass


_UNSET = _UnsetValue()


class WorkbenchStorage(Protocol):
    def load_json(self) -> list[dict[str, Any]]:
        """Load persisted workbench rows."""

    def save_json(self, rows: list[dict[str, Any]]) -> None:
        """Save persisted workbench rows."""


class UserStateWorkbenchStorage:
    """Production storage adapter backed by app_kv."""

    def load_json(self) -> list[dict[str, Any]]:
        from app.user_state_core import get_kv

        raw = get_kv(WORKBENCH_KV_KEY)
        if not raw:
            return []
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed if isinstance(row, dict)]

    def save_json(self, rows: list[dict[str, Any]]) -> None:
        from app.user_state_core import set_kv

        set_kv(WORKBENCH_KV_KEY, json.dumps(rows, ensure_ascii=False))


class InMemoryWorkbenchStorage:
    """Small storage seam for unit tests and non-Streamlit callers."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])

    def load_json(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows]

    def save_json(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]


def _content_from_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {field: row.get(field) for field in _CONTENT_FIELDS}
    out["heading_text"] = str(out.get("heading_text") or "")
    out["slug"] = str(out.get("slug") or "")
    out["level"] = int(out.get("level") or 0)
    out["line_start"] = int(out.get("line_start") or 0)
    out["line_end"] = int(out.get("line_end") or 0)
    out["text"] = str(out.get("text") or "")
    out["own_text"] = str(out.get("own_text") or "")
    if out.get("concept") is not None:
        out["concept"] = str(out.get("concept"))
    return out


def _basename_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return Path(raw).name or raw


def _portable_row_key(konspekt_md_rel: str, line_start: int) -> str:
    return f"p:{konspekt_md_rel}:{int(line_start or 0)}"


def _non_portable_row_key(row: dict[str, Any]) -> str:
    identity = {
        "konspekt_md_label": str(row.get("konspekt_md_label") or ""),
        "source_label": str(row.get("source_label") or ""),
        "heading_text": str(row.get("heading_text") or ""),
        "line_start": int(row.get("line_start") or 0),
        "line_end": int(row.get("line_end") or 0),
        "text": str(row.get("text") or ""),
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"np:{digest}"


def _non_portable_persisted_from_row(row: dict[str, Any], *, resolve_error: str) -> dict[str, Any]:
    out = {
        "row_version": ROW_VERSION,
        "portability_status": NON_PORTABLE,
        "konspekt_md_label": _basename_label(row.get("konspekt_md_label") or row.get("konspekt_md_abs")),
        "source_label": _basename_label(row.get("source_label") or row.get("source_abs")),
        "resolve_error": resolve_error,
    }
    out.update(_content_from_row(row))
    for field in _RESERVED_FIELDS:
        out[field] = row.get(field) if row.get(field) is not None else None
    out["row_key"] = str(row.get("row_key") or _non_portable_row_key(out))
    return out


def persisted_row_from_runtime(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a runtime/base row to the v2 persisted schema."""
    if str(row.get("portability_status") or "") == NON_PORTABLE:
        return _non_portable_persisted_from_row(row, resolve_error=str(row.get("resolve_error") or "non_portable"))

    try:
        md_rel = str(row.get("konspekt_md_rel") or data_relative_from_path(row.get("konspekt_md_abs") or ""))
        source_rel = str(row.get("source_rel") or data_relative_from_path(row.get("source_abs") or ""))
    except ValueError:
        return _non_portable_persisted_from_row(row, resolve_error="outside_data_dir")

    out = {
        "row_key": _portable_row_key(md_rel, int(row.get("line_start") or 0)),
        "konspekt_md_rel": md_rel,
        "source_rel": source_rel,
        "row_version": ROW_VERSION,
        "portability_status": PORTABLE,
    }
    out.update(_content_from_row(row))
    for field in _RESERVED_FIELDS:
        out[field] = row.get(field) if row.get(field) is not None else None
    return out


def runtime_row_from_persisted(row: dict[str, Any]) -> dict[str, Any]:
    """Hydrate a persisted v2 row into the runtime shape consumed by UI code."""
    status = str(row.get("portability_status") or PORTABLE)
    if status == NON_PORTABLE or not row.get("konspekt_md_rel"):
        out = {
            "row_key": str(row.get("row_key") or _non_portable_row_key(row)),
            "konspekt_md_abs": "",
            "source_abs": "",
            "portability_status": NON_PORTABLE,
            "konspekt_md_label": _basename_label(row.get("konspekt_md_label")),
            "source_label": _basename_label(row.get("source_label")),
            "resolve_error": str(row.get("resolve_error") or "non_portable"),
        }
        out.update(_content_from_row(row))
        for field in _RESERVED_FIELDS:
            out[field] = row.get(field) if row.get(field) is not None else None
        return out

    try:
        md_abs = resolve_data_relative_path(str(row.get("konspekt_md_rel") or ""))
        source_abs = resolve_data_relative_path(str(row.get("source_rel") or ""))
    except ValueError:
        return runtime_row_from_persisted(
            _non_portable_persisted_from_row(
                {
                    **row,
                    "konspekt_md_label": _basename_label(row.get("konspekt_md_rel")),
                    "source_label": _basename_label(row.get("source_rel")),
                },
                resolve_error="resolve_failed",
            )
        )

    md_rel = str(row.get("konspekt_md_rel") or "")
    out = {
        "row_key": str(row.get("row_key") or _portable_row_key(md_rel, int(row.get("line_start") or 0))),
        "konspekt_md_abs": str(md_abs),
        "source_abs": str(source_abs),
        "portability_status": PORTABLE,
    }
    out.update(_content_from_row(row))
    for field in _RESERVED_FIELDS:
        out[field] = row.get(field) if row.get(field) is not None else None
    return out


def persisted_rows_from_runtime(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("row_version") == ROW_VERSION and not row.get("konspekt_md_abs"):
            out.append(persisted_row_from_runtime(runtime_row_from_persisted(row)))
        else:
            out.append(persisted_row_from_runtime(row))
    return out


def runtime_rows_from_persisted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        persisted = row if row.get("row_version") == ROW_VERSION else persisted_row_from_runtime(row)
        runtime_rows.append(runtime_row_from_persisted(persisted))
    return runtime_rows


def normalize_runtime_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept legacy/runtime/persisted rows and return hydrated runtime rows."""
    runtime_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("row_version") == ROW_VERSION and not row.get("konspekt_md_abs"):
            runtime_rows.append(runtime_row_from_persisted(row))
        else:
            runtime_rows.append(runtime_row_from_persisted(persisted_row_from_runtime(row)))
    return runtime_rows


def load_rows(storage: WorkbenchStorage | None = None) -> list[dict[str, Any]]:
    store = storage or UserStateWorkbenchStorage()
    try:
        persisted_rows = store.load_json()
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    runtime_rows: list[dict[str, Any]] = []
    normalized_persisted: list[dict[str, Any]] = []
    for row in persisted_rows:
        persisted = row if row.get("row_version") == ROW_VERSION else persisted_row_from_runtime(row)
        runtime = runtime_row_from_persisted(persisted)
        normalized = persisted_row_from_runtime(runtime)
        runtime_rows.append(runtime)
        normalized_persisted.append(normalized)

    if normalized_persisted != persisted_rows:
        store.save_json(normalized_persisted)
    return runtime_rows


def save_rows(rows: list[dict[str, Any]], storage: WorkbenchStorage | None = None) -> list[dict[str, Any]]:
    runtime_rows = normalize_runtime_rows(rows)
    (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(runtime_rows))
    return runtime_rows


def normalize_goal(value: Any) -> dict[str, Any]:
    """Normalize the Living Konspekt project goal persisted next to the workbench."""
    if isinstance(value, dict):
        text = str(value.get("text") or "").strip()
        updated_at = str(value.get("updated_at") or "").strip() or None
    else:
        text = str(value or "").strip()
        updated_at = None
    return {"text": text[:500], "updated_at": updated_at}


def load_goal() -> dict[str, Any]:
    from app.user_state_core import get_kv

    raw = get_kv(WORKBENCH_GOAL_KV_KEY)
    if not raw:
        return normalize_goal(None)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return normalize_goal(None)
    return normalize_goal(parsed)


def save_goal(goal: Any) -> dict[str, Any]:
    from datetime import datetime, timezone

    from app.user_state_core import set_kv

    normalized = normalize_goal(goal)
    if normalized["text"]:
        normalized["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    set_kv(WORKBENCH_GOAL_KV_KEY, json.dumps(normalized, ensure_ascii=False))
    return normalized


def add_section(
    current_rows: list[dict[str, Any]],
    section: IndexedSection,
    storage: WorkbenchStorage | None = None,
) -> list[dict[str, Any]]:
    rows = normalize_runtime_rows(current_rows)
    new_row = runtime_row_from_persisted(persisted_row_from_runtime(section_to_row(section)))
    if any(str(row.get("row_key") or "") == str(new_row.get("row_key") or "") for row in rows):
        (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(rows))
        return rows
    rows.append(new_row)
    (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(rows))
    return rows


def move_section(
    current_rows: list[dict[str, Any]],
    row_key: str,
    delta: int,
    storage: WorkbenchStorage | None = None,
) -> list[dict[str, Any]]:
    rows = normalize_runtime_rows(current_rows)
    idx = next((i for i, row in enumerate(rows) if str(row.get("row_key") or "") == row_key), None)
    if idx is None:
        return rows
    new_idx = idx + int(delta)
    if not 0 <= new_idx < len(rows):
        return rows
    rows.insert(new_idx, rows.pop(idx))
    (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(rows))
    return rows


def remove_section(
    current_rows: list[dict[str, Any]],
    row_key: str,
    storage: WorkbenchStorage | None = None,
) -> list[dict[str, Any]]:
    rows = normalize_runtime_rows(current_rows)
    new_rows = [row for row in rows if str(row.get("row_key") or "") != row_key]
    (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(new_rows))
    return new_rows


def remove_sections(
    current_rows: list[dict[str, Any]],
    row_keys: set[str] | list[str] | tuple[str, ...],
    storage: WorkbenchStorage | None = None,
) -> list[dict[str, Any]]:
    rows = normalize_runtime_rows(current_rows)
    keys = {str(row_key) for row_key in row_keys}
    new_rows = [row for row in rows if str(row.get("row_key") or "") not in keys]
    (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(new_rows))
    return new_rows


def clear_rows(storage: WorkbenchStorage | None = None) -> list[dict[str, Any]]:
    (storage or UserStateWorkbenchStorage()).save_json([])
    return []


def update_section_fields(
    current_rows: list[dict[str, Any]],
    row_key: str,
    *,
    note: str | None | _UnsetValue = _UNSET,
    read_at: str | None | _UnsetValue = _UNSET,
    listened_at: str | None | _UnsetValue = _UNSET,
    knowledge_status: str | None | _UnsetValue = _UNSET,
    open_question: str | None | _UnsetValue = _UNSET,
    storage: WorkbenchStorage | None = None,
) -> list[dict[str, Any]]:
    rows = normalize_runtime_rows(current_rows)
    changed = False
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("row_key") or "") != row_key:
            new_rows.append(row)
            continue
        updated = dict(row)
        if not isinstance(note, _UnsetValue):
            updated["note"] = (note or "").strip() or None
        if not isinstance(read_at, _UnsetValue):
            updated["read_at"] = read_at
        if not isinstance(listened_at, _UnsetValue):
            updated["listened_at"] = listened_at
        if not isinstance(knowledge_status, _UnsetValue):
            # A2: validated simple enum or None (backward safe). Invalid -> None (silent to not break UI).
            valid = {"understood", "unsure", "unclear"}
            updated["knowledge_status"] = knowledge_status if (knowledge_status in valid or knowledge_status is None) else None
        if not isinstance(open_question, _UnsetValue):
            updated["open_question"] = (open_question or "").strip() or None
        changed = changed or updated != row
        new_rows.append(updated)
    if changed:
        (storage or UserStateWorkbenchStorage()).save_json(persisted_rows_from_runtime(new_rows))
    return new_rows


__all__ = [
    "clear_rows",
    "InMemoryWorkbenchStorage",
    "NON_PORTABLE",
    "PORTABLE",
    "ROW_VERSION",
    "UserStateWorkbenchStorage",
    "WORKBENCH_GOAL_KV_KEY",
    "WORKBENCH_KV_KEY",
    "WORKBENCH_SECTIONS_KEY",
    "WorkbenchStorage",
    "add_section",
    "load_rows",
    "load_goal",
    "move_section",
    "normalize_runtime_rows",
    "persisted_row_from_runtime",
    "persisted_rows_from_runtime",
    "remove_section",
    "remove_sections",
    "runtime_row_from_persisted",
    "runtime_rows_from_persisted",
    "save_rows",
    "save_goal",
    "normalize_goal",
    "update_section_fields",
]
