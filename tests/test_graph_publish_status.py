import json
from pathlib import Path

from app.graph_publish_status import _compact_report, get_graph_publish_status, graph_freshness_gap


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


def test_compact_report_dedupes_fail_reasons() -> None:
    report = _compact_report(
        {
            "gate_passed": False,
            "fail_reasons": ["Конфликт alias: LLM vs LLM", "Конфликт alias: LLM vs LLM", "  "],
        }
    )

    assert report["fail_reasons"] == ["Конфликт alias: LLM vs LLM"]


def test_compact_report_preserves_source_paths_count() -> None:
    # A1 DoD: _compact_report must not drop source_paths (used by graph_freshness_gap).
    assert _compact_report({"source_paths": ["demo/a.md", "demo/b.md"], "published": True})["source_paths_count"] == 2
    assert _compact_report({})["source_paths_count"] == 0
    assert _compact_report({"source_paths": "not-a-list"})["source_paths_count"] == 0


def test_graph_freshness_gap_counts_index_minus_active_graph() -> None:
    # 3 indexed materials, graph built from 2 → gap 1 (map lags by one).
    index_stats = {"files": ["demo/a.md", "demo/b.md", "demo/c.md"]}
    publish_status = {"active": {"report": {"source_paths_count": 2}}}
    assert graph_freshness_gap(index_stats, publish_status) == 1


def test_graph_freshness_gap_zero_when_fresh_or_no_index() -> None:
    fresh = {"active": {"report": {"source_paths_count": 3}}}
    assert graph_freshness_gap({"files": ["a.md", "b.md", "c.md"]}, fresh) == 0
    # No indexed materials → nothing to lag behind.
    assert graph_freshness_gap({"files": []}, fresh) == 0
    assert graph_freshness_gap(None, fresh) == 0
    # Promote skipped: active bundle has no report → whole index looks "not on the map".
    assert graph_freshness_gap({"files": ["a.md", "b.md"]}, {"active": {"report": None}}) == 2
