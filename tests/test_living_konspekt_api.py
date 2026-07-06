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


def test_video_citation_redirect_tracks_and_preserves_timestamp(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        "app.event_tracking.track_event",
        lambda name, payload=None, **kwargs: events.append((name, payload or {})),
    )

    response = living_konspekt.open_video_citation(
        "https://www.youtube.com/watch?v=abc123def&t=90s",
        heading="Тема",
        source="lesson.txt",
    )

    assert response.status_code == 307
    assert str(response.headers["location"]).endswith("t=90s")
    assert events == [
        (
            "ask_lecturer_video_citation_clicked",
            {"heading": "Тема", "source": "lesson.txt", "kind": "youtube"},
        )
    ]
