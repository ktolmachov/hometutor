from app.ui.flashcard_handoff_source_actions import (
    first_flashcard_handoff_source_url,
    flashcard_handoff_source_actions,
)


def test_flashcard_handoff_source_actions_prefers_structured_actions() -> None:
    source = {
        "source_actions": [
            {"label": "Открыть конспект", "url": "obsidian://open"},
            {"label": "", "url": "vscode://file"},
            {"label": "Видео", "url": ""},
        ],
        "vscode_uri": "vscode://legacy",
    }

    assert flashcard_handoff_source_actions(source) == [("Открыть конспект", "obsidian://open")]
    assert first_flashcard_handoff_source_url(source) == "obsidian://open"


def test_flashcard_handoff_source_actions_supports_legacy_fields() -> None:
    source = {
        "section_heading": "State machines",
        "obsidian_uri": "obsidian://section",
        "vscode_uri": "vscode://section",
        "video_url": "https://youtu.be/demo?t=12",
        "video_label": "Видео с 0:12",
    }

    assert flashcard_handoff_source_actions(source) == [
        ("Открыть раздел «State machines» в Obsidian", "obsidian://section"),
        ("Открыть раздел «State machines» в VS Code", "vscode://section"),
        ("Видео с 0:12", "https://youtu.be/demo?t=12"),
    ]
