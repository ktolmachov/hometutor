"""UI contracts for the Library schedule surface."""

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


def test_library_schedule_source_contains_compact_toggle() -> None:
    src = Path("app/ui/library_schedule.py").read_text(encoding="utf-8")

    assert "library_schedule_compact" in src
    assert "Компактные плитки" in src
    assert "_render_catalog_course_compact_card" in src
