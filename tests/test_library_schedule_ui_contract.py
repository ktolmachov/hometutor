"""UI contracts for the Library schedule surface (W8)."""

import base64
from pathlib import Path

from app.ui.library_schedule import course_thumbnail_data_uri


def _decode_svg(uri: str) -> str:
    prefix = "data:image/svg+xml;base64,"
    assert uri.startswith(prefix)
    return base64.b64decode(uri[len(prefix) :]).decode("utf-8")


def test_course_thumbnail_data_uri_is_local_stable_svg() -> None:
    first = course_thumbnail_data_uri("ИИ Агенты", "ai-agents")
    second = course_thumbnail_data_uri("ИИ Агенты", "ai-agents")

    assert first == second
    svg = _decode_svg(first)
    assert "<svg" in svg
    assert "<text" in svg
    assert "ИА" in svg


def test_course_thumbnail_data_uri_varies_by_course() -> None:
    agents = course_thumbnail_data_uri("ИИ Агенты", "ai-agents")
    physics = course_thumbnail_data_uri("Physics", "physics")

    assert agents != physics


def test_library_schedule_w8_unified_card_and_grid_contract() -> None:
    src = Path("app/ui/library_schedule.py").read_text(encoding="utf-8")
    css = Path("app/ui_theme.css").read_text(encoding="utf-8")

    assert "library_schedule_compact" in src
    assert "Сетка 3→2→1" in src or "3→2→1" in src
    assert "_render_unified_card" in src
    assert "_render_card_grid" in src
    assert "library_card_html" in src
    assert "Подтверждаю смену активного курса" in src
    # No split panel wrapper / old dual card models
    assert 'class="panel lib-schedule"' not in src
    assert "_render_catalog_course_compact_card" not in src
    # Responsive 3→2→1 CSS
    assert "data-lib-grid" in src
    assert "lib-card" in css
    assert "280px" in css
    assert "src-addr" in css
