# ADR 0003: Workbench row contract (persisted vs runtime)

Date: 2026-07-06

Status: Proposed

Implementation status (2026-07-06): not started. This ADR fixes the contract that
W4 of the Living Konspekt plan (`docs/living_konspekt_next_waves_plan.md`, §A2/W4)
must implement before any user data (notes, reading progress) is introduced.

## Context

The Living Konspekt workbench row is a de-facto public contract. A row produced by
`app/section_index.py::section_to_row` survives four transitions unchanged today:

1. persist to `app_kv` (workbench autosave);
2. backup/QR move, because `app_kv` is in the sync whitelist
   (`app/user_state_db.py::_SYNC_TABLE_COLUMNS`);
3. serialization into research-session payloads
   (`app/ui/sidebar.py` stores `workbench_sections` in the payload, restored by
   `apply_research_payload`);
4. restore on a different machine or after a `DATA_DIR` change.

The current v1 row stores absolute local paths:

```text
source_abs, konspekt_md_abs, heading_text, slug, level,
line_start, line_end, text, own_text, concept
```

Because `app_kv` is synced, the row travels to another machine, but its absolute
paths (`D:\AI\app\data\...`) no longer resolve there. Every consumer that reads the
abs paths silently breaks after the move: dedup keys, deep-links, staleness checks,
the media panel and the konspekt memory loop. The data looks "synchronized" while
being unusable. This is the silent-data-loss trap the plan calls out in §A2.

A migration that only swaps one field would fix sync and break the UI: today the UI
reads `konspekt_md_abs`/`source_abs` directly for dedup, deep-links, staleness and
Obsidian/VS Code opening (`app/section_index.py`, `app/ui/living_konspekt_view.py`).
The whole row contract must be versioned, and the persisted and runtime forms must
be separated, so the migration fixes portability without touching consuming code.

## Decision

Introduce row contract **v2** with two explicitly separated models and a single
owner for the persisted form.

### Persisted row v2 (stored in `app_kv` and research-session payloads)

Nothing absolute is written to disk. Paths are stored `DATA_DIR`-relative POSIX,
exactly as `media_sidecar` already does (ADR 0001):

```text
konspekt_md_rel, source_rel, row_version,
heading_text, slug, level, line_start, line_end, text, own_text, concept,
note, read_at
```

- `konspekt_md_rel`, `source_rel` — POSIX paths relative to `DATA_DIR`.
- `row_version` — integer, starts at `2`. Governs all future migrations; after this
  ADR every field addition goes through an ADR revision (plan §8.5).
- `note: str | None`, `read_at: str | None` — reserved optional fields, declared in
  the v2 schema now. They are part of the contract, not a future placeholder:
  populated only in W6, but they must round-trip through the W5 artifact manifest as
  opaque passthrough with no schema bump between W4 and W6.
- `concept` stays `str | None`, as in v1.

### Runtime row (what the UI and other consumers see after hydration)

The workbench service resolves `rel → abs` on hydration and returns the dict in
today's shape so consuming code is unchanged:

```text
konspekt_md_abs, source_abs, heading_text, slug, level,
line_start, line_end, text, own_text, concept, note, read_at
```

`konspekt_md_abs`/`source_abs` are present but **computed**, never stored. Dedup
keys, deep-links, staleness and Obsidian/VS Code opening keep working without
edits in `living_konspekt_view.py` or the external importers.

### Single owner

`app/workbench_service.py` (created in W4) is the only component that reads or
writes the persisted form. UI modules, routers and other consumers receive the
runtime row only. This is the AC that closes the "domain logic in the UI layer"
debt (plan §A1): `dashboards_graph`, `flashcards_review_view`, `mission_control`,
`sidebar` and `main` import the service directly; re-exports in
`living_konspekt_view` are either removed in the same wave or marked
`# TODO(W4-cleanup)` with a test asserting their emptiness/removal.

### Path resolution and the non-portable-snapshot rule

Resolution reuses the existing path-safety layer, keeping one resolution convention
with `media_sidecar`:

- `app/path_safety.py::resolve_data_relative_path` (rel → abs, must stay inside
  `DATA_DIR`);
- `app/path_safety.py::validate_data_relative_path` (canonical POSIX rel);
- `DATA_DIR` from `app/config.py`.

A row whose path falls **outside** the current `DATA_DIR` at resolve time is not a
crash: the service marks it a non-portable snapshot and surfaces a staleness hint.
The snapshot stays readable and collectible; only its deep-link/media resolve
degrade. This mirrors the "stale media links degrade safely" rule from ADR 0001.

### Migration

- **Lazy abs → rel.** Rows saved before v2 that still carry `konspekt_md_abs` /
  `source_abs` are read by the fallback path. On first hydration, if the absolute
  path is inside the current `DATA_DIR`, the row is normalized to the v2 persisted
  form and rewritten. Old abs keys are accepted on read during the migration window
  and never written by new code.
- **Research-session payloads serialize the same rows**, so the same migration and
  the same persisted/runtime split apply to them. The payload version
  (`RESEARCH_PAYLOAD_VERSION`) is bumped together with `row_version`.
- **Out-of-`DATA_DIR` legacy rows** that cannot be normalized become non-portable
  snapshots rather than portable rows; they are not silently rewritten to a wrong
  relative path.

## Consequences

Positive:

- rows survive a machine or `DATA_DIR` move without silent breakage;
- sync stays correct: `app_kv` is already whitelisted, and nothing absolute is
  serialized anymore;
- UI and external importers are unchanged because the runtime row keeps today's
  shape;
- one path-resolution convention is shared with `media_sidecar` (ADR 0001);
- reserved `note`/`read_at` avoid a second schema bump when W6 fills them.

Tradeoffs:

- the service layer becomes mandatory in W4 — the persisted form is hidden behind
  it, and the v1 helpers in `living_konspekt_view` move out of the view;
- every hydration pays a resolve cost (cheap, but it must be cached per document,
  like the existing `sidecar_cache`);
- mixed-version rows coexist until each is hydrated once (lazy migration);
- rows referencing scratch paths outside `DATA_DIR` become non-portable snapshots
  instead of portable data — an intentional trade for correctness.

## Implementation Notes

- Row dict is produced/consumed by `section_to_row` / `row_to_section` in
  `app/section_index.py`; the v2 persisted/runtime split is added there in W4.
- Persistence goes through `app/user_state*` helpers (`app_kv`) and research
  sessions; both are already in the sync whitelist, so no whitelist change is
  needed.
- Path resolution goes through `app/path_safety.py`; `DATA_DIR` comes from
  `app/config.py`. Do not read env or build paths ad hoc.
- Any HTTP surface for the workbench, if added (plan W7), belongs in
  `app/routers/*` and consumes the runtime row only.
- Verification of the migration is recorded in the PR/commit message of the W4
  wave, not as a suite-status claim inside this document (plan §journal).
