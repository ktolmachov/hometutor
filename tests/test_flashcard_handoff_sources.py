from types import SimpleNamespace

import app.flashcard_handoff as handoff


def test_flashcard_handoff_seed_attaches_section_and_video_actions(monkeypatch) -> None:
    section = SimpleNamespace(
        heading_text="Idempotency keys",
        line_start=42,
        konspekt_md_abs="D:/vault/lesson.md",
        source_abs=SimpleNamespace(name="lesson.md"),
    )
    citation = SimpleNamespace(
        url="https://youtu.be/demo?t=83",
        timestamp_label="1:23",
    )

    monkeypatch.setattr(
        "app.section_index.build_section_index",
        lambda source_path: [section],
    )
    monkeypatch.setattr(
        "app.section_index.best_section_for",
        lambda sections, query: section,
    )
    monkeypatch.setattr(
        "app.obsidian_export.obsidian_uri_if_available",
        lambda path, heading_text=None: "obsidian://open",
    )
    monkeypatch.setattr(
        "app.obsidian_export.vscode_uri",
        lambda path, line=None: "vscode://file",
    )
    monkeypatch.setattr(
        "app.living_konspekt_video_citations.video_citation_for_candidate",
        lambda candidate: SimpleNamespace(status="available", citation=citation),
    )
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(
            auth_enabled=True,
            home_rag_api_key="",
            ui_api_base_url="http://127.0.0.1:8000",
        ),
    )

    seed = handoff.build_flashcard_handoff_seed(
        {
            "id": 7,
            "front": "Зачем нужны idempotency keys?",
            "back": "Чтобы повторный вызов инструмента не менял состояние непредсказуемо.",
            "source_path": "ии агенты/lesson.md",
        }
    )

    source = seed["sources"][0]
    assert source["section_heading"] == "Idempotency keys"
    assert source["section_line_start"] == 42
    assert source["obsidian_uri"] == "obsidian://open"
    assert source["vscode_uri"] == "vscode://file"
    assert source["video_url"] == "https://youtu.be/demo?t=83"
    assert source["video_label"] == "🎬 Видео с 1:23"
    assert source["source_actions"] == [
        {
            "kind": "obsidian_section",
            "label": "Открыть раздел «Idempotency keys» в Obsidian",
            "url": "obsidian://open",
        },
        {
            "kind": "vscode_section",
            "label": "Открыть раздел «Idempotency keys» в VS Code",
            "url": "vscode://file",
        },
        {
            "kind": "video",
            "label": "🎬 Видео с 1:23",
            "url": "https://youtu.be/demo?t=83",
        },
    ]


def test_flashcard_handoff_seed_keeps_source_action_without_section_index(monkeypatch, tmp_path) -> None:
    source_abs = tmp_path / "lesson.md"
    source_abs.write_text("# Lesson\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.obsidian_export.resolve_source",
        lambda source_path: source_abs,
    )
    monkeypatch.setattr(
        "app.obsidian_export.vscode_uri",
        lambda path, line=None: "vscode://source",
    )
    monkeypatch.setattr(
        "app.obsidian_export.vault_target",
        lambda source_path: tmp_path / "vault" / "lesson.md",
    )
    monkeypatch.setattr(
        "app.section_index.build_section_index",
        lambda source_path: [],
    )

    seed = handoff.build_flashcard_handoff_seed(
        {
            "id": 8,
            "front": "Почему LLM stateless?",
            "back": "Она не хранит память между запросами без внешнего состояния.",
            "source_path": "ии агенты/lesson.md",
        }
    )

    source = seed["sources"][0]
    assert source["source_vscode_uri"] == "vscode://source"
    assert source["source_actions"] == [
        {
            "kind": "vscode_source",
            "label": "Открыть источник в VS Code",
            "url": "vscode://source",
        }
    ]
    assert source["source_action_note"] == "Раздел конспекта ещё не подготовлен; можно открыть исходный файл."
