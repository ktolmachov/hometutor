"""Workbench-state adapters для Живого конспекта.

Тонкий Streamlit-слой над ``app.workbench_service``: корзина живёт в
``st.session_state`` как реактивное зеркало, персистентность и доменный контракт —
в сервисе. Вынесено из ``living_konspekt_view`` (size-budget): рендеринг остался во
view, управление состоянием — здесь. Реэкспортируется из view для совместимости с
соседними UI-модулями и тестами.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, MutableMapping

import streamlit as st

from app import workbench_service
from app.section_index import IndexedSection

WORKBENCH_SECTIONS_KEY = workbench_service.WORKBENCH_SECTIONS_KEY
_WORKBENCH_KV_KEY = workbench_service.WORKBENCH_KV_KEY
_WORKBENCH_HYDRATED_KEY = "_workbench_hydrated"
_WORKBENCH_GOAL_HYDRATED_KEY = "_living_konspekt_goal_hydrated"
_WORKBENCH_GOAL_KEY = "living_konspekt_goal"


def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    return state if state is not None else st.session_state


def _ensure_auth_context() -> None:
    from app.ui.auth_gate import ensure_streamlit_auth_context

    ensure_streamlit_auth_context()


def ensure_workbench_hydrated(state: MutableMapping[str, Any] | None = None) -> None:
    """Один раз за сессию поднять runtime rows из ``app_kv`` через сервис."""
    target = _state(state)
    if target.get(_WORKBENCH_HYDRATED_KEY):
        return
    target[_WORKBENCH_HYDRATED_KEY] = True
    if WORKBENCH_SECTIONS_KEY in target:
        target[WORKBENCH_SECTIONS_KEY] = workbench_service.normalize_runtime_rows(
            list(target.get(WORKBENCH_SECTIONS_KEY) or [])
        )
        return
    if state is not None:
        target[WORKBENCH_SECTIONS_KEY] = []
        return
    try:
        _ensure_auth_context()
        target[WORKBENCH_SECTIONS_KEY] = workbench_service.load_rows()
    except Exception:  # noqa: BLE001 - недоступный профиль → пустая корзина, не падение
        return


def ensure_project_goal_hydrated(state: MutableMapping[str, Any] | None = None) -> None:
    target = _state(state)
    if target.get(_WORKBENCH_GOAL_HYDRATED_KEY):
        return
    target[_WORKBENCH_GOAL_HYDRATED_KEY] = True
    if _WORKBENCH_GOAL_KEY in target:
        target[_WORKBENCH_GOAL_KEY] = workbench_service.normalize_goal(target.get(_WORKBENCH_GOAL_KEY))
        return
    if state is not None:
        target[_WORKBENCH_GOAL_KEY] = workbench_service.normalize_goal(None)
        return
    try:
        _ensure_auth_context()
        target[_WORKBENCH_GOAL_KEY] = workbench_service.load_goal()
    except Exception:  # noqa: BLE001 - goal is optional; workbench still renders
        target[_WORKBENCH_GOAL_KEY] = workbench_service.normalize_goal(None)


def set_workbench_rows(
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Заменить корзину целиком (restore research-сессии) + авто-персист через сервис."""
    target = _state(state)
    runtime_rows = workbench_service.normalize_runtime_rows([row for row in rows if isinstance(row, dict)])
    target[WORKBENCH_SECTIONS_KEY] = runtime_rows
    target[_WORKBENCH_HYDRATED_KEY] = True
    if state is None:
        try:
            _ensure_auth_context()
            workbench_service.save_rows(runtime_rows)
        except Exception:  # noqa: BLE001 - restore не должен падать из-за авто-персиста
            pass


def get_workbench_rows(state: MutableMapping[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = _state(state).get(WORKBENCH_SECTIONS_KEY)
    return rows if isinstance(rows, list) else []


def get_project_goal(state: MutableMapping[str, Any] | None = None) -> dict[str, Any]:
    ensure_project_goal_hydrated(state)
    return workbench_service.normalize_goal(_state(state).get(_WORKBENCH_GOAL_KEY))


def set_project_goal(goal: dict[str, Any], state: MutableMapping[str, Any] | None = None) -> dict[str, Any]:
    target = _state(state)
    normalized = workbench_service.normalize_goal(goal)
    if state is None:
        try:
            _ensure_auth_context()
            normalized = workbench_service.save_goal(normalized)
        except Exception:  # noqa: BLE001 - goal persistence must not break the workbench
            pass
    target[_WORKBENCH_GOAL_KEY] = normalized
    target["living_konspekt_goal_text"] = str(normalized.get("text") or "")
    target[_WORKBENCH_GOAL_HYDRATED_KEY] = True
    return normalized


# TODO(W4-cleanup): внутренние UI-модули фичи ещё импортируют эти адаптеры из view;
# внешний доменный контракт уже живёт в app.workbench_service.
def add_section_to_workbench(
    section: IndexedSection,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Добавить раздел в session_state-зеркало; доменная операция живёт в сервисе."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    before = {str(row.get("row_key") or "") for row in rows}
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    new_rows = workbench_service.add_section(rows, section, storage=storage)
    target[WORKBENCH_SECTIONS_KEY] = new_rows
    added = any(str(row.get("row_key") or "") not in before for row in new_rows)
    if state is None and added:
        try:
            # Funnel «чтение → обучение»: раздел добавлен (из графа/карточки/сбора по концепту).
            from app.ui_events import track_event

            track_event("living_konspekt_section_added")
        except Exception:  # noqa: BLE001 - аналитика не должна ломать корзину
            pass
    return added


def move_section_in_workbench(
    row_key: str,
    delta: int,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Сдвинуть раздел по ``row_key``; доменная операция живёт в сервисе."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    new_rows = workbench_service.move_section(rows, row_key, delta, storage=storage)
    changed = [row.get("row_key") for row in new_rows] != [row.get("row_key") for row in rows]
    target[WORKBENCH_SECTIONS_KEY] = new_rows
    return changed


def remove_section_from_workbench(
    row_key: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.remove_section(rows, row_key, storage=storage)


def remove_sections_from_workbench(
    row_keys: set[str],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.remove_sections(rows, row_keys, storage=storage)


def clear_workbench(state: MutableMapping[str, Any] | None = None) -> None:
    target = _state(state)
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.clear_rows(storage=storage)


def update_section_note_in_workbench(
    row_key: str,
    note: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        note=note,
        storage=storage,
    )


def mark_section_read_in_workbench(
    row_key: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    read_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        read_at=read_at,
        storage=storage,
    )


def mark_section_listened_in_workbench(
    row_key: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Record that an audio fragment for the section was activated (listened)."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    listened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        listened_at=listened_at,
        storage=storage,
    )


def set_knowledge_status_in_workbench(
    row_key: str,
    status: str | None,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """A2: understood / unsure / unclear (or None to clear).
    Per plan: also updates read_at as date of last status.
    """
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    read_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        knowledge_status=status,
        read_at=read_at,
        storage=storage,
    )


def set_open_question_in_workbench(
    row_key: str,
    question: str | None,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """A2: student's open question for the section."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        open_question=question,
        storage=storage,
    )
