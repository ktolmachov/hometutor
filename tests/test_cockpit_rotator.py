from app.ui.cockpit_rotator import (
    DEFAULT_SLOTS,
    living_konspekt_slot_hint,
    next_slot_index,
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
