from app.routers import living_konspekt


def test_workbench_status_counts_sections_notes_and_read(monkeypatch) -> None:
    monkeypatch.setattr(
        living_konspekt.workbench_service,
        "load_rows",
        lambda: [
            {"note": "мысль", "read_at": "2026-07-06T10:00:00Z"},
            {"note": None, "read_at": None},
        ],
    )

    assert living_konspekt.workbench_status() == {"sections": 2, "with_notes": 1, "read": 1}
