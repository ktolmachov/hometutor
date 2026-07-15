"""Tests for wave-material-passport B1/B2 (course quality passport)."""

from __future__ import annotations

import json
from pathlib import Path

from app.course_quality_passport import (
    build_course_quality_passport,
    format_min_documents_ladder,
    rewrite_fail_reasons_for_learners,
)


def _sha(n: str = "a") -> str:
    return (n * 64)[:64]


def _valid_media_sidecar(*, video_url: str = "https://example.com/lesson.mp4") -> dict:
    return {
        "schema_version": 1,
        "konspekt_sha256": _sha("c"),
        "generated_by": {"tool": "test", "created_at": "2026-07-15T00:00:00Z"},
        "media": {"video": {"kind": "url", "url": video_url}},
        "sections": [],
    }


def test_format_min_documents_ladder_with_doc_count() -> None:
    report = {
        "fail_reasons": ["Недостаточно документов для семантического графа"],
        "metrics": {"doc_count": 1},
        "gates": [{"name": "min_documents", "required": ">= 3", "actual": "1", "passed": False}],
    }
    text = format_min_documents_ladder(report)
    assert text is not None
    assert "ещё 2" in text
    assert "1 из 3" in text


def test_format_min_documents_ladder_skips_when_other_blockers() -> None:
    report = {
        "fail_reasons": [
            "Недостаточно документов для семантического графа",
            "Мало нормализованных концептов",
        ],
        "metrics": {"doc_count": 2},
    }
    assert format_min_documents_ladder(report) is None


def test_format_min_documents_ladder_gates_fallback_ignores_non_dict() -> None:
    """M2: gates may be malformed; only dict entries with name/actual are read."""
    report = {
        "fail_reasons": ["Недостаточно документов для семантического графа"],
        "metrics": {},
        "gates": [
            "not-a-dict",
            None,
            {"name": "other", "actual": "9"},
            {"name": "min_documents", "actual": "1"},
        ],
    }
    text = format_min_documents_ladder(report)
    assert text is not None
    assert "ещё 2" in text
    assert "1 из 3" in text


def test_rewrite_fail_reasons_replaces_min_documents() -> None:
    report = {
        "fail_reasons": ["Недостаточно документов для семантического графа"],
        "metrics": {"doc_count": 2},
    }
    out = rewrite_fail_reasons_for_learners(report)
    assert len(out) == 1
    assert "Добавьте ещё 1" in out[0]


def test_build_passport_aggregates_lines(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    course = data / "demo"
    course.mkdir(parents=True)
    (course / "a.md").write_text("# A\n", encoding="utf-8")
    (course / "b.md").write_text("# B\n", encoding="utf-8")
    # Canonical media contract: frontmatter pointer → differently named sidecar file.
    (course / "a.konspekt.md").write_text(
        "---\n"
        "type: konspekt\n"
        "source: a.md\n"
        "media_sidecar: demo/media/renamed_a.media.json\n"
        "---\n"
        "# K\n",
        encoding="utf-8",
    )
    media_dir = course / "media"
    media_dir.mkdir()
    (media_dir / "renamed_a.media.json").write_text(
        json.dumps(_valid_media_sidecar()),
        encoding="utf-8",
    )
    # Orphan sidecar next to konspekt without pointer must NOT count (M1).
    (course / "a.konspekt.media.json").write_text("{}", encoding="utf-8")
    (course / "b.konspekt.media.json").write_text(
        json.dumps(_valid_media_sidecar()),
        encoding="utf-8",
    )

    import app.konspekt_discovery as kd
    import app.path_safety as path_safety

    monkeypatch.setattr(kd, "DATA_DIR", data)
    monkeypatch.setattr(path_safety, "DATA_DIR", data)

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "graph_audit_report.json").write_text(
        json.dumps(
            {
                "counters": {"duplicate_candidates": 2},
                "findings": [
                    {
                        "kind": "duplicate_candidates",
                        "items": [{"a": "1"}, {"b": "2"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    publish_status = {
        "reader_source": "active",
        "reader_generation_id": "gen-1",
        "active": {
            "generation_id": "gen-1",
            "exists": True,
            "bundle_dir": str(bundle),
            "report": {
                "published": True,
                "gate_passed": True,
                "source_paths": ["demo/a.md", "demo/b.md"],
                "source_paths_count": 2,
            },
        },
        "latest_failed_staging": None,
    }
    # M3: graph_freshness_gap reads index_stats["files"], not "documents".
    index_stats = {"files": ["demo/a.md", "demo/b.md", "demo/c.md"]}

    passport = build_course_quality_passport(
        ["demo/a.md", "demo/b.md"],
        publish_status=publish_status,
        index_stats=index_stats,
        data_dir=data,
        fetch_live=False,
    )
    lines = "\n".join(passport["lines"])
    assert "Карта" in lines
    assert "отстаёт на 1" in lines  # c.md on index, not on graph
    assert passport["graph"]["freshness_gap"] == 1
    assert "Конспекты: 1/2" in lines
    # Only a has pointer → loadable sidecar; orphan b.konspekt.media.json ignored.
    assert "Медиа: 1/2" in lines
    assert passport["media"]["with_media"] == 1
    assert "Аудит" in lines
    assert passport["audit"]["duplicate_count"] == 2
    assert passport["konspekts"]["covered"] == 1


def test_build_passport_ladder_when_unpublished_min_docs() -> None:
    publish_status = {
        "reader_source": "legacy",
        "active": {
            "generation_id": "gen-x",
            "exists": False,
            "bundle_dir": "",
            "report": None,
        },
        "latest_failed_staging": {
            "label": "staging-1",
            "report": {
                "fail_reasons": ["Недостаточно документов для семантического графа"],
                "metrics": {"doc_count": 1},
            },
        },
    }
    passport = build_course_quality_passport(
        ["demo/a.md"],
        publish_status=publish_status,
        index_stats={"files": ["demo/a.md"]},
        data_dir=None,
        fetch_live=False,
    )
    assert any("Добавьте ещё" in line for line in passport["lines"])
