"""Пользовательские настройки видимости UI поверх user_state KV (app_kv)."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.auth_context import get_current_user_id, reset_current_user_id, set_current_user_id
from app.user_state import get_kv, set_kv

logger = logging.getLogger(__name__)

UI_LEVEL_KEY = "ui_level"
UI_OVERRIDES_KEY = "ui_feature_overrides"
UI_THEME_KEY = "ui_theme"

# Three presets: Учёба (day-to-day learning loop), Полный (courses/plans/graph),
# Диагностика (metrics/trace/index — operator surface). Collapsed down from a
# legacy 6-level scheme (tiers "1".."5" + "all") that split one audience across
# too many cards; feature tiers 1-5 in feature_registry.py still exist and are
# bucketed into these three via _TIER_LEVEL below.
LEVEL_STUDY = "study"
LEVEL_FULL = "full"
LEVEL_DIAGNOSTIC = "diagnostic"
VALID_UI_LEVELS = frozenset({LEVEL_STUDY, LEVEL_FULL, LEVEL_DIAGNOSTIC})

# Legacy stored values (pre-collapse) map onto the new presets so existing
# per-user KV rows keep working without a migration script.
_LEGACY_LEVEL_MAP: dict[str, str] = {
    "1": LEVEL_STUDY,
    "2": LEVEL_STUDY,
    "3": LEVEL_FULL,
    "4": LEVEL_DIAGNOSTIC,
    "5": LEVEL_DIAGNOSTIC,
    "all": LEVEL_DIAGNOSTIC,
}
_LEVEL_ORDER: dict[str, int] = {LEVEL_STUDY: 0, LEVEL_FULL: 1, LEVEL_DIAGNOSTIC: 2}
_TIER_LEVEL: dict[int, str] = {
    1: LEVEL_STUDY,
    2: LEVEL_STUDY,
    3: LEVEL_FULL,
    4: LEVEL_DIAGNOSTIC,
    5: LEVEL_DIAGNOSTIC,
}


def _ensure_auth_context() -> None:
    from app.ui.auth_gate import ensure_streamlit_auth_context

    ensure_streamlit_auth_context()


def _read_global_kv(key: str, default: str | None = None) -> str | None:
    """Прочитать ключ из глобального user_state.db (без per-user префикса)."""
    uid = (get_current_user_id() or "").strip()
    if not uid:
        return default
    token = set_current_user_id(None)
    try:
        return get_kv(key, default)
    except Exception:  # noqa: BLE001 - migration must not break reads
        return default
    finally:
        reset_current_user_id(token)


def _maybe_migrate_global_ui_prefs() -> None:
    """Один раз скопировать ui_level/overrides/theme из глобальной БД в per-user профиль."""
    if not (get_current_user_id() or "").strip():
        return
    if _read_raw_kv(UI_LEVEL_KEY):
        return
    global_level = _read_global_kv(UI_LEVEL_KEY)
    global_overrides = _read_global_kv(UI_OVERRIDES_KEY)
    global_theme = _read_global_kv(UI_THEME_KEY)
    if global_level:
        _write_raw_kv(UI_LEVEL_KEY, global_level)
    if global_overrides:
        _write_raw_kv(UI_OVERRIDES_KEY, global_overrides)
    if global_theme:
        _write_raw_kv(UI_THEME_KEY, global_theme)


def _read_raw_kv(key: str, default: str | None = None) -> str | None:
    try:
        return get_kv(key, default)
    except Exception:  # noqa: BLE001 - UI preferences must not break startup.
        return default


def _write_raw_kv(key: str, value: str) -> None:
    try:
        set_kv(key, value)
    except Exception as exc:  # noqa: BLE001 - log, но не ломаем UI
        logger.warning("ui_preferences set_kv failed for %r: %s", key, exc)


def _safe_get_kv(key: str, default: str | None = None) -> str | None:
    _ensure_auth_context()
    if key in (UI_LEVEL_KEY, UI_OVERRIDES_KEY, UI_THEME_KEY):
        _maybe_migrate_global_ui_prefs()
    return _read_raw_kv(key, default)


def _safe_set_kv(key: str, value: str) -> None:
    _ensure_auth_context()
    _write_raw_kv(key, value)


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
    if raw in _LEGACY_LEVEL_MAP:
        migrated = _LEGACY_LEVEL_MAP[raw]
        _safe_set_kv(UI_LEVEL_KEY, migrated)
        return migrated
    if _has_existing_activity():
        _safe_set_kv(UI_LEVEL_KEY, LEVEL_DIAGNOSTIC)
        return LEVEL_DIAGNOSTIC
    return LEVEL_STUDY


def set_ui_level(level: str) -> None:
    value = str(level or "").strip().lower()
    if value not in VALID_UI_LEVELS:
        raise ValueError(f"unsupported UI level: {level!r}")
    _safe_set_kv(UI_LEVEL_KEY, value)
    clear_overrides()


def ensure_min_ui_level(level: str) -> None:
    """Raise the stored UI level to at least ``level`` without clearing overrides.

    For automatic promotions (e.g. activating a course should reveal the
    course/plan/graph views even if the learner never opened the control
    panel). Never downgrades, and unlike :func:`set_ui_level` this is a silent
    background nudge, not a deliberate preset switch, so overrides survive it.
    """
    value = str(level or "").strip().lower()
    if value not in VALID_UI_LEVELS:
        raise ValueError(f"unsupported UI level: {level!r}")
    current = get_ui_level()
    if _LEVEL_ORDER.get(current, 0) >= _LEVEL_ORDER.get(value, 0):
        return
    _safe_set_kv(UI_LEVEL_KEY, value)


def get_ui_theme() -> str:
    from app.ui.theme_presets import VALID_UI_THEMES

    raw = str(_safe_get_kv(UI_THEME_KEY, "") or "").strip().lower()
    if raw in VALID_UI_THEMES:
        return raw
    return "forest"


def set_ui_theme(theme_id: str) -> None:
    from app.ui.theme_presets import VALID_UI_THEMES

    value = str(theme_id or "").strip().lower()
    if value not in VALID_UI_THEMES:
        raise ValueError(f"unsupported UI theme: {theme_id!r}")
    _safe_set_kv(UI_THEME_KEY, value)


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
    resolved = _LEGACY_LEVEL_MAP.get(str(level or "").strip().lower(), level)
    tier_level = _TIER_LEVEL.get(int(spec_tier), LEVEL_DIAGNOSTIC)
    return _LEVEL_ORDER.get(tier_level, 2) <= _LEVEL_ORDER.get(resolved, 2)


def tier_level(spec_tier: int) -> str:
    """Return which of the three presets a feature-registry tier (1-5) belongs to."""
    return _TIER_LEVEL.get(int(spec_tier), LEVEL_DIAGNOSTIC)


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
