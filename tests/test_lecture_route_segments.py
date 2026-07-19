"""Tests for lecture route segment grouping (#19 P0-1)."""
from __future__ import annotations

import pytest

from app.ui import living_konspekt_lecture_route as lecture_route
from app.ui.living_konspekt_lecture_route import group_sections_into_segments


def test_empty_sections_returns_empty() -> None:
    assert group_sections_into_segments([]) == []


def test_single_section_becomes_one_segment() -> None:
    sections = [{"t_start": 0.0, "t_end": 600.0, "label": "Intro"}]
    segs = group_sections_into_segments(sections)
    assert len(segs) == 1
    assert segs[0].t_start == 0.0
    assert segs[0].t_end == 600.0
    assert segs[0].duration_min == 10.0


def test_sections_grouped_by_target_duration() -> None:
    sections = [
        {"t_start": 0.0, "t_end": 300.0, "label": "A"},
        {"t_start": 300.0, "t_end": 700.0, "label": "B"},
        {"t_start": 1000.0, "t_end": 1600.0, "label": "C"},
    ]
    segs = group_sections_into_segments(sections, target_min=10.0)
    assert len(segs) == 2
    assert segs[0].t_start == 0.0
    assert segs[0].duration_min >= 10.0
    assert segs[1].t_start == 1000.0


def test_long_section_stays_alone() -> None:
    sections = [{"t_start": 0.0, "t_end": 720.0, "label": "Very long"}]
    segs = group_sections_into_segments(sections, target_min=10.0)
    assert len(segs) == 1
    assert segs[0].duration_min == 12.0


def test_sections_without_timecodes_are_ignored() -> None:
    sections = [
        {"t_start": 0.0, "t_end": 300.0, "label": "Valid"},
        {"label": "No timecode"},
        {"t_start": None, "t_end": None, "label": "Null"},
    ]
    segs = group_sections_into_segments(sections)
    assert len(segs) == 1


def test_out_of_order_sections_sorted_with_gap_separates() -> None:
    sections = [
        {"t_start": 600.0, "t_end": 800.0, "label": "B"},
        {"t_start": 0.0, "t_end": 300.0, "label": "A"},
    ]
    segs = group_sections_into_segments(sections)
    assert len(segs) == 2
    assert segs[0].t_start == 0.0
    assert segs[1].t_start == 600.0


def test_segment_title_uses_first_three_labels() -> None:
    sections = [
        {"t_start": i * 60, "t_end": (i + 1) * 60, "label": f"Section {c}"}
        for i, c in enumerate("ABCD")
    ]
    segs = group_sections_into_segments(sections, target_min=2.5)
    assert len(segs) == 2
    assert "Section A, Section B" in segs[0].title


def test_sections_from_different_media_do_not_share_one_audio_clip() -> None:
    sections = [
        {"t_start": 0.0, "t_end": 300.0, "label": "A", "media_path": "a.md", "audio_path": "a.m4a"},
        {"t_start": 301.0, "t_end": 600.0, "label": "B", "media_path": "b.md", "audio_path": "b.m4a"},
    ]

    segs = group_sections_into_segments(sections, target_min=20.0)

    assert len(segs) == 2
    assert segs[0].audio_path == "a.m4a"
    assert segs[1].audio_path == "b.m4a"
    assert {s["media_path"] for s in segs[0].section_dicts} == {"a.md"}
    assert {s["media_path"] for s in segs[1].section_dicts} == {"b.md"}


def test_gate_results_read_scoped_status_and_clear_all_gate_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "gate_result_0": {"status": "correct"},
        "gate_result_1": {"status": "incorrect"},
        "gate_scoped_0": 2,
        "gate_hint_0": True,
        "gate_completion_metric_emitted": True,
        "gate_next_cta_route": "progress",
    }
    monkeypatch.setattr(lecture_route.st, "session_state", state)

    assert lecture_route._read_gate_results("gate", 2) == {
        "total": 2,
        "correct": 1,
        "answered": 2,
    }

    lecture_route._clear_gate_scoped_state("gate", 2)

    assert "gate_result_0" not in state
    assert "gate_scoped_0" not in state
    assert "gate_hint_0" not in state
    assert "gate_completion_metric_emitted" not in state
    assert "gate_next_cta_route" not in state
