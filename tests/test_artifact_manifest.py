from __future__ import annotations

from pathlib import Path

import pytest

from app import konspekt_artifact, workbench_service
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


def _write_konspekt(*, line_start: int = 10, heading: str = "Тема", text: str = "Текст раздела.") -> None:
    MD.parent.mkdir(parents=True, exist_ok=True)
    MD.write_text("\n" * (line_start - 1) + f"## {heading}\n\n{text}\n", encoding="utf-8")


def test_serialize_parse_manifest_roundtrip_preserves_rows_and_sidecars() -> None:
    row = _runtime_row()
    persisted = workbench_service.persisted_rows_from_runtime([row])
    manifest_text = konspekt_artifact.serialize_manifest(
        "Рабочий конспект",
        persisted,
        [{"konspekt_md_rel": "_test_artifact_manifest/lecture.md", "media_sidecar": "_test_artifact_manifest/lecture.media.json"}],
        artifact_id="working-konspekt",
        created_at="2026-07-06T00:00:00Z",
        updated_at="2026-07-06T00:00:01Z",
    )

    manifest = konspekt_artifact.parse_manifest(manifest_text + "# Рабочий конспект\n\nТело")

    assert manifest is not None
    assert manifest.type == "living-konspekt"
    assert manifest.manifest_version == 1
    assert manifest.artifact_id == "working-konspekt"
    # Portable rows shed ``text``/``own_text`` from the manifest (slim portable
    # contract): these are re-read from the source on reassemble, so the persisted
    # payload omits them rather than duplicating the lecture content.
    slim_dropped = ("text", "own_text")
    expected = {k: v for k, v in persisted[0].items() if k not in slim_dropped}
    actual = {k: v for k, v in manifest.rows[0].items() if k != "section_id"}
    assert actual == expected
    assert manifest.rows[0]["row_key"] == persisted[0]["row_key"]
    assert manifest.rows[0]["section_id"].startswith("sha256:")
    assert manifest.sidecar_pointers == [
        {
            "konspekt_md_rel": "_test_artifact_manifest/lecture.md",
            "media_sidecar": "_test_artifact_manifest/lecture.media.json",
        }
    ]


def test_parse_manifest_returns_none_for_plain_markdown() -> None:
    assert konspekt_artifact.parse_manifest("# Просто markdown") is None


def test_parse_manifest_requires_section_id_on_rows() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row()])
    text = konspekt_artifact.serialize_manifest("T", persisted, [], artifact_id="t")
    text = text.replace("    section_id:", "    legacy_section_id:", 1).replace(
        "  section_id:",
        "  legacy_section_id:",
        1,
    )

    with pytest.raises(ValueError, match="rows\\[\\]\\.section_id"):
        konspekt_artifact.parse_manifest(text)


def test_reassemble_rows_uses_workbench_runtime_contract() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row(line_start=42)])
    _write_konspekt(line_start=42)
    manifest = konspekt_artifact.parse_manifest(
        konspekt_artifact.serialize_manifest("T", persisted, [], artifact_id="t")
    )

    rows = konspekt_artifact.reassemble_rows(manifest)

    assert rows[0]["row_key"].startswith("p:")
    assert rows[0]["konspekt_md_abs"] == str(MD.resolve())
    assert rows[0]["line_start"] == 42


def test_reassemble_rows_reanchors_by_section_id_when_line_start_drifted() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row(line_start=10)])
    manifest = konspekt_artifact.parse_manifest(
        konspekt_artifact.serialize_manifest("T", persisted, [], artifact_id="t")
    )
    _write_konspekt(line_start=15)

    rows = konspekt_artifact.reassemble_rows(manifest)

    assert rows[0]["line_start"] == 15
    assert rows[0]["row_key"].endswith(":15")
    assert rows[0]["text"] == "Текст раздела."


def test_reassemble_rows_falls_back_to_non_portable_snapshot_when_source_missing() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row(line_start=10)])
    manifest = konspekt_artifact.parse_manifest(
        konspekt_artifact.serialize_manifest("T", persisted, [], artifact_id="t")
    )
    if MD.exists():
        MD.unlink()

    rows = konspekt_artifact.reassemble_rows(manifest)

    assert rows[0]["portability_status"] == "non_portable"
    assert rows[0]["konspekt_md_abs"] == ""
    # Portable rows carry no text in the manifest (slim portable contract); when the
    # source is missing at reassemble the non-portable snapshot cannot recover it.
    assert rows[0]["text"] == ""


