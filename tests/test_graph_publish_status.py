import json
from pathlib import Path

from app.graph_publish_status import get_graph_publish_status


def _write_registry(path: Path, *, active_gid: str, previous_gid: str | None = None) -> None:
    previous = None
    if previous_gid:
        previous = {
            "generation_id": previous_gid,
            "chunks_collection": f"{previous_gid}_chunks",
            "summaries_collection": f"{previous_gid}_summaries",
        }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "index_version": 2,
                "active_generation": {
                    "generation_id": active_gid,
                    "chunks_collection": f"{active_gid}_chunks",
                    "summaries_collection": f"{active_gid}_summaries",
                },
                "previous_generation": previous,
                "staging_generation": None,
                "last_failed_generation": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_bundle(root: Path, generation_id: str, *, gate_passed: bool = True) -> None:
    bundle_dir = root / generation_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "kg.sqlite").write_bytes(b"placeholder")
    (bundle_dir / "graph_quality_report.json").write_text(
        json.dumps(
            {
                "generation_id": generation_id,
                "gate_passed": gate_passed,
                "published": gate_passed,
                "metrics": {"concept_count": 7},
                "fail_reasons": [] if gate_passed else ["blocked"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_publish_status_falls_back_to_previous_when_active_bundle_missing(tmp_path, monkeypatch):
    from app import graph_generation_paths, index_registry

    registry_path = tmp_path / "index_registry.json"
    monkeypatch.setattr(index_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(index_registry, "REGISTRY_LOCK_PATH", tmp_path / "index_registry.lock")
    by_generation = tmp_path / "graph_generations" / "by_generation"
    staging = tmp_path / "graph_generations" / "staging"
    monkeypatch.setattr(graph_generation_paths, "BY_GENERATION_ROOT", by_generation)
    monkeypatch.setattr(graph_generation_paths, "STAGING_ROOT", staging)

    _write_registry(registry_path, active_gid="active-gen", previous_gid="previous-gen")
    _write_bundle(by_generation, "previous-gen")
    _write_bundle(staging, "staging-failed", gate_passed=False)

    status = get_graph_publish_status()

    assert status["reader_source"] == "previous"
    assert status["reader_generation_id"] == "previous-gen"
    assert status["active"]["exists"] is False
    assert status["previous"]["exists"] is True
    assert status["latest_failed_staging"]["label"] == "staging-failed"


def test_publish_status_prefers_active_bundle_when_present(tmp_path, monkeypatch):
    from app import graph_generation_paths, index_registry

    registry_path = tmp_path / "index_registry.json"
    monkeypatch.setattr(index_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(index_registry, "REGISTRY_LOCK_PATH", tmp_path / "index_registry.lock")
    by_generation = tmp_path / "graph_generations" / "by_generation"
    monkeypatch.setattr(graph_generation_paths, "BY_GENERATION_ROOT", by_generation)
    monkeypatch.setattr(graph_generation_paths, "STAGING_ROOT", tmp_path / "graph_generations" / "staging")

    _write_registry(registry_path, active_gid="active-gen", previous_gid="previous-gen")
    _write_bundle(by_generation, "active-gen")
    _write_bundle(by_generation, "previous-gen")

    status = get_graph_publish_status()

    assert status["reader_source"] == "active"
    assert status["reader_generation_id"] == "active-gen"
    assert status["active"]["report"]["gate_passed"] is True
