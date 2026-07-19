"""Tests for lecture route segment grouping (#19 P0-1)."""
from __future__ import annotations

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


def test_out_of_order_sections_are_sorted() -> None:
    sections = [
        {"t_start": 600.0, "t_end": 800.0, "label": "B"},
        {"t_start": 0.0, "t_end": 300.0, "label": "A"},
    ]
    segs = group_sections_into_segments(sections)
    assert len(segs) == 1
    assert segs[0].t_start == 0.0


def test_segment_title_uses_first_three_labels() -> None:
    sections = [
        {"t_start": i * 60, "t_end": (i + 1) * 60, "label": f"Section {c}"}
        for i, c in enumerate("ABCD")
    ]
    segs = group_sections_into_segments(sections, target_min=2.5)
    assert len(segs) == 2
    assert "Section A, Section B" in segs[0].title
