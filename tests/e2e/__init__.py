"""W10.F1 live Streamlit e2e harness.

External-stack smoke against a running local stack
(``scripts/run_local_stack.ps1`` → backend :8000 + Streamlit :8501).
This package does **not** spawn its own stack in the first wave; see
``tests/e2e/README.md`` for the roadmap and how to extend to a spawned mode.

What this harness closes (W10.F1, 2026-07-18):
  - Mission Control cold-state live smoke on the release viewport matrix
    (1366×768, 1920×1080, 390×844): HTTP 200, no Streamlit exception,
    Mission Control DOM markers present, no horizontal overflow, artifact
    screenshots under ``_artifacts/``.

What remains open (do **not** flip W10 to “fully done”):
  - Pixel/DOM regression baseline + diff on the full app.
  - Live focus-vs-sticky, full-app keyboard-only, SR smoke,
    empty/loading/error/offline visual pass on the live app.
  - Spawned/self-contained stack mode (currently relies on external stack).
"""
