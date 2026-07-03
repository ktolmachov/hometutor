from types import SimpleNamespace

from app.ui.first_run import should_show_empty_index_hero
from app.ui.preflight import preflight_rows
from app.ui.seed_questions import build_seed_questions


def test_empty_index_hero_condition() -> None:
    assert should_show_empty_index_hero(None) is False
    assert should_show_empty_index_hero({"status": "ok", "documents_count": 5}) is False
    assert should_show_empty_index_hero({"status": "empty"}) is True
    assert should_show_empty_index_hero({"status": "ok", "documents_count": 0}) is True


def test_preflight_rows_payload_none() -> None:
    rows = preflight_rows(None)

    assert rows == [("API", "❌", "API недоступен — запустите main.py (см. quickstart.md).")]


def test_preflight_rows_status_matrix(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ui.preflight.get_settings",
        lambda: SimpleNamespace(llm_model="local-model", llm_api_base="http://127.0.0.1:1234/v1"),
    )
    for index_status in ["ok", "empty", "missing", "error"]:
        for llm_status in ["ok", "timeout", "error"]:
            rows = preflight_rows(
                {
                    "status": "ok" if index_status == "ok" and llm_status == "ok" else "degraded",
                    "components": {
                        "index": {
                            "status": index_status,
                            "documents_count": 2,
                            "error": "Traceback\nsecret stack",
                        },
                        "llm": {"status": llm_status, "latency_ms": 12},
                        "api": {"status": "ok"},
                    },
                }
            )
            text = " ".join(row[2] for row in rows)
            assert "Traceback" not in text
            if llm_status != "ok":
                assert "local-model" in text


def test_build_seed_questions_priority_artifact_topics_files() -> None:
    index_stats = {"status": "ok", "documents_count": 3, "files": ["docs\\пример.md"]}
    artifact = {
        "seed_questions": [
            {"q": "Артефакт 1?", "retrieval_trace": {"source_paths": ["course/a.md"]}},
            {"q": "Артефакт 2?", "retrieval_trace": {"source_paths": ["course/b.md"]}},
            {"q": "Артефакт 3?", "retrieval_trace": {"source_paths": ["course/c.md"]}},
            {"q": "Артефакт 4?"},
        ]
    }
    topics = {"topics": [{"topic_name": "RAG"}]}

    questions = build_seed_questions(index_stats, topics, artifact)

    assert [item["q"] for item in questions] == ["Артефакт 1?", "Артефакт 2?", "Артефакт 3?"]
    assert len(questions) == 3


def test_build_seed_questions_topics_then_files_and_empty_index() -> None:
    assert build_seed_questions({"status": "ok", "documents_count": 0, "files": []}, {}, {}) == []

    topic_questions = build_seed_questions(
        {"status": "ok", "documents_count": 2},
        {"topics": [{"topic_name": "RAG"}, {"topic_name": "BM25"}, {"topic_name": "SRS"}]},
        {},
    )
    assert topic_questions[0]["q"] == "Что такое RAG — коротко и с источниками?"
    assert topic_questions[1]["q"] == "С чего начать изучение темы «BM25»?"

    file_questions = build_seed_questions(
        {"status": "ok", "documents_count": 2, "files": ["папка\\лекция.md", "docs/second.txt"]},
        {},
        {},
    )
    assert file_questions[0] == {"q": "О чём файл лекция.md?", "source_label": "лекция.md"}
