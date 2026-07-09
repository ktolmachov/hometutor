import json

from app.knowledge_graph_bundle import write_graph_snapshot_payload
from app.ui.dashboards_graph import _load_staging_preview_graph


def test_load_staging_preview_graph_reads_failed_staging_bundle(tmp_path):
    bundle_dir = tmp_path / "graph_generations" / "staging" / "bundle-a"
    write_graph_snapshot_payload(
        bundle_dir,
        json.dumps(
            {
                "concepts": {
                    "llm": {
                        "label": "LLM",
                        "description": "Large language model",
                    }
                },
                "documents": {},
                "edges": {},
                "typed_relations": [],
            },
            ensure_ascii=False,
        ),
    )
    status = {
        "latest_failed_staging": {
            "label": "bundle-a",
            "bundle_dir": str(bundle_dir),
            "exists": True,
            "report": {"gate_passed": False},
        }
    }

    graph, info = _load_staging_preview_graph(status)

    assert info["label"] == "bundle-a"
    assert "llm" in graph.get_concepts()


def test_load_staging_preview_graph_ignores_missing_bundle_dir():
    graph, info = _load_staging_preview_graph(
        {"latest_failed_staging": {"label": "bundle-a", "exists": True}}
    )

    assert graph is None
    assert info is None
