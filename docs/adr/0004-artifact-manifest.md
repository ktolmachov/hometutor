# ADR 0004: Living Konspekt artifact manifest

Date: 2026-07-06

Status: Proposed

Implementation status (2026-07-06): not started. This ADR fixes the W5
"lifecycle" contract from `docs/living_konspekt_next_waves_plan.md`, §A3/W5,
before saved Living Konspekts begin to carry user-authored notes and reading
progress in W6.

## Context

The Living Konspekt workbench now has a v2 row contract (ADR 0003) with a clear
persisted/runtime split. The saved artifact still loses that contract: current
save writes only a readable markdown body, so the file cannot be assembled back
into the workbench, cannot preserve future row metadata (`note`, `read_at`), and
cannot be updated by identity. Re-saving produces filename copies instead of
updating the same logical artifact.

The multimodal media sidecar contract (ADR 0001) is intentionally not enough for
this artifact. A sidecar is anchored to one generated konspekt and one primary
media alignment. A saved Living Konspekt is an aggregate of N documents and M
videos, so it has different invariants and needs a separate owner.

## Decision

Introduce `artifact_manifest_v1`, owned only by `app/konspekt_artifact.py`.

The manifest lives in the YAML frontmatter of the saved `.md` file. The markdown
file is self-contained and round-trippable, while the body stays human-readable:
W5 does not change the deterministic `_stitch_verbatim` body format.

The frontmatter fields are:

```yaml
type: living-konspekt
manifest_version: 1
artifact_id: working-konspekt
title: Рабочий конспект
created_at: "2026-07-06T12:00:00Z"
updated_at: "2026-07-06T12:00:00Z"
goal: null
rows:
  - row_version: 2
    portability_status: portable
    section_id: sha256:...
    row_key: p:courses/lecture.md:10
    konspekt_md_rel: courses/lecture.md
    source_rel: courses/lecture.txt
    heading_text: Тема
    line_start: 10
    line_end: 20
    text: Дословный текст
    note: null
    read_at: null
sidecar_pointers:
  - konspekt_md_rel: courses/lecture.md
    media_sidecar: courses/lecture.media.json
```

`rows` stores the persisted v2 row form returned by
`workbench_service.persisted_rows_from_runtime`, plus artifact-level
`section_id` on each row. `section_id` is not part of the workbench row contract;
it is the manifest snapshot computed from the row content with
`app.media_alignment.compute_section_id` at save time. On reassembly the artifact
owner strips this field before handing rows back to `workbench_service`, after it
has used the field for best-effort re-anchoring. `note` and `read_at` are opaque
passthrough fields: even `null` must survive save -> reassemble -> re-save, and
future W6 values must not require a manifest version bump.

When the source markdown has drifted, reassembly reparses the source and matches
by `section_id`; if a matching section is found, line/text fields are refreshed
from the source. If the source disappeared or no matching section exists, the
row remains a readable non-portable snapshot rather than silently moving notes to
the wrong section.

`goal` is reserved for W6. In v1 it is opaque passthrough data and is not filled
by W5.

`sidecar_pointers` stores only references to the original konspekts'
`media_sidecar:` pointers plus the source konspekt rel path. Section timestamps
are not copied into the artifact manifest; readers resolve them through the
original sidecars when rows are reassembled.

Round-trip contract:

```text
manifest.rows
  -> workbench_service.runtime_rows_from_persisted(...)
  -> Living Konspekt workbench basket
```

`section_id` is carried directly on each manifest row so W6+ can preserve
notes/progress across source drift without changing manifest v1.

Portable and non-portable rows both survive this path because the manifest stores
the already persisted row shape from ADR 0003, including non-portable snapshots.

Artifact identity is `artifact_id`. It is stable after first save; re-saving an
artifact with the same id overwrites the existing file instead of creating
`-1`/`-2` copies. A first save derives the id from the title slug. A reassembled
artifact carries its existing id back in UI state and uses it on the next save.

## Consequences

Positive:

- saved Living Konspekts become machine-readable without losing readable markdown;
- rows can be restored to the workbench through the ADR 0003 service contract;
- `section_id` gives W6 a stable note/progress hook that is less brittle than
  `row_key`'s line-number component;
- W6 can add notes, reading progress, and goals without a manifest bump;
- update-vs-copy is based on stable identity instead of filename probing;
- media timestamps remain sourced from the original sidecars, avoiding duplicate
  timestamp truth in the aggregate artifact.

Tradeoffs:

- saved files now have a structured frontmatter contract that must be validated;
- scanner code must ignore markdown files without `type: living-konspekt`;
- a title change does not imply a new artifact id, which is intentional for
  update semantics.

## Implementation Notes

- `app/konspekt_artifact.py` is the only module that knows the manifest schema
  and the readable artifact body shape.
- YAML parsing reuses the existing markdown frontmatter conventions used by
  `app/ingestion_sections.py`; no new dependency is introduced.
- Path resolution for sidecar pointers goes through `app/path_safety.py`, and the
  UI gets the vault location from `app/obsidian_export.py::vault_root()`.
- The manifest contract is separate from `media_sidecar`; do not reuse the
  sidecar schema for aggregate artifacts.
- The artifact body remains the output of the existing stitching/export path.
