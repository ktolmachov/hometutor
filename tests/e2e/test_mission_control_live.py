"""W10.F1 — Mission Control live smoke on the release viewport matrix.

Cold-state smoke against a running local stack (external-stack mode; see
``tests/e2e/conftest.py``). This is the first live Streamlit gate: HTTP 200,
no Streamlit exception, Mission Control DOM markers present, no horizontal
overflow, artifact screenshots under ``tests/e2e/_artifacts/``.

This wave does **not** close: pixel baseline/diff, focus-vs-sticky,
full-app keyboard-only, SR smoke, empty/loading/error/offline visuals,
returning-state (warm session) — those are subsequent W10.F waves.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.conftest import OVERFLOW_JS, open_streamlit_page

pytestmark = pytest.mark.e2e

# Release viewport matrix (docs/ui_ux_design_review_implementation_plan.md §W10.D).
MISSION_CONTROL_VIEWPORTS: tuple[dict[str, int], ...] = (
    {"width": 1366, "height": 768},
    {"width": 1920, "height": 1080},
    {"width": 390, "height": 844},
)

# DOM selectors proving Mission Control actually rendered. These are explicit
# ``data-testid`` hooks emitted by ``app/ui/mission_control.py`` (not CSS class
# names that also appear in injected ``<style>``), so a passing query means the
# surface painted real elements — not just that the stylesheet was injected.
#   * ``mission-control-ssr-banner`` — mission_control.py:401, rendered for both
#     cold and returning users (render_mission_control → _render_ssr_banner).
#   * ``mission-tile-`` prefix — mission_control.py:450, one per tile.
#     Cold state paints exactly 3 (``_COLD_USER_TILE_IDS``); returning paints
#     more. We assert the floor (>=3) so the gate is honest for cold smoke and
#     does not over-fit to a specific non-cold tile count.
_MISSION_CONTROL_SELECTORS: tuple[tuple[str, str, int], ...] = (
    # (css_selector, label, min_count)
    ('[data-testid="mission-control-ssr-banner"]', "SSR banner", 1),
    ('[data-testid^="mission-tile-"]', "mission tile", 3),
)


def _vp_id(vp: dict[str, int]) -> str:
    return f"{vp['width']}x{vp['height']}"


@pytest.mark.parametrize("viewport", MISSION_CONTROL_VIEWPORTS, ids=_vp_id)
def test_mission_control_cold_state_live(
    e2e_browser,
    e2e_streamlit_url: str,
    e2e_artifacts_dir: Path,
    viewport: dict[str, int],
) -> None:
    """Cold-state Mission Control renders without exception or overflow."""
    context, page = open_streamlit_page(e2e_browser, e2e_streamlit_url, viewport=viewport)
    try:
        # Hard guard: a Streamlit script exception means the surface did not render.
        exc_el = page.query_selector('[data-testid="stException"]')
        assert exc_el is None, (
            f"[{_vp_id(viewport)}] Streamlit stException present: "
            f"{exc_el.inner_text()[:400] if exc_el else ''}"
        )

        main_el = page.query_selector('section[data-testid="stMain"]')
        assert main_el is not None, f"[{_vp_id(viewport)}] stMain container missing"

        # Real-DOM marker check (NOT substring search in body_html — the CSS
        # class names ``.mode-card`` / ``.mission-tile`` / ``.ssr-banner`` also
        # live in the injected stylesheet, so a substring match could pass even
        # when Mission Control never painted). Query actual elements by the
        # explicit ``data-testid`` hooks the renderer emits.
        counts = page.evaluate(
            """
            (selectors) => selectors.map(s => document.querySelectorAll(s).length)
            """,
            [sel for sel, _label, _min in _MISSION_CONTROL_SELECTORS],
        )
        observed = {
            label: count
            for (sel, label, _min), count in zip(_MISSION_CONTROL_SELECTORS, counts)
        }
        for sel, label, min_count in _MISSION_CONTROL_SELECTORS:
            actual = observed[label]
            assert actual >= min_count, (
                f"[{_vp_id(viewport)}] {label}: querySelectorAll('{sel}') "
                f"→ {actual}, expected >= {min_count}. observed={observed}"
            )

        overflow = page.evaluate(OVERFLOW_JS)
        assert overflow["overflowX"] is False, (
            f"[{_vp_id(viewport)}] horizontal overflow: {overflow}"
        )

        # Page-error honesty: collect JS exceptions thrown during render.
        page_errors = getattr(page, "_e2e_errors", [])
        assert not page_errors, f"[{_vp_id(viewport)}] pageerror(s): {page_errors[:3]}"

        # Inventory artifact (not a gate): screenshot for human review.
        shot = e2e_artifacts_dir / f"mission_control_cold_{_vp_id(viewport)}.png"
        page.screenshot(path=str(shot), full_page=True)
        assert shot.is_file() and shot.stat().st_size > 0
    finally:
        context.close()


def test_mission_control_live_matrix_coverage_documented() -> None:
    """Honesty guard: the live matrix matches the W10 documented viewports."""
    widths = {vp["width"] for vp in MISSION_CONTROL_VIEWPORTS}
    assert {1366, 1920, 390}.issubset(widths)
    # Plan must mention each release viewport so the live gate stays anchored.
    plan = (Path(__file__).resolve().parents[2] / "docs" / "ui_ux_design_review_implementation_plan.md").read_text(
        encoding="utf-8"
    )
    for token in ("1366×768", "1920×1080", "390×844"):
        assert token in plan, f"release viewport {token} not in implementation plan"
