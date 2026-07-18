# W10.F1/W10.F2/W10.F3 — live Streamlit e2e harness

Spawned-stack smoke against real FastAPI + Streamlit by default, with an
external URL override for local debugging. These live gates close W10 release
open items incrementally.

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

### W10.F2 (2026-07-18) — closed

- Self-contained spawned stack mode:
  - starts `uvicorn app.api:app` + `streamlit run app/ui/main.py` on free ports,
  - uses a temporary seeded `HOME_RAG_HOME` / Chroma collection / registry,
  - sets `HOME_RAG_E2E_OFFLINE=1` so the visual smoke does not depend on LM Studio
    or cloud keys,
  - writes process logs to `_artifacts/spawned_fastapi.log` and
    `_artifacts/spawned_streamlit.log`.
- Mission Control returning/warm-state live smoke on the release viewport matrix:
  - same matrix (`1366×768`, `1920×1080`, `390×844`),
  - same hard guards as W10.F1: no `stException`, no page/console errors,
    no horizontal overflow,
  - returning/non-cold proof: mission tiles >3, `Ещё режимы` inventory present,
    empty-index first-run hero absent,
  - SSR actionable body present (`e2e-ssr-why-not-others`,
    `e2e-ssr-contrast`),
  - visible singular primary learning CTA in the main Mission Control flow,
  - artifact screenshots under `_artifacts/mission_control_returning_*.png`.

### W10.F3 (2026-07-19) — closed

- Mission Control live focus-vs-sticky smoke on the release viewport matrix:
  - tabs through visible focus stops,
  - checks focused control boxes stay in viewport,
  - checks `elementFromPoint` does not reveal fixed/sticky chrome covering the
    focused control,
  - keeps screenshots under `_artifacts/mission_control_focus_*.png`.
- Mission Control primary learning/onboarding CTA keyboard activation smoke:
  - reaches the CTA via Tab,
  - activates it with Enter,
  - asserts no `stException`, no page/console errors, and no horizontal overflow,
  - keeps `_artifacts/mission_control_keyboard_cta_1366x768.png`.

### Still open (do **not** flip W10 to “fully done”)

- Pixel/DOM baseline + diff on the live app (current artifacts are
  inventory-only; no committed baseline).
- Live focus-vs-sticky beyond Mission Control / remaining critical surfaces.
- Full-app keyboard-only smoke across all critical destinations.
- Screen-reader smoke audit.
- Empty / loading / error / offline **visual** pass on the live app.
- 200% zoom + reduced-motion on the **live** Streamlit chrome
  (already covered on pure-HTML fixtures in `test_w10_visual_matrix.py`).

## How to run

Default spawned-stack mode:

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
| `HT_E2E_STREAMLIT_URL` | unset | Use an already-running Streamlit URL instead of spawned-stack mode. |
| `HT_SKIP_E2E_LIVE` | unset | `1` skips the whole live suite. |

If `HT_E2E_STREAMLIT_URL` is set and unreachable, the suite **skips** with a
hint. In default spawned-stack mode, startup failures fail the explicit e2e run
and point to the spawned process logs under `_artifacts/`.

## Extending

- Add a new surface: create `tests/e2e/test_<surface>_live.py`, reuse
  `e2e_browser` / `e2e_streamlit_url` / `e2e_artifacts_dir` fixtures and
  `open_streamlit_page(...)` helper from `conftest.py`.
- Pixel baseline: when ready, introduce `_baselines/` (tracked) + a diff
  threshold; only then can W10 move from “partially done” to “done” for the
  live-app regression axis.

## Artifacts policy

`tests/e2e/_artifacts/` is gitignored. Screenshots are produced for human
triage and are **not** a committed acceptance baseline. Overwriting
`docs/screenshots/final` is still forbidden (see W10 principles).
