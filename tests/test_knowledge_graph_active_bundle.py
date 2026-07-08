import json
from pathlib import Path

from app import graph_generation_paths, index_registry, knowledge_graph
from app.knowledge_graph_bundle import write_graph_snapshot_payload


def _write_registry(path: Path, *, active_gid: str, previous_gid: str | None) -> None:
    previous = None
    if previous_gid:
        previous = {
            "generation_id": previous_gid,
            "chunks_collection": f"{previous_gid}_chunks",
            "summaries_collection": f"{previous_gid}_summaries",
            "activated_at": "2026-07-08T00:00:00+00:00",
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
                    "activated_at": "2026-07-08T01:00:00+00:00",
                },
                "previous_generation": previous,
                "staging_generation": None,
                "last_failed_generation": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_bundle(root: Path, generation_id: str, concept_id: str) -> None:
    payload = {
        "concepts": {
            concept_id: {
                "label": concept_id,
                "description": "test concept",
            }
        },
        "documents": {},
        "edges": {},
        "typed_relations": [],
    }
    write_graph_snapshot_payload(
        root / generation_id,
        json.dumps(payload, ensure_ascii=False),
    )


def test_active_graph_falls_back_to_previous_promoted_bundle(tmp_path, monkeypatch):
    registry_path = tmp_path / "index_registry.json"
    monkeypatch.setattr(index_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(index_registry, "REGISTRY_LOCK_PATH", tmp_path / "index_registry.lock")
    by_generation = tmp_path / "graph_generations" / "by_generation"
    monkeypatch.setattr(graph_generation_paths, "BY_GENERATION_ROOT", by_generation)
    monkeypatch.setattr(knowledge_graph, "DATA_DIR", tmp_path)

    _write_registry(registry_path, active_gid="active-gen", previous_gid="previous-gen")
    _write_bundle(by_generation, "previous-gen", "previous-concept")
    knowledge_graph.invalidate_knowledge_graph_singleton()

    kg = knowledge_graph.get_active_knowledge_graph()

    assert "previous-concept" in kg.get_concepts()


def test_active_graph_prefers_active_bundle_when_it_exists(tmp_path, monkeypatch):
    registry_path = tmp_path / "index_registry.json"
    monkeypatch.setattr(index_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(index_registry, "REGISTRY_LOCK_PATH", tmp_path / "index_registry.lock")
    by_generation = tmp_path / "graph_generations" / "by_generation"
    monkeypatch.setattr(graph_generation_paths, "BY_GENERATION_ROOT", by_generation)
    monkeypatch.setattr(knowledge_graph, "DATA_DIR", tmp_path)

    _write_registry(registry_path, active_gid="active-gen", previous_gid="previous-gen")
    _write_bundle(by_generation, "previous-gen", "previous-concept")
    _write_bundle(by_generation, "active-gen", "active-concept")
    knowledge_graph.invalidate_knowledge_graph_singleton()

    kg = knowledge_graph.get_active_knowledge_graph()

    assert "active-concept" in kg.get_concepts()
    assert "previous-concept" not in kg.get_concepts()
