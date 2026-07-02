from app import config, user_state, user_state_db
from app.ui_preferences import UI_LEVEL_KEY, UI_OVERRIDES_KEY


def test_ui_preferences_are_exported_and_imported_with_sync_bundle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USER_STATE_DB", str(tmp_path / "user_state.db"))
    config.reset_settings_cache()
    user_state_db.reset_schema_cache_for_tests()
    try:
        user_state.set_kv(UI_LEVEL_KEY, "4")
        user_state.set_kv(UI_OVERRIDES_KEY, '{"view:metrics": true}')

        bundle = user_state.export_full_sync_bundle()
        app_kv_rows = bundle["tables"]["app_kv"]
        exported = {row["key"]: row["value"] for row in app_kv_rows}
        assert exported[UI_LEVEL_KEY] == "4"
        assert exported[UI_OVERRIDES_KEY] == '{"view:metrics": true}'

        user_state.set_kv(UI_LEVEL_KEY, "1")
        user_state.set_kv(UI_OVERRIDES_KEY, "{}")

        user_state.import_full_sync_bundle(bundle)

        assert user_state.get_kv(UI_LEVEL_KEY) == "4"
        assert user_state.get_kv(UI_OVERRIDES_KEY) == '{"view:metrics": true}'
    finally:
        config.reset_settings_cache()
        user_state_db.reset_schema_cache_for_tests()
