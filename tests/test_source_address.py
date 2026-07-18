"""W8 SourceAddress pure helpers."""

from app.ui.source_address import (
    address_aria_label,
    format_source_address,
    join_address_parts,
    library_card_html,
    normalize_source_address,
    source_address_html,
    status_with_icon,
)


def test_join_and_format_address() -> None:
    assert join_address_parts("Курс A", "Урок 1", "", None) == "Курс A · Урок 1"
    assert format_source_address(course="AI", lesson="Intro", section="RAG") == "AI · Intro · RAG"
    assert format_source_address(fallback="only") == "only"


def test_normalize_separators() -> None:
    assert normalize_source_address("a / b | c") == "a · b · c"
    assert normalize_source_address("") == "—"


def test_status_always_has_icon_or_symbol() -> None:
    line = status_with_icon("нужна переиндексация", kind="course")
    assert "переиндекс" in line
    assert line != "нужна переиндексация"  # icon prefix
    assert status_with_icon("🔁 already", kind="route").startswith("🔁")


def test_source_address_html_accessible() -> None:
    html = source_address_html("курс · урок", quant="3 док.")
    assert "src-addr" in html
    assert "aria-label" in html
    assert "курс · урок" in html
    assert address_aria_label("курс · урок").startswith("Адрес")


def test_library_card_html_anatomy_address_before_title() -> None:
    html = library_card_html(
        title="ИИ Агенты",
        address="ai-agents · intro",
        status="12 док.",
        kind="course",
        quant="12",
    )
    assert "lib-card" in html
    addr_i = html.index("src-addr")
    title_i = html.index("lib-card-title")
    status_i = html.index("lib-card-status")
    assert addr_i < title_i < status_i
