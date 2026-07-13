# TTS dependency strategy (Audio Podcasts B2)

**Date:** 2026-07-13
**Status:** accepted (minimal P1)
**Related:** audio_podcasts_plan.md (B2), ADR-0002 (ffmpeg/asr)

## Context
P1 B2 adds optional synthesis of audio files from section text ("text-only" sections without lecture media). Goal: same player surface as A1, file-based only.

## Decision
- Optional extra `[tts]` (modeled after `[asr]`).
- Initial engine: pyttsx3 (already present via voice extra) for `save_to_file` → .wav in temp cache.
- No live `speak()` extension for podcasts path; `tts_text_to_audio_file()` + `st.audio` is the supported form.
- Later candidates (piper, silero) can replace without contract change.
- Graceful: if engine absent, helper returns None + UI shows honest hint. No new storage schema.

## Consequences
- Users: `pip install -e .[tts]` (or [voice]) to enable.
- No impact on P0 audio extraction (ffmpeg remains separate).
- Doc update: user_guide.md + this ADR.

No LLM, no sidecar schema change.
