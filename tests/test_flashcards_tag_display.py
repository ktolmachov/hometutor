"""Learner-facing tag presentation for the flashcard review face."""

from app.flashcards_tag_display import (
    escape_multiline,
    render_card_tags_html,
    source_display,
    split_card_tags,
)

# The exact tag string shown raw on the card face in the reported screenshot.
SCREENSHOT_TAGS = (
    "llm, stateless, архитектура, course:bf00fdd2145b, folder:ии агенты, "
    "source:ии агенты/урок_3_автономность_память_стейт_и_контроль_поведения.md"
)


def test_split_separates_human_from_system_tags() -> None:
    human, system = split_card_tags(SCREENSHOT_TAGS)
    assert human == ["llm", "stateless", "архитектура"]
    assert system == [
        "course:bf00fdd2145b",
        "folder:ии агенты",
        "source:ии агенты/урок_3_автономность_память_стейт_и_контроль_поведения.md",
    ]


def test_split_dedupes_case_insensitively_and_keeps_order() -> None:
    human, system = split_card_tags("LLM, llm,  stateless , LLM")
    assert human == ["LLM", "stateless"]
    assert system == []


def test_split_handles_empty_and_none() -> None:
    assert split_card_tags(None) == ([], [])
    assert split_card_tags("   ,, ") == ([], [])


def test_source_display_strips_path_to_filename() -> None:
    _, system = split_card_tags(SCREENSHOT_TAGS)
    assert source_display(system) == ("📄", "урок_3_автономность_память_стейт_и_контроль_поведения.md")
    assert source_display(["source:plain.md"]) == ("📄", "plain.md")
    assert source_display(["source:C:\\notes\\deck.md"]) == ("📄", "deck.md")
    assert source_display(["course:x"]) is None
    assert source_display(["source:"]) is None


def test_source_display_handles_pseudo_sources() -> None:
    # Quiz-derived cards carry source:scoped-quiz — not a file, show a label.
    assert source_display(["source:scoped-quiz"]) == ("🧩", "Из Quiz")
    # e2e fixture pseudo-source is internal and hidden entirely.
    assert source_display(["source:e2e-offline"]) is None
    # An opaque non-file token must not masquerade as a file.
    assert source_display(["source:opaque-token"]) is None


def test_render_scoped_quiz_card_shows_quiz_label_not_file() -> None:
    out = render_card_tags_html("llm, source:scoped-quiz")
    assert ">llm<" in out
    assert "Из Quiz" in out
    assert "📄" not in out
    assert "scoped-quiz" not in out


def test_render_shows_human_chips_and_source_but_not_scope_ids() -> None:
    out = render_card_tags_html(SCREENSHOT_TAGS)
    assert 'class="fc-tag-chip"' in out
    assert ">llm<" in out and ">архитектура<" in out
    # Internal scope identifiers must never reach the learner-facing markup.
    assert "course:" not in out
    assert "folder:" not in out
    assert "bf00fdd2145b" not in out
    # The readable filename is surfaced instead of the raw source: tag.
    assert "урок_3_автономность_память_стейт_и_контроль_поведения.md" in out
    assert "source:" not in out


def test_render_empty_when_no_displayable_tags() -> None:
    assert render_card_tags_html("") == ""
    assert render_card_tags_html("course:abc, folder:x") == ""


def test_render_escapes_tag_html() -> None:
    out = render_card_tags_html("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_escape_multiline_escapes_and_breaks_lines() -> None:
    assert escape_multiline("a < b") == "a &lt; b"
    assert escape_multiline("Правильный ответ: X\n\nПояснение") == (
        "Правильный ответ: X<br><br>Пояснение"
    )
    assert escape_multiline("one\r\ntwo") == "one<br>two"
    assert escape_multiline(None) == ""
