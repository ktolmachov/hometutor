from app.knowledge_graph_audit import build_graph_audit_report, render_graph_audit_markdown


def test_graph_audit_counts_source_hygiene_evidence_and_duplicates():
    concepts = {
        "ai-agent": {
            "label": "AI Agent",
            "aliases": ["LLM Agent"],
            "related_documents": ["course/lesson.md"],
        },
        "llm-agent": {
            "label": "LLM Agent",
            "aliases": ["AI Agent"],
            "related_documents": ["course/lesson.md"],
        },
        "temperature": {
            "label": "Temperature",
            "related_documents": ["_test_workbench/fixture.md"],
        },
    }
    relations = [
        {
            "source_concept_id": "ai-agent",
            "target_concept_id": "llm-agent",
            "relation_type": "related",
            "evidence_doc_id": "course/lesson.md",
            "evidence_chunk_id": "chunk-1",
        },
        {
            "source_concept_id": "temperature",
            "target_concept_id": "ai-agent",
            "relation_type": "uses",
            "evidence_doc_id": "course/lesson.md",
        },
    ]

    report = build_graph_audit_report(
        concepts=concepts,
        typed_relations=relations,
        compiler_report={
            "gate_passed": False,
            "published": False,
            "metrics": {"concept_count": 3},
            "fail_reasons": ["Не все связи с evidence"],
        },
    )

    assert report["counters"]["test_artifacts"] == 1
    assert report["counters"]["relations_without_evidence"] == 1
    assert report["counters"]["duplicate_candidates"] == 1
    assert report["next_actions"]
    markdown = render_graph_audit_markdown(report)
    assert "Knowledge Graph Audit" in markdown
    assert "test_artifacts" in markdown
    assert "Не все связи с evidence" in markdown
