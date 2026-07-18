"""Owner course order for hall lanes / library schedule (presentation only).

Stored in UI session (or any mutable mapping). Never writes curriculum
``precedes`` edges — only affects paint order and recommendations.
"""

from __future__ import annotations

from typing import Any, MutableMapping, Sequence

from app.course_lanes import resolve_course_order

# Session / state key shared by Library schedule and Knowledge Graph hall.
COURSE_OWNER_ORDER_KEY = "library_course_owner_order"


def read_course_owner_order(state: MutableMapping[str, Any] | None) -> list[str]:
    """Return owner order list from state (empty if unset)."""
    if state is None:
        return []
    raw = state.get(COURSE_OWNER_ORDER_KEY)
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item or "").strip().replace("\\", "/")
        if name and name not in seen:
            out.append(name)
            seen.add(name)
    return out


def write_course_owner_order(
    state: MutableMapping[str, Any],
    order: Sequence[str],
) -> list[str]:
    """Persist normalized order into state; return the written list."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in order or []:
        name = str(item or "").strip().replace("\\", "/")
        if name and name not in seen:
            cleaned.append(name)
            seen.add(name)
    state[COURSE_OWNER_ORDER_KEY] = cleaned
    return cleaned


def merge_owner_order_with_available(
    available: Sequence[str],
    *,
    owner_order: Sequence[str] | None = None,
) -> list[str]:
    """Owner pins first, then remaining courses (stable)."""
    return resolve_course_order(available, owner_order=owner_order)


def move_course_in_order(
    order: Sequence[str],
    folder_rel: str,
    *,
    delta: int,
) -> list[str]:
    """Move ``folder_rel`` by ``delta`` (-1 up, +1 down). No-op if missing/bounds."""
    items = [str(x).strip().replace("\\", "/") for x in order if str(x).strip()]
    key = str(folder_rel or "").strip().replace("\\", "/")
    if not key or key not in items or delta == 0:
        return items
    idx = items.index(key)
    new_idx = idx + int(delta)
    if new_idx < 0 or new_idx >= len(items):
        return items
    items.pop(idx)
    items.insert(new_idx, key)
    return items


__all__ = [
    "COURSE_OWNER_ORDER_KEY",
    "merge_owner_order_with_available",
    "move_course_in_order",
    "read_course_owner_order",
    "write_course_owner_order",
]
