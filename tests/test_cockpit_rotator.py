from app.ui.cockpit_rotator import (
    DEFAULT_SLOTS,
    living_konspekt_slot_hint,
    next_slot_index,
    render_rotator_panel,
    slot_hint,
    slot_id_at,
    slot_label,
)


def test_living_konspekt_slot_is_in_cockpit_rotation() -> None:
    assert DEFAULT_SLOTS[-1] == "living_konspekt"
    assert slot_label("living_konspekt") == "10 минут: пополни конспект недели"
    assert slot_id_at(next_slot_index(len(DEFAULT_SLOTS) - 2)) == "living_konspekt"


def test_living_konspekt_slot_hint_tracks_next_unfinished_step() -> None:
    assert living_konspekt_slot_hint(0) == "10 минут: добавь первый раздел в Живой конспект"
    assert living_konspekt_slot_hint(2) == "10 минут: задай цель конспекта"
    assert living_konspekt_slot_hint(2, has_goal=True) == "10 минут: собери и сохрани текущую сборку"
    assert (
        living_konspekt_slot_hint(2, has_goal=True, has_saved_artifact=True)
        == "10 минут: закрепи сборку коротким quiz"
    )
    assert (
        slot_hint(
            "living_konspekt",
            rows_count=2,
            has_goal=True,
            has_saved_artifact=True,
            has_scoped_quiz=True,
        )
        == "10 минут: пополни конспект недели"
    )


def test_rotator_panel_allows_multiple_render_surfaces(monkeypatch) -> None:
    class _Column:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _StreamlitStub:
        session_state = {}

        def __init__(self) -> None:
            self.button_keys: list[str] = []

        def caption(self, *args, **kwargs) -> None:
            return None

        def columns(self, count: int):
            return [_Column() for _ in range(count)]

        def button(self, *args, key: str, **kwargs) -> bool:
            self.button_keys.append(key)
            return False

    st_stub = _StreamlitStub()
    monkeypatch.setattr("app.ui.cockpit_rotator.st", st_stub)

    render_rotator_panel()
    render_rotator_panel(key_prefix="sidebar_cockpit_rotator")

    assert st_stub.button_keys == [
        "cockpit_rotator_prev",
        "cockpit_rotator_next",
        "sidebar_cockpit_rotator_prev",
        "sidebar_cockpit_rotator_next",
    ]
    assert len(set(st_stub.button_keys)) == len(st_stub.button_keys)
