# ADR 0001: Multimodal media metadata contract

Date: 2026-07-05

Status: Accepted

## Context

hometutor needs to attach videos, timestamps, slides and future image captions to
generated konspekts without breaking the current markdown/frontmatter flow. The
runtime repository is local-first, uses `DATA_DIR` as the content boundary, routes
LLM calls through the provider layer, and stores user state through `user_state*`
helpers.

The first multimodal version must avoid three traps:

- persisting absolute local paths such as `C:\Users\...\lecture.mp4`;
- treating section slugs as stable identifiers;
- adding a second multimodal index before captions-as-text is exhausted.
- reopening the primary text LLM choice while implementing media plumbing.

## Decision

Use a versioned sidecar file for multimodal metadata:

```text
<konspekt>.media.json
```

The runtime sidecar lives next to the runtime konspekt inside `DATA_DIR`. The
konspekt frontmatter stores only a data-relative pointer:

```yaml
media_sidecar: courses/autonomy/lecture_01/The_Architecture_of_Autonomy.media.json
```

The sidecar, not the frontmatter, is the source of truth for video source,
section timestamps and image assets.

The sidecar follows `docs/schemas/media_sidecar_v1.schema.json`.

Persisted local media paths must be relative to `DATA_DIR`. Absolute paths may be
accepted only as import input and must be converted into a controlled data-relative
path before they are stored. URL media sources are stored as URL entries and must
be normalized before timestamp links are built.

Sections are keyed by a stable `section_id`; `section_slug` is only a UI/deep-link
helper. The sidecar stores hashes and generation metadata so stale timestamps can
be detected after the konspekt, media file, ASR model or alignment algorithm changes.

Vision captions, when added, should first be indexed as text through the existing
BM25/vector retrieval path. A separate multimodal embedding index is out of scope
until there is evidence that captions-as-text is insufficient.

The existing local text LLM policy stays in force. Textual multimodal work such
as section enrichment, video-segment questions, tutor review and SSR explanations
uses the configured primary text model, currently `qwopus3.6-35b-a3b-v1-mtp`,
through the provider layer. ASR and VLM are specialized roles and do not replace
the primary text LLM.

## Consequences

Positive:

- current markdown parsing remains compatible;
- stale media links can degrade safely instead of silently lying;
- local file privacy follows the existing `DATA_DIR` boundary;
- future ASR/VLM work has a concrete contract to target.

Tradeoffs:

- readers must load one extra sidecar file;
- sidecar invalidation needs tests;
- a future export/import feature must decide whether to include heavy media assets,
  metadata only, or both.

## Implementation Notes

- Path resolution must use the existing path-safety layer.
- M0a uses lightweight internal validation in `app/media_sidecar.py`; the JSON
  Schema remains the public contract and sanity-check artifact until the project
  has a separate reason to add a schema-validator dependency.
- Runtime settings belong in `app/config.py`.
- VLM calls, if added, must go through `app/provider.py`.
- Text LLM calls should keep using the configured `LLM_MODEL`/role model; do not
  create a new text-model path for multimodality.
- Any `media_progress` persistence must use `app/user_state*` helpers and sync
  whitelists.
- HTTP endpoints, if needed, belong in `app/routers/*`, not directly in `app/api.py`.
