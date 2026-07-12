import pytest

import app.ui_preferences as prefs
from app.ui.feature_registry import feature_by_id


@pytest.fixture()
def kv_store(monkeypatch):
    store: dict[str, str] = {}

    def fake_get_kv(key: str, default: str | None = None) -> str | None:
        return store.get(key, default)

    def fake_set_kv(key: str, value: str) -> None:
        store[key] = value

    monkeypatch.setattr(prefs, "_read_raw_kv", fake_get_kv)
    monkeypatch.setattr(prefs, "_write_raw_kv", fake_set_kv)
    monkeypatch.setattr(prefs, "_ensure_auth_context", lambda: None)
    monkeypatch.setattr(prefs, "_maybe_migrate_global_ui_prefs", lambda: None)
    return store


def test_existing_user_migrates_to_all(kv_store, monkeypatch) -> None:
    monkeypatch.setattr(prefs, "_has_existing_activity", lambda: True)

    assert prefs.get_ui_level() == prefs.LEVEL_ALL
    assert kv_store[prefs.UI_LEVEL_KEY] == prefs.LEVEL_ALL


def test_new_user_defaults_to_level_1_without_persisting(kv_store, monkeypatch) -> None:
    monkeypatch.setattr(prefs, "_has_existing_activity", lambda: False)

    assert prefs.get_ui_level() == "1"
    assert prefs.UI_LEVEL_KEY not in kv_store


def test_set_ui_level_validates_and_clears_overrides(kv_store) -> None:
    prefs.set_override("view:metrics", True)
    assert prefs.get_overrides() == {"view:metrics": True}

    prefs.set_ui_level("2")

    assert kv_store[prefs.UI_LEVEL_KEY] == "2"
    assert prefs.get_overrides() == {}


def test_set_ui_level_rejects_unknown_level() -> None:
    with pytest.raises(ValueError):
        prefs.set_ui_level("expert")


def test_ui_prefs_migrate_from_global_db_for_auth_user(tmp_path, monkeypatch) -> None:
    """Настройки из глобальной БД переносятся в per-user профиль при первом чтении."""
    monkeypatch.setenv("USER_STATE_DB", str(tmp_path / "user_state.db"))
    from app import config
    from app.auth_context import set_current_user_id
    from app.user_state import get_kv, set_kv
    from app.user_state_db import reset_schema_cache_for_tests

    config.reset_settings_cache()
    reset_schema_cache_for_tests()
    try:
        set_kv("ui_level", "3")
        set_kv("ui_feature_overrides", '{"view:metrics": true}')

        set_current_user_id("user-a")
        config.reset_settings_cache()
        reset_schema_cache_for_tests()

        assert prefs.get_ui_level() == "3"
        assert prefs.get_overrides() == {"view:metrics": True}
        assert get_kv("ui_level") == "3"
        assert get_kv("ui_feature_overrides") == '{"view:metrics": true}'
    finally:
        set_current_user_id(None)
        config.reset_settings_cache()
        reset_schema_cache_for_tests()


def test_get_ui_theme_defaults_to_forest(kv_store) -> None:
    assert prefs.get_ui_theme() == "forest"
    assert prefs.UI_THEME_KEY not in kv_store


def test_set_ui_theme_persists(kv_store) -> None:
    prefs.set_ui_theme("ocean")
    assert kv_store[prefs.UI_THEME_KEY] == "ocean"
    assert prefs.get_ui_theme() == "ocean"


def test_set_ui_theme_rejects_unknown(kv_store) -> None:
    with pytest.raises(ValueError, match="unsupported UI theme"):
        prefs.set_ui_theme("vaporwave")


def test_get_ui_theme_falls_back_on_invalid_stored(kv_store) -> None:
    kv_store[prefs.UI_THEME_KEY] = "vaporwave"
    assert prefs.get_ui_theme() == "forest"


def test_feature_visible_honors_level_and_override() -> None:
    spec = feature_by_id("view:metrics")
    assert spec is not None

    assert prefs.feature_visible(spec, level="1", overrides={}) is False
    assert prefs.feature_visible(spec, level=prefs.LEVEL_ALL, overrides={}) is True
    assert prefs.feature_visible(spec, level="1", overrides={spec.id: True}) is True
    assert prefs.feature_visible(spec, level=prefs.LEVEL_ALL, overrides={spec.id: False}) is False
