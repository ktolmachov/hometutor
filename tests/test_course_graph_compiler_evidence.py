from types import SimpleNamespace

from app.course_graph_compiler import compile_course_graph


def _doc(path: str, chunk_id: str):
    return SimpleNamespace(
        text="Task board coordinates deep agents.",
        metadata={
            "doc_id": path,
            "relative_path": path,
            "chunk_id": chunk_id,
            "title": "Deep agents",
        },
    )


def test_relation_with_invalid_chunk_gets_same_doc_chunk_fallback():
    def extract(_doc_id, _rows):
        return (
            {
                "concepts": [
                    {
                        "label": "Task Board",
                        "normalized_label": "Task Board",
                        "source_chunk_id": "chunk-1",
                    },
                    {
                        "label": "Deep Agents",
                        "normalized_label": "Deep Agents",
                        "source_chunk_id": "chunk-1",
                    },
                ],
                "relations": [
                    {
                        "source": "Task Board",
                        "target": "Deep Agents",
                        "type": "part_of",
                        "evidence_doc_id": "course/deep-agents.md",
                        "evidence_chunk_id": "missing-chunk",
                        "confidence": 0.9,
                    }
                ],
            },
            None,
        )

    result = compile_course_graph(
        [_doc("course/deep-agents.md", "chunk-1")],
        generation_id="gen-test",
        scope_hash="scope-test",
        llm_extract_fn=extract,
    )

    relation = next(
        rel
        for rel in result.payload["typed_relations"]
        if rel["source_concept_id"] == "task-board" and rel["target_concept_id"] == "deep-agents"
    )
    assert relation["evidence_doc_id"] == "course/deep-agents.md"
    assert relation["evidence_chunk_id"] == "chunk-1"
