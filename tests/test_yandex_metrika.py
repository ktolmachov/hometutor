"""Workstream E: инъекция Яндекс.Метрики в index.html Streamlit (app/ui/analytics.py)."""
from __future__ import annotations

from app import config
from app.ui import analytics


def _fake_streamlit_module(tmp_path, monkeypatch):
    static_dir = tmp_path / "streamlit_pkg" / "static"
    static_dir.mkdir(parents=True)
    index_path = static_dir / "index.html"
    index_path.write_text("<html><head><title>x</title></head><body></body></html>", encoding="utf-8")

    import types

    fake_module = types.ModuleType("streamlit")
    fake_module.__file__ = str(tmp_path / "streamlit_pkg" / "__init__.py")
    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_module)
    return index_path


def test_noop_without_counter_id(monkeypatch):
    monkeypatch.delenv("YANDEX_METRIKA_ID", raising=False)
    config.reset_settings_cache()
    analytics.inject_yandex_metrika()  # must not raise even without streamlit static dir


def test_injects_snippet_once(tmp_path, monkeypatch):
    index_path = _fake_streamlit_module(tmp_path, monkeypatch)
    monkeypatch.setenv("YANDEX_METRIKA_ID", "12345678")
    config.reset_settings_cache()

    analytics.inject_yandex_metrika()
    html = index_path.read_text(encoding="utf-8")
    assert "12345678" in html
    assert analytics._MARKER in html

    analytics.inject_yandex_metrika()
    html_twice = index_path.read_text(encoding="utf-8")
    assert html_twice.count(analytics._MARKER) == 1
