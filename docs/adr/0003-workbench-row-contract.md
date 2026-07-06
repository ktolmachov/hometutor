# ADR 0003: Workbench row contract (persisted vs runtime)

Date: 2026-07-06 (amended 2026-07-06: explicit non-portable snapshot persisted
schema; `section_index.py` stays runtime-only; path-safety abs→rel helper;
service auth boundary; research-payload backward-compat rule)

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
exactly as `media_sidecar` already does (ADR 0001). The persisted row carries an
explicit `portability_status`, so a row whose source has left `DATA_DIR` is stored
honestly instead of being rewritten to a wrong relative path.

Portable persisted row (the normal case):

```text
konspekt_md_rel, source_rel, row_version, portability_status,
heading_text, slug, level, line_start, line_end, text, own_text, concept,
note, read_at
```

Non-portable persisted row (snapshot of a source no longer inside `DATA_DIR`):

```text
row_version, portability_status="non_portable",
konspekt_md_label, source_label, resolve_error,
heading_text, slug, level, line_start, line_end, text, own_text, concept,
note, read_at
```

- `konspekt_md_rel`, `source_rel` — POSIX paths relative to `DATA_DIR`. Absent on a
  non-portable row.
- `portability_status` — `"portable"` (default when the key is absent, for
  read-compat during the migration window) or `"non_portable"`.
- `konspekt_md_label`, `source_label`, `resolve_error` — present only on a
  non-portable row. Labels are **display basenames only** (e.g. `lecture_01.md`),
  never absolute paths; `resolve_error` is a short reason (e.g.
  `outside_data_dir`). They preserve diagnosability and the row's content without
  re-introducing an absolute path on disk.
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

For a non-portable row the runtime row keeps the **same keys** (stable shape for
consumers) but `konspekt_md_abs`/`source_abs` are empty strings, and the runtime
row additionally carries `portability_status`, `konspekt_md_label`, `source_label`
and `resolve_error`. Staleness/deep-link code reads `portability_status` to show
the hint and skip resolve instead of touching an empty path.

### Single owner and module boundaries

The persisted form has exactly one owner:

- **`app/workbench_service.py` (created in W4)** is the only component that reads
  or writes the persisted row. It owns the persisted↔runtime conversion
  (`persisted_row_from_runtime` / `runtime_row_from_persisted`), the lazy
  abs→rel migration, and the non-portable-snapshot decision.
- **`app/section_index.py` stays runtime-only.** It keeps `IndexedSection` /
  `ParsedSection` and the *runtime* row (`section_to_row` / `row_to_section`,
  today's abs-keyed shape). It must **not** learn the persisted schema — otherwise
  it becomes a second owner and the "single owner" invariant is broken.
- UI modules, routers and other consumers receive the runtime row only.

This is the AC that closes the "domain logic in the UI layer" debt (plan §A1):
`dashboards_graph`, `flashcards_review_view`, `mission_control`, `sidebar` and
`main` import the service directly; re-exports in `living_konspekt_view` are
either removed in the same wave or marked `# TODO(W4-cleanup)` with a test
asserting their emptiness/removal.

### Service boundary (reusable across UI/API/Telegram/CLI)

The service exists to be reusable outside Streamlit, so it must **not** import
`streamlit` or `app/ui/auth_gate`, and it must not touch `st.session_state`. It
persists only through `app/user_state*` helpers (`get_kv` / `set_kv` under the
workbench key). The **caller** is responsible for establishing the auth/user
context before calling the service — today that is `_ensure_auth_context()` in the
UI; in FastAPI it is the request-scoped dependency, in Telegram the bot handler.
The Streamlit-only `state: MutableMapping` DI parameter of the current view helpers
does not move into the service: persistence is `app_kv`, not session_state.

### Path resolution and the non-portable-snapshot rule

Resolution reuses the existing path-safety layer, keeping one resolution convention
with `media_sidecar`:

- `app/path_safety.py::resolve_data_relative_path` (rel → abs, must stay inside
  `DATA_DIR`);
- `app/path_safety.py::validate_data_relative_path` (canonical POSIX rel);
- `app/path_safety.py::data_relative_from_path` (abs path inside `DATA_DIR` → POSIX
  rel; returns `None` / signals outside-`DATA_DIR` otherwise) — **added in W4**.
  The lazy abs→rel migration needs the reverse direction, which the current API
  lacks (`validate_data_relative_path` rejects absolute input). Adding one helper
  here also consolidates the ad hoc `relative_to(DATA_DIR).as_posix()` already
  scattered across `demo_sandbox.py`, `index_diff.py`, `ingestion_content_state.py`
  and `term_cards.py`, so W4 does not reinvent a fifth copy;
- `DATA_DIR` from `app/config.py`.

A row whose path falls **outside** the current `DATA_DIR` at resolve time is not a
crash: the service marks it `portability_status="non_portable"` and surfaces a
staleness hint. The snapshot stays readable and collectible; only its deep-link/
media resolve degrade. This mirrors the "stale media links degrade safely" rule
from ADR 0001.

### Migration

- **Lazy abs → rel.** Rows saved before v2 that still carry `konspekt_md_abs` /
  `source_abs` are read by the fallback path. On first hydration, if the absolute
  path is inside the current `DATA_DIR`, the row is normalized to the v2 persisted
  form and rewritten. Old abs keys are accepted on read during the migration window
  and never written by new code.
- **Research-session payloads serialize the same rows**, so the same migration and
  the same persisted/runtime split apply to them. The payload version
  (`RESEARCH_PAYLOAD_VERSION`) is bumped together with `row_version`, but
  **backward-compatible**: a v1 payload is still readable. Only `workbench_sections`
  is migrated (each row lazily normalized on hydration exactly like `app_kv` rows);
  every other payload field (`current_view`, `active_topic_id`, `history`,
  `last_answer`, `topic_document_selections`, …) is untouched. The version bump must
  not be used as a hard gate that rejects or wipes older research sessions.
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

- The runtime row is produced/consumed by `section_to_row` / `row_to_section` in
  `app/section_index.py`, unchanged in shape. The persisted↔runtime conversion
  (persisted schema, `row_version`, portability status, lazy abs→rel migration)
  lives in `app/workbench_service.py` — `section_index.py` stays runtime-only.
- Persistence goes through `app/user_state*` helpers (`app_kv`) and research
  sessions; both are already in the sync whitelist, so no whitelist change is
  needed.
- Path resolution goes through `app/path_safety.py`; `DATA_DIR` comes from
  `app/config.py`. Do not read env or build paths ad hoc.
- Any HTTP surface for the workbench, if added (plan W7), belongs in
  `app/routers/*` and consumes the runtime row only.
- Verification of the migration is recorded in the PR/commit message of the W4
  wave, not as a suite-status claim inside this document (plan §journal).
