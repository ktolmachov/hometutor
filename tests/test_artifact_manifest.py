from __future__ import annotations

from pathlib import Path

import pytest

from app import artifact_manifest, workbench_service
from app.config import DATA_DIR
from app.section_index import IndexedSection, section_to_row


MD = DATA_DIR / "_test_artifact_manifest" / "lecture.md"
SRC = DATA_DIR / "_test_artifact_manifest" / "lecture.txt"


def _runtime_row(line_start: int = 10, heading: str = "Тема") -> dict:
    section = IndexedSection(
        heading_text=heading,
        slug="tema",
        level=2,
        line_start=line_start,
        line_end=line_start + 3,
        text="Текст раздела.",
        own_text="Текст раздела.",
        source_abs=SRC,
        konspekt_md_abs=MD,
        concept=None,
    )
    return workbench_service.runtime_row_from_persisted(
        workbench_service.persisted_row_from_runtime(section_to_row(section))
    )


def test_serialize_parse_manifest_roundtrip_preserves_rows_and_sidecars() -> None:
    row = _runtime_row()
    persisted = workbench_service.persisted_rows_from_runtime([row])
    manifest_text = artifact_manifest.serialize_manifest(
        "Рабочий конспект",
        persisted,
        [{"konspekt_md_rel": "_test_artifact_manifest/lecture.md", "media_sidecar": "_test_artifact_manifest/lecture.media.json"}],
        artifact_id="working-konspekt",
        created_at="2026-07-06T00:00:00Z",
        updated_at="2026-07-06T00:00:01Z",
    )

    manifest = artifact_manifest.parse_manifest(manifest_text + "# Рабочий конспект\n\nТело")

    assert manifest is not None
    assert manifest.type == "living-konspekt"
    assert manifest.manifest_version == 1
    assert manifest.artifact_id == "working-konspekt"
    assert manifest.rows == persisted
    assert manifest.sidecar_pointers == [
        {
            "konspekt_md_rel": "_test_artifact_manifest/lecture.md",
            "media_sidecar": "_test_artifact_manifest/lecture.media.json",
        }
    ]


def test_parse_manifest_returns_none_for_plain_markdown() -> None:
    assert artifact_manifest.parse_manifest("# Просто markdown") is None


def test_reassemble_rows_uses_workbench_runtime_contract() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row(line_start=42)])
    manifest = artifact_manifest.parse_manifest(
        artifact_manifest.serialize_manifest("T", persisted, [], artifact_id="t")
    )

    rows = artifact_manifest.reassemble_rows(manifest)

    assert rows[0]["row_key"].startswith("p:")
    assert rows[0]["konspekt_md_abs"] == str(MD.resolve())
    assert rows[0]["line_start"] == 42


def test_note_read_at_and_goal_survive_reassemble_and_resave() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row()])
    persisted[0]["note"] = "моя мысль"
    persisted[0]["read_at"] = None
    manifest = artifact_manifest.parse_manifest(
        artifact_manifest.serialize_manifest(
            "T",
            persisted,
            [],
            artifact_id="t",
            goal={"opaque": ["W6"]},
            created_at="2026-07-06T00:00:00Z",
            updated_at="2026-07-06T00:00:01Z",
        )
    )

    reassembled = artifact_manifest.reassemble_rows(manifest)
    resaved = workbench_service.persisted_rows_from_runtime(reassembled)
    text = artifact_manifest.serialize_manifest(
        manifest.title,
        resaved,
        manifest.sidecar_pointers,
        artifact_id=manifest.artifact_id,
        goal=manifest.goal,
        created_at=manifest.created_at,
        updated_at="2026-07-06T00:00:02Z",
    )
    reparsed = artifact_manifest.parse_manifest(text)

    assert reparsed.manifest_version == 1
    assert reparsed.goal == {"opaque": ["W6"]}
    assert reparsed.rows[0]["note"] == "моя мысль"
    assert reparsed.rows[0]["read_at"] is None


def test_non_portable_rows_survive_roundtrip() -> None:
    persisted = [
        {
            "row_version": 2,
            "portability_status": "non_portable",
            "row_key": "np:abc",
            "konspekt_md_label": "outside.md",
            "source_label": "outside.txt",
            "resolve_error": "outside_data_dir",
            "heading_text": "Outside",
            "slug": "outside",
            "level": 2,
            "line_start": 1,
            "line_end": 2,
            "text": "Snapshot text",
            "own_text": "Snapshot text",
            "concept": None,
            "note": None,
            "read_at": None,
        }
    ]
    manifest = artifact_manifest.parse_manifest(
        artifact_manifest.serialize_manifest("Outside", persisted, [], artifact_id="outside")
    )

    rows = artifact_manifest.reassemble_rows(manifest)
    resaved = workbench_service.persisted_rows_from_runtime(rows)

    assert rows[0]["portability_status"] == "non_portable"
    assert rows[0]["konspekt_md_abs"] == ""
    assert resaved == persisted


def test_update_target_uses_existing_artifact_id_without_copy_suffix(tmp_path: Path) -> None:
    target_dir = tmp_path / "living-konspekt"
    target_dir.mkdir()
    existing = target_dir / "old-title.md"
    existing.write_text(
        artifact_manifest.serialize_manifest("Old", [], [], artifact_id="stable-id") + "# Old\n",
        encoding="utf-8",
    )

    assert artifact_manifest.target_path_for_artifact(tmp_path, "New title", "stable-id") == existing
    assert artifact_manifest.target_path_for_artifact(tmp_path, "New title", None) == target_dir / "new-title.md"


def test_scan_saved_artifacts_lists_only_valid_manifests(tmp_path: Path) -> None:
    target_dir = tmp_path / "living-konspekt"
    target_dir.mkdir()
    (target_dir / "valid.md").write_text(
        artifact_manifest.serialize_manifest(
            "Valid",
            workbench_service.persisted_rows_from_runtime([_runtime_row()]),
            [],
            artifact_id="valid",
            updated_at="2026-07-06T00:00:02Z",
        )
        + "# Valid\n",
        encoding="utf-8",
    )
    (target_dir / "plain.md").write_text("# Plain\n", encoding="utf-8")
    (target_dir / "broken.md").write_text(
        "---\ntype: living-konspekt\nmanifest_version: 2\n---\n",
        encoding="utf-8",
    )

    artifacts = artifact_manifest.scan_saved_artifacts(tmp_path)

    assert [(item.name, item.artifact_id, item.title, item.section_count) for item in artifacts] == [
        ("valid.md", "valid", "Valid", 1)
    ]


def test_collect_sidecar_pointers_reads_source_konspekt_frontmatter() -> None:
    MD.parent.mkdir(parents=True, exist_ok=True)
    MD.write_text(
        "---\nmedia_sidecar: _test_artifact_manifest/lecture.media.json\n---\n\n# Lecture\n",
        encoding="utf-8",
    )
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row()])

    assert artifact_manifest.collect_sidecar_pointers(persisted) == [
        {
            "konspekt_md_rel": "_test_artifact_manifest/lecture.md",
            "media_sidecar": "_test_artifact_manifest/lecture.media.json",
        }
    ]


def test_parse_rejects_unsupported_manifest_version() -> None:
    with pytest.raises(ValueError, match="Unsupported artifact manifest version"):
        artifact_manifest.parse_manifest("---\ntype: living-konspekt\nmanifest_version: 2\n---\n")
