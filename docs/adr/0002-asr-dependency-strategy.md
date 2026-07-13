# ADR 0002: ASR dependency strategy

Date: 2026-07-05 (amended 2026-07-06: ffmpeg scope narrowed to remux, import flag
and idempotency fingerprint implemented in `scripts/transcribe_media.py`)

Status: Proposed

Implementation status (2026-07-06): `scripts/transcribe_media.py`,
`scripts/build_media_sidecar.py` and `app/media_alignment.py` exist as offline
maintainer prototypes with unit tests; the benchmark spike below has NOT been
run yet, so M1 is *partially prototyped, not production-ready*. `ASR_ENABLED`
runtime setting is not introduced — the scripts are not called by the app.

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

`ffmpeg` is a system dependency for container remux (`--remux`) and audio track
operations (P0 podcasts: `extract_audio_to_m4a` + A2 basket concat). Both use
`-c copy` / `-vn -c:a copy` / concat (no re-encoding of content). Audio
decoding for ASR itself goes through PyAV bundled with faster-whisper.
ffmpeg must not be vendored into the repository.

The script entrypoint is:

```text
scripts/transcribe_media.py
```

The script accepts an external input path; `--import-to-data <rel-dir>` copies the
media into `DATA_DIR` so metadata can persist only data-relative paths. Running
against a file outside `DATA_DIR` without import prints an explicit warning.
Segment-level timestamps (`{start, end, text}`) are persisted; word-level
timestamps are available in faster-whisper but intentionally not stored in M1.

`whisper.cpp` stays a documented fallback candidate, not part of M1 unless the
CUDA/Python stack proves impractical during the benchmark spike.

Cloud ASR is out of scope for default behavior and may only be added later as
explicit opt-in through config/provider conventions.

## Consequences

Positive:

- no heavy ASR dependency in core installs;
- Python integration is straightforward for tests and script output;
- segment-level timestamps are persisted for alignment (word-level available upstream in faster-whisper, intentionally not stored in M1);
- local-first remains the default.

Tradeoffs:

- users need compatible CUDA/runtime packages for GPU speed;
- `ffmpeg` is operationally required for `--remux`, audio extraction for podcasts
  (A1) and basket release concat (A2); all operations are copy-only;
- a small benchmark spike is required before promising processing time.

## Amendment (2026-07-13, audio podcasts P0)

ffmpeg scope expanded from remux-only to include deterministic audio remux/extract
(`extract_audio_to_m4a`: `-vn -c:a copy`) and basket concat (A2) for the
local-first "Audio Podcasts" feature (waves A1+A2).

- Runtime: `app/media_audio.py` (discovery + `make_basket_audio_release`), 
  `app/ui/living_konspekt_media.py` (`st.audio(..., format="audio/mp4")` + download button).
- Pipeline: `scripts/transcribe_media.py` + `Run-MediaKonspektPipeline.ps1` (always
  after sidecar; `-Skip*` флаги не влияют на extract).
- Нет изменения схемы sidecar v1, нет новых Python-зависимостей, graceful
  деградация (честные подсказки в UI/скриптах).
- См. `user_guide.md` (Живой конспект), `multimodal_konspekt_plan.md`,
  `evolutionary_development.md`.

Тесты: unit-регрессии на str-путь, outside-DATA abs, `end=None` + реальный
PS-пайплайн в CI (`test-media-pipeline-audio`).

## Required Spike Before M1 Merge

Run on a representative lecture, for example `The_Architecture_of_Autonomy.mp4`,
after importing it into `DATA_DIR`:

- duration, codec and file size;
- ASR wall-clock time;
- rough transcript quality on 5-10 sampled segments;
- timestamp coverage;
- whether CPU fallback is tolerable enough for a warning path.

No exact speed/WER claim should be documented until this spike is recorded.
