# W10.F1 — live Streamlit e2e harness

External-stack smoke against a running local stack. First wave of live
Streamlit gates closing W10 release-open items incrementally.

## What this is

`tests/e2e/` is the runtime home for **live Streamlit** gates (Playwright
against a real `streamlit run app/ui/main.py`). It complements — does **not**
replace — `tests/test_w10_release_gates.py` (static) and
`tests/test_w10_visual_matrix.py` (pure-HTML Playwright fixtures).

The live suite is excluded from default `pytest` collection by
`tests/conftest.py`; run it explicitly with `pytest tests/e2e`.

### W10.F1 (2026-07-18) — closed

- Mission Control cold-state live smoke on the release viewport matrix
  (`1366×768`, `1920×1080`, `390×844`):
  - HTTP 200 + Streamlit `stMain` present,
  - **no `stException`** (catches regressions like the
    `_render_hidden_nav_expander` leftover call fixed in this wave),
  - Mission Control real-DOM markers present via `querySelectorAll` on the
    explicit `data-testid` hooks the renderer emits
    (`[data-testid="mission-control-ssr-banner"]` ≥1,
    `[data-testid^="mission-tile-"]` ≥3) — not CSS-class substrings in
    `body_html`, which would also match the injected `<style>`,
  - no horizontal `scrollWidth` overflow,
  - no Playwright `pageerror` during render,
  - artifact screenshot under `_artifacts/` for human review (inventory,
    not a pixel gate).

### Still open (do **not** flip W10 to “fully done”)

- Pixel/DOM baseline + diff on the live app (current artifacts are
  inventory-only; no committed baseline).
- Mission Control **returning** state (warm session), SSR actionable body.
- Live focus-vs-sticky in Streamlit chrome.
- Full-app keyboard-only smoke across all critical destinations.
- Screen-reader smoke audit.
- Empty / loading / error / offline **visual** pass on the live app.
- 200% zoom + reduced-motion on the **live** Streamlit chrome
  (already covered on pure-HTML fixtures in `test_w10_visual_matrix.py`).
- Spawned/self-contained stack mode (this harness relies on an external
  stack; a future wave can add subprocess spawning for CI autonomy).

## How to run

The harness connects to an already-running local stack. Start it once:

```powershell
.\scripts\run_local_stack.ps1 -SkipPip
# backend → http://127.0.0.1:8000 ; streamlit → http://127.0.0.1:8501
```

Then in another terminal:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
```

> **Note on the `e2e` marker:** every live test carries `pytestmark = pytest.mark.e2e`
> (registered in `pyproject.toml`), but the marker is a **label**, not a run selector.
> Opt-in is path-based: `pytest tests/e2e`. `tests/conftest.py::pytest_ignore_collect`
> keeps the live suite out of default `pytest` collection, so `pytest -m e2e`
> collects `0` tests by design (the files are not collected in the default run).
> Use `pytest tests/e2e` explicitly.

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `HT_E2E_STREAMLIT_URL` | `http://127.0.0.1:8501` | Override the Streamlit base URL. |
| `HT_SKIP_E2E_LIVE` | unset | `1` skips the whole live suite (CI without a stack). |

If the stack is unreachable the suite **skips** (not fails) with a hint.

## Extending

- Add a new surface: create `tests/e2e/test_<surface>_live.py`, reuse
  `e2e_browser` / `e2e_streamlit_url` / `e2e_artifacts_dir` fixtures and
  `open_streamlit_page(...)` helper from `conftest.py`.
- Spawned mode: add a session-scoped fixture in `conftest.py` that launches
  `uvicorn app.api:app` + `streamlit run app/ui/main.py` on free ports and
  sets `HT_E2E_STREAMLIT_URL`; gate behind `HT_E2E_SPAWN_STACK=1`.
- Pixel baseline: when ready, introduce `_baselines/` (tracked) + a diff
  threshold; only then can W10 move from “partially done” to “done” for the
  live-app regression axis.

## Artifacts policy

`tests/e2e/_artifacts/` is gitignored. Screenshots are produced for human
triage and are **not** a committed acceptance baseline. Overwriting
`docs/screenshots/final` is still forbidden (see W10 principles).
