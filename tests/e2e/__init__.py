"""W10.F1/W10.F2/W10.F3 live Streamlit e2e harness.

Spawned-stack smoke against real FastAPI + Streamlit by default, with an
external URL override for local debugging. See ``tests/e2e/README.md`` for
details and extension policy.

What this harness closes so far:
  - Mission Control cold-state live smoke on the release viewport matrix
    (1366×768, 1920×1080, 390×844): HTTP 200, no Streamlit exception,
    Mission Control DOM markers present, no horizontal overflow, artifact
    screenshots under ``_artifacts/`` (W10.F1).
  - Spawned-stack mode + Mission Control returning-state smoke with SSR
    actionable body and non-cold tile inventory (W10.F2).
  - Mission Control focus-vs-sticky smoke + primary CTA keyboard activation
    smoke (W10.F3).

What remains open (do **not** flip W10 to “fully done”):
  - Pixel/DOM regression baseline + diff on the full app.
  - Remaining surface focus-vs-sticky, full-app keyboard-only, SR smoke,
    empty/loading/error/offline visual pass on the live app.
"""
