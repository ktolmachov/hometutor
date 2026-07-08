from types import SimpleNamespace

from app.knowledge_graph import _filter_graph_source_scope


def _doc(path: str):
    return SimpleNamespace(text="body", metadata={"relative_path": path, "doc_id": path})


def test_graph_source_scope_filters_technical_documents_and_paths():
    documents = [
        _doc("_test_workbench/fixture.md"),
        _doc("test-fixtures/fixture.md"),
        _doc("graph_generations/staging/kg.sqlite"),
        _doc("ai-agents/lesson-1.md"),
    ]

    filtered_docs, filtered_paths, content_hashes = _filter_graph_source_scope(
        documents,
        source_paths=[
            "_test_workbench/fixture.md",
            "test-fixtures/fixture.md",
            "graph_generations/staging/kg.sqlite",
            "ai-agents/lesson-1.md",
        ],
        source_content_hashes=["hash-real"],
    )

    assert [doc.metadata["relative_path"] for doc in filtered_docs] == ["ai-agents/lesson-1.md"]
    assert filtered_paths == ["ai-agents/lesson-1.md"]
    assert content_hashes == ["hash-real"]
