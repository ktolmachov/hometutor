from app.prompts import (
    DESIGN_REVIEW_PROMPT,
    get_prompt,
    get_prompt_version,
)


def _render_prompt() -> str:
    return DESIGN_REVIEW_PROMPT.format(
        product_name="Example Product",
        product_context="Учебный продукт для самостоятельного обучения.",
        priority_area="Knowledge Map",
        product_areas="Home, Knowledge Map, Reader, Quiz, Library",
        required_materials="vision.md, references/*.html, app/ui/*",
        reference_standards="Apple HIG, WCAG 2.2, Linear, Figma",
        viewports="1366×768, 1920×1080, 390×844",
        constraints="local-first; все visual signals основаны на данных",
        output_language="русский",
    )


def test_design_review_prompt_is_registered_and_versioned() -> None:
    assert get_prompt("design_review") is DESIGN_REVIEW_PROMPT
    assert get_prompt_version("design_review") == "1.0"


def test_design_review_prompt_renders_required_review_contract() -> None:
    rendered = _render_prompt()

    assert "Example Product" in rendered
    assert "Knowledge Map" in rendered
    assert "WCAG 2.2 AA" in rendered
    assert "P0" in rendered
    assert "P1" in rendered
    assert "P2" in rendered
    assert "файл:строка" in rendered
    assert "Definition of Done" in rendered
    assert "План реализации" in rendered


def test_design_review_prompt_has_no_unresolved_variables_after_render() -> None:
    rendered = _render_prompt()

    for variable in (
        "product_name",
        "product_context",
        "priority_area",
        "product_areas",
        "required_materials",
        "reference_standards",
        "viewports",
        "constraints",
        "output_language",
    ):
        assert "{" + variable + "}" not in rendered
