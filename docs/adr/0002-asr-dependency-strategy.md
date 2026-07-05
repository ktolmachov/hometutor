# ADR 0002: ASR dependency strategy

Date: 2026-07-05

Status: Proposed

## Context

The multimodal konspekt plan needs video transcription, but the runtime core must
stay local-first and small. The project also avoids pulling heavy dependencies
into the default install unless the feature clearly needs them.

The first ASR implementation must produce two artifacts inside `DATA_DIR`:

```text
<lecture>.txt
<lecture>.segments.json
```

The `.txt` artifact is consumed by the existing smart-konspekt path. The
`.segments.json` artifact is used by deterministic section-to-timestamp alignment.

## Decision

Use `faster-whisper` as the first supported ASR backend, behind an optional
`asr` dependency extra and an explicit runtime setting such as `ASR_ENABLED`.

`ffmpeg` remains a system dependency checked by preflight. It should not be
vendored into the repository.

The script entrypoint is:

```text
scripts/transcribe_media.py
```

The script accepts an external input path, imports/copies the media into `DATA_DIR`,
and persists only data-relative paths in metadata.

`whisper.cpp` stays a documented fallback candidate, not part of M1 unless the
CUDA/Python stack proves impractical during the benchmark spike.

Cloud ASR is out of scope for default behavior and may only be added later as
explicit opt-in through config/provider conventions.

## Consequences

Positive:

- no heavy ASR dependency in core installs;
- Python integration is straightforward for tests and script output;
- word/segment timestamps are available for alignment;
- local-first remains the default.

Tradeoffs:

- users need compatible CUDA/runtime packages for GPU speed;
- `ffmpeg` installation remains an operational prerequisite;
- a small benchmark spike is required before promising processing time.

## Required Spike Before M1 Merge

Run on a representative lecture, for example `The_Architecture_of_Autonomy.mp4`,
after importing it into `DATA_DIR`:

- duration, codec and file size;
- ASR wall-clock time;
- rough transcript quality on 5-10 sampled segments;
- timestamp coverage;
- whether CPU fallback is tolerable enough for a warning path.

No exact speed/WER claim should be documented until this spike is recorded.
