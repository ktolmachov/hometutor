"""Unit tests for the demo Knowledge Graph generation self-heal migration."""

from __future__ import annotations

import json

import pytest

from app import demo_sandbox


def _write_shipped_registry(base_dir, generation_id: str = "gen123") -> None:
    (base_dir / "demo_index_registry.json").write_text(
        json.dumps({"active_generation": {"generation_id": generation_id}}),
        encoding="utf-8",
    )


def _write_shipped_bundle(base_dir, generation_id: str = "gen123", *, with_kg_sqlite: bool = True) -> None:
    bundle = base_dir / "demo_data" / "graph_generations" / "by_generation" / generation_id
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "property_graph_store.json").write_text("{}", encoding="utf-8")
    if with_kg_sqlite:
        (bundle / "kg.sqlite").write_bytes(b"fake-sqlite")


@pytest.fixture()
def demo_mode(monkeypatch):
    monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: True)


@pytest.fixture()
def capture_save_registry(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr("app.index_registry.save_registry_atomic", lambda data: calls.append(data))
    return calls


def test_skips_when_not_demo_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: False)
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    assert demo_sandbox.sync_demo_graph_generation() is False


def test_skips_when_shipped_registry_missing(demo_mode, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    assert demo_sandbox.sync_demo_graph_generation() is False


def test_skips_when_shipped_registry_has_no_generation_id(demo_mode, monkeypatch, tmp_path) -> None:
    (tmp_path / "demo_index_registry.json").write_text(
        json.dumps({"active_generation": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    assert demo_sandbox.sync_demo_graph_generation() is False


def test_skips_when_shipped_bundle_missing_kg_sqlite(demo_mode, monkeypatch, tmp_path) -> None:
    _write_shipped_registry(tmp_path)
    _write_shipped_bundle(tmp_path, with_kg_sqlite=False)
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    assert demo_sandbox.sync_demo_graph_generation() is False


def test_skips_when_live_bundle_already_readable(
    demo_mode, monkeypatch, tmp_path, capture_save_registry
) -> None:
    _write_shipped_registry(tmp_path)
    _write_shipped_bundle(tmp_path)
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    live_dir = tmp_path / "live" / "gen123"
    live_dir.mkdir(parents=True)
    (live_dir / "kg.sqlite").write_bytes(b"already-fine")
    monkeypatch.setattr(
        "app.knowledge_graph._active_graph_bundle_target", lambda: ("gen123", live_dir)
    )

    assert demo_sandbox.sync_demo_graph_generation() is False
    assert capture_save_registry == []


def test_syncs_when_live_bundle_missing(demo_mode, monkeypatch, tmp_path, capture_save_registry) -> None:
    _write_shipped_registry(tmp_path)
    _write_shipped_bundle(tmp_path)
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    live_dir = tmp_path / "live" / "gen123"  # does not exist yet
    monkeypatch.setattr(
        "app.knowledge_graph._active_graph_bundle_target", lambda: ("gen123", live_dir)
    )
    monkeypatch.setattr("app.graph_generation_paths.generation_bundle_dir", lambda gid: live_dir)

    result = demo_sandbox.sync_demo_graph_generation()

    assert result is True
    assert (live_dir / "kg.sqlite").is_file()
    assert (live_dir / "property_graph_store.json").is_file()
    assert len(capture_save_registry) == 1
    assert capture_save_registry[0]["active_generation"]["generation_id"] == "gen123"


def test_syncs_when_resolution_raises(demo_mode, monkeypatch, tmp_path, capture_save_registry) -> None:
    _write_shipped_registry(tmp_path)
    _write_shipped_bundle(tmp_path)
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    def _raise():
        raise RuntimeError("registry unreadable")

    live_dir = tmp_path / "live" / "gen123"
    monkeypatch.setattr("app.knowledge_graph._active_graph_bundle_target", _raise)
    monkeypatch.setattr("app.graph_generation_paths.generation_bundle_dir", lambda gid: live_dir)

    assert demo_sandbox.sync_demo_graph_generation() is True
    assert (live_dir / "kg.sqlite").is_file()


def test_overwrites_stale_live_bundle_directory(
    demo_mode, monkeypatch, tmp_path, capture_save_registry
) -> None:
    """A live bundle dir that exists but lacks kg.sqlite (partial/corrupt) must be replaced, not merged."""
    _write_shipped_registry(tmp_path)
    _write_shipped_bundle(tmp_path)
    monkeypatch.setattr(demo_sandbox, "BASE_DIR", tmp_path)

    live_dir = tmp_path / "live" / "gen123"
    live_dir.mkdir(parents=True)
    (live_dir / "stale_leftover.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        "app.knowledge_graph._active_graph_bundle_target", lambda: ("gen123", live_dir)
    )
    monkeypatch.setattr("app.graph_generation_paths.generation_bundle_dir", lambda gid: live_dir)

    assert demo_sandbox.sync_demo_graph_generation() is True
    assert (live_dir / "kg.sqlite").is_file()
    assert not (live_dir / "stale_leftover.txt").exists()
