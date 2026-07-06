from app.ui.cockpit_rotator import DEFAULT_SLOTS, next_slot_index, slot_id_at, slot_label


def test_living_konspekt_slot_is_in_cockpit_rotation() -> None:
    assert DEFAULT_SLOTS[-1] == "living_konspekt"
    assert slot_label("living_konspekt") == "10 минут: пополни конспект недели"
    assert slot_id_at(next_slot_index(len(DEFAULT_SLOTS) - 2)) == "living_konspekt"
