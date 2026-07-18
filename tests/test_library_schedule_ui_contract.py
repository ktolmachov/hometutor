"""UI contracts for the Library schedule surface (W8)."""

import base64
from pathlib import Path

from app.library_schedule_read import ScheduleTile
from app.ui.library_schedule import _render_card_grid
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


def test_library_card_grid_keys_include_absolute_tile_index(monkeypatch) -> None:
    class _Column:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _StreamlitStub:
        session_state = {}

        def __init__(self) -> None:
            self.button_keys: list[str] = []

        def markdown(self, *args, **kwargs) -> None:
            return None

        def caption(self, *args, **kwargs) -> None:
            return None

        def columns(self, count: int, **kwargs):
            return [_Column() for _ in range(count)]

        def button(self, *args, key: str, **kwargs) -> bool:
            self.button_keys.append(key)
            return False

        def expander(self, *args, **kwargs):
            return _Column()

    tiles = [
        ScheduleTile(
            kind="transfer",
            title="Shared one",
            address="course · lesson 1",
            status="в 2 курсах",
            quant="2 курса",
            courses=("course-a", "course-b"),
            concept_id="",
            cta="ask",
            meta="transfer",
        ),
        ScheduleTile(
            kind="transfer",
            title="Shared two",
            address="course · lesson 2",
            status="в 2 курсах",
            quant="2 курса",
            courses=("course-a", "course-c"),
            concept_id="",
            cta="ask",
            meta="transfer",
        ),
    ]
    st_stub = _StreamlitStub()
    monkeypatch.setattr("app.ui.library_schedule.st", st_stub)

    _render_card_grid(tiles, key_prefix="lib_tr", show_thumb=True)

    assert "lib_tr_0_transfer_primary" in st_stub.button_keys
    assert "lib_tr_1_transfer_primary" in st_stub.button_keys
    assert len(set(st_stub.button_keys)) == len(st_stub.button_keys)
