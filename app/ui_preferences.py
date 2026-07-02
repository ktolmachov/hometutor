"""Пользовательские настройки видимости UI поверх user_state KV (app_kv)."""
from __future__ import annotations

import json
from typing import Any

from app.user_state import get_kv, set_kv

UI_LEVEL_KEY = "ui_level"
UI_OVERRIDES_KEY = "ui_feature_overrides"
LEVEL_ALL = "all"
VALID_UI_LEVELS = frozenset({"1", "2", "3", "4", "5", LEVEL_ALL})


def _safe_get_kv(key: str, default: str | None = None) -> str | None:
    try:
        return get_kv(key, default)
    except Exception:  # noqa: BLE001 - UI preferences must not break startup.
        return default


def _safe_set_kv(key: str, value: str) -> None:
    try:
        set_kv(key, value)
    except Exception:  # noqa: BLE001
        return


def _has_existing_activity() -> bool:
    try:
        if _safe_get_kv("onboarding_v1_done") == "1":
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.history_service import get_history

        if int((get_history(limit=1) or {}).get("total") or 0) > 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.user_state_flashcards import list_flashcard_decks

        if list_flashcard_decks():
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app import user_state

        if int(user_state.count_due_flashcards() or 0) > 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def get_ui_level() -> str:
    raw = str(_safe_get_kv(UI_LEVEL_KEY, "") or "").strip().lower()
    if raw in VALID_UI_LEVELS:
        return raw
    if _has_existing_activity():
        _safe_set_kv(UI_LEVEL_KEY, LEVEL_ALL)
        return LEVEL_ALL
    return "1"


def set_ui_level(level: str) -> None:
    value = str(level or "").strip().lower()
    if value not in VALID_UI_LEVELS:
        raise ValueError(f"unsupported UI level: {level!r}")
    _safe_set_kv(UI_LEVEL_KEY, value)
    clear_overrides()


def get_overrides() -> dict[str, bool]:
    raw = _safe_get_kv(UI_OVERRIDES_KEY, "{}") or "{}"
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): bool(value) for key, value in data.items() if str(key).strip()}


def set_override(feature_id: str, enabled: bool) -> None:
    key = str(feature_id or "").strip()
    if not key:
        return
    overrides = get_overrides()
    overrides[key] = bool(enabled)
    _safe_set_kv(UI_OVERRIDES_KEY, json.dumps(overrides, ensure_ascii=False, sort_keys=True))


def clear_overrides() -> None:
    _safe_set_kv(UI_OVERRIDES_KEY, "{}")


def level_allows(spec_tier: int, level: str) -> bool:
    if level == LEVEL_ALL:
        return True
    return int(spec_tier) <= int(level)


def feature_visible(
    spec: Any,
    *,
    level: str,
    overrides: dict[str, bool],
    context_ok: bool = True,
) -> bool:
    spec_id = str(getattr(spec, "id", "") or "")
    if spec_id in overrides:
        return bool(overrides[spec_id]) and context_ok
    return level_allows(int(getattr(spec, "tier")), level) and context_ok


def feature_visible_by_id(feature_id: str, *, context_ok: bool = True) -> bool:
    from app.ui.feature_registry import context_ok_for_feature, feature_by_id

    spec = feature_by_id(feature_id)
    if spec is None:
        return True
    return feature_visible(
        spec,
        level=get_ui_level(),
        overrides=get_overrides(),
        context_ok=context_ok and context_ok_for_feature(spec),
    )
