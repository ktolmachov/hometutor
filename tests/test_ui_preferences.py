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

    monkeypatch.setattr(prefs, "get_kv", fake_get_kv)
    monkeypatch.setattr(prefs, "set_kv", fake_set_kv)
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


def test_feature_visible_honors_level_and_override() -> None:
    spec = feature_by_id("view:metrics")
    assert spec is not None

    assert prefs.feature_visible(spec, level="1", overrides={}) is False
    assert prefs.feature_visible(spec, level=prefs.LEVEL_ALL, overrides={}) is True
    assert prefs.feature_visible(spec, level="1", overrides={spec.id: True}) is True
    assert prefs.feature_visible(spec, level=prefs.LEVEL_ALL, overrides={spec.id: False}) is False