def test_note_read_at_and_goal_survive_reassemble_and_resave() -> None:
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row()])
    persisted[0]["note"] = "моя мысль"
    persisted[0]["read_at"] = None
    _write_konspekt()
    manifest = konspekt_artifact.parse_manifest(
        konspekt_artifact.serialize_manifest(
            "T",
            persisted,
            [],
            artifact_id="t",
            goal={"opaque": ["W6"]},
            created_at="2026-07-06T00:00:00Z",
            updated_at="2026-07-06T00:00:01Z",
        )
    )

    reassembled = konspekt_artifact.reassemble_rows(manifest)
    resaved = workbench_service.persisted_rows_from_runtime(reassembled)
    text = konspekt_artifact.serialize_manifest(
        manifest.title,
        resaved,
        manifest.sidecar_pointers,
        artifact_id=manifest.artifact_id,
        goal=manifest.goal,
        created_at=manifest.created_at,
        updated_at="2026-07-06T00:00:02Z",
    )
    reparsed = konspekt_artifact.parse_manifest(text)

    assert reparsed.manifest_version == 1
    assert reparsed.goal == {"opaque": ["W6"]}
    assert reparsed.rows[0]["note"] == "моя мысль"
    assert reparsed.rows[0]["read_at"] is None


def test_artifact_body_includes_user_note_block() -> None:
    row = _runtime_row()
    row["note"] = "моя мысль"

    body = konspekt_artifact.build_artifact_body([row])

    assert "### 💬 Моими словами" in body
    assert "моя мысль" in body


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
    manifest = konspekt_artifact.parse_manifest(
        konspekt_artifact.serialize_manifest("Outside", persisted, [], artifact_id="outside")
    )

    rows = konspekt_artifact.reassemble_rows(manifest)
    resaved = workbench_service.persisted_rows_from_runtime(rows)

    assert rows[0]["portability_status"] == "non_portable"
    assert rows[0]["konspekt_md_abs"] == ""
    assert resaved == persisted


def test_update_target_uses_existing_artifact_id_without_copy_suffix(tmp_path: Path) -> None:
    target_dir = tmp_path / "living-konspekt"
    target_dir.mkdir()
    existing = target_dir / "old-title.md"
    existing.write_text(
        konspekt_artifact.serialize_manifest("Old", [], [], artifact_id="stable-id") + "# Old\n",
        encoding="utf-8",
    )

    assert konspekt_artifact.target_path_for_artifact(tmp_path, "New title", "stable-id") == existing
    assert konspekt_artifact.target_path_for_artifact(tmp_path, "New title", None) == target_dir / "new-title.md"


def test_scan_saved_artifacts_lists_only_valid_manifests(tmp_path: Path) -> None:
    target_dir = tmp_path / "living-konspekt"
    target_dir.mkdir()
    (target_dir / "valid.md").write_text(
        konspekt_artifact.serialize_manifest(
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

    artifacts = konspekt_artifact.scan_saved_artifacts(tmp_path)

    by_name = {item.name: item for item in artifacts}
    assert (by_name["valid.md"].artifact_id, by_name["valid.md"].title, by_name["valid.md"].section_count) == (
        "valid",
        "Valid",
        1,
    )
    assert by_name["plain.md"].has_manifest is False
    assert "broken.md" not in by_name


def test_collect_sidecar_pointers_reads_source_konspekt_frontmatter() -> None:
    MD.parent.mkdir(parents=True, exist_ok=True)
    MD.write_text(
        "---\nmedia_sidecar: _test_artifact_manifest/lecture.media.json\n---\n\n# Lecture\n",
        encoding="utf-8",
    )
    persisted = workbench_service.persisted_rows_from_runtime([_runtime_row()])

    assert konspekt_artifact.collect_sidecar_pointers(persisted) == [
        {
            "konspekt_md_rel": "_test_artifact_manifest/lecture.md",
            "media_sidecar": "_test_artifact_manifest/lecture.media.json",
        }
    ]


def test_parse_rejects_unsupported_manifest_version() -> None:
    with pytest.raises(ValueError, match="Unsupported artifact manifest version"):
        konspekt_artifact.parse_manifest("---\ntype: living-konspekt\nmanifest_version: 2\n---\n")


def test_delete_saved_artifact_removes_file_under_living_konspekt(tmp_path: Path) -> None:
    target_dir = tmp_path / "living-konspekt"
    target_dir.mkdir()
    artifact_path = target_dir / "to-delete.md"
    artifact_path.write_text("# Delete me\n", encoding="utf-8")

    konspekt_artifact.delete_saved_artifact(artifact_path, tmp_path)

    assert not artifact_path.exists()


def test_delete_saved_artifact_rejects_path_outside_living_konspekt(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the living-konspekt directory"):
        konspekt_artifact.delete_saved_artifact(outside, tmp_path)
