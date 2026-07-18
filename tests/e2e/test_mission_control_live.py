"""W10.F1/W10.F2/W10.F3 — Mission Control live smoke on the release viewport matrix.

Smoke against a real local stack (spawned by default; external URL override is
still supported in ``tests/e2e/conftest.py``). W10.F1 landed the first live
Mission Control DOM/overflow gate. W10.F2 extends it with returning-state checks
on the same release viewport matrix. W10.F3 adds Mission Control keyboard/focus
smoke without claiming full-app keyboard coverage.

This wave does **not** close: pixel baseline/diff, full-app keyboard-only,
SR smoke, empty/loading/error/offline visuals, screen-reader smoke — those are
subsequent W10.F waves.
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

_FOCUS_SNAPSHOT_JS = """
() => {
  const active = document.activeElement;
  if (!active || active === document.body || active === document.documentElement) {
    return { focused: false };
  }
  const rect = active.getBoundingClientRect();
  const label = (
    active.getAttribute('aria-label') ||
    active.innerText ||
    active.textContent ||
    active.getAttribute('title') ||
    active.getAttribute('data-testid') ||
    active.tagName ||
    ''
  ).trim().replace(/\\s+/g, ' ').slice(0, 120);

  const visibleBox = rect.width > 0 && rect.height > 0;
  const inViewport = visibleBox &&
    rect.bottom > 0 && rect.right > 0 &&
    rect.top < window.innerHeight && rect.left < window.innerWidth;
  const points = [
    [rect.left + rect.width / 2, rect.top + rect.height / 2],
    [rect.left + Math.min(rect.width - 1, 3), rect.top + Math.min(rect.height - 1, 3)],
    [rect.right - Math.min(rect.width - 1, 3), rect.bottom - Math.min(rect.height - 1, 3)],
  ].filter(([x, y]) => x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight);

  function stickyAncestor(el) {
    let cur = el;
    while (cur && cur !== document.body && cur !== document.documentElement) {
      const pos = window.getComputedStyle(cur).position;
      if (pos === 'sticky' || pos === 'fixed') {
        return {
          tag: cur.tagName,
          role: cur.getAttribute('role') || '',
          testid: cur.getAttribute('data-testid') || '',
          text: (cur.innerText || cur.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80),
          position: pos,
        };
      }
      cur = cur.parentElement;
    }
    return null;
  }

  const blockers = [];
  for (const [x, y] of points) {
    const top = document.elementFromPoint(x, y);
    if (!top || top === active || active.contains(top) || top.contains(active)) {
      continue;
    }
    const sticky = stickyAncestor(top);
    if (sticky) blockers.push(sticky);
  }
  return {
    focused: true,
    tag: active.tagName,
    role: active.getAttribute('role') || '',
    testid: active.getAttribute('data-testid') || '',
    label,
    rect: {
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      bottom: Math.round(rect.bottom),
    },
    inViewport,
    blockers,
  };
}
"""


def _vp_id(vp: dict[str, int]) -> str:
    return f"{vp['width']}x{vp['height']}"


def _assert_no_streamlit_exception(page, viewport: dict[str, int]) -> None:
    exc_el = page.query_selector('[data-testid="stException"]')
    assert exc_el is None, (
        f"[{_vp_id(viewport)}] Streamlit stException present: "
        f"{exc_el.inner_text()[:400] if exc_el else ''}"
    )


def _mission_control_counts(page) -> dict[str, int]:
    counts = page.evaluate(
        """
        (selectors) => selectors.map(s => document.querySelectorAll(s).length)
        """,
        [sel for sel, _label, _min in _MISSION_CONTROL_SELECTORS],
    )
    return {
        label: count
        for (_sel, label, _min), count in zip(_MISSION_CONTROL_SELECTORS, counts)
    }


def _visible_primary_learning_ctas(page) -> list[str]:
    return page.evaluate(
        """
        () => {
          const main = document.querySelector('section[data-testid="stMain"]');
          const banner = document.querySelector('[data-testid="mission-control-ssr-banner"]');
          if (!main || !banner) return [];
          const bannerTop = banner.getBoundingClientRect().top;
          const moreModes = Array.from(main.querySelectorAll('button, details, summary'))
            .find((el) => (el.innerText || el.textContent || '').includes('Ещё режимы'));
          const moreModesTop = moreModes ? moreModes.getBoundingClientRect().top : Number.POSITIVE_INFINITY;
          return Array.from(main.querySelectorAll('button'))
          .filter((btn) => {
            const rect = btn.getBoundingClientRect();
            const style = window.getComputedStyle(btn);
            const visible = rect.width > 0 && rect.height > 0 &&
              style.visibility !== 'hidden' && style.display !== 'none';
            const kind = `${btn.getAttribute('kind') || ''} ${btn.getAttribute('data-testid') || ''}`.toLowerCase();
            return visible && kind.includes('primary') && rect.top >= bannerTop && rect.top < moreModesTop;
          })
          .map((btn) => (btn.innerText || btn.textContent || '').trim())
          .filter(Boolean);
        }
        """
    )


def _active_focus_snapshot(page) -> dict:
    return page.evaluate(_FOCUS_SNAPSHOT_JS)


def _tab_until_any_label(page, needles: tuple[str, ...], *, max_tabs: int = 100) -> dict:
    seen: list[str] = []
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        page.wait_for_timeout(80)
        snap = _active_focus_snapshot(page)
        label = str(snap.get("label") or snap.get("testid") or snap.get("tag") or "")
        if label and label not in seen:
            seen.append(label)
        if snap.get("inViewport") is not True:
            continue
        if any(needle.casefold() in label.casefold() for needle in needles):
            return snap
    raise AssertionError(
        f"Could not focus label containing one of {needles!r} within {max_tabs} tabs. "
        f"Seen labels: {seen}"
    )


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
        _assert_no_streamlit_exception(page, viewport)

        main_el = page.query_selector('section[data-testid="stMain"]')
        assert main_el is not None, f"[{_vp_id(viewport)}] stMain container missing"

        # Real-DOM marker check (NOT substring search in body_html — the CSS
        # class names ``.mode-card`` / ``.mission-tile`` / ``.ssr-banner`` also
        # live in the injected stylesheet, so a substring match could pass even
        # when Mission Control never painted). Query actual elements by the
        # explicit ``data-testid`` hooks the renderer emits.
        observed = _mission_control_counts(page)
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
        console_errors = getattr(page, "_e2e_console_errors", [])
        assert not console_errors, f"[{_vp_id(viewport)}] console error(s): {console_errors[:3]}"

        # Inventory artifact (not a gate): screenshot for human review.
        shot = e2e_artifacts_dir / f"mission_control_cold_{_vp_id(viewport)}.png"
        page.screenshot(path=str(shot), full_page=True)
        assert shot.is_file() and shot.stat().st_size > 0
    finally:
        context.close()


@pytest.mark.parametrize("viewport", MISSION_CONTROL_VIEWPORTS, ids=_vp_id)
def test_mission_control_returning_state_live(
    e2e_browser,
    e2e_streamlit_url: str,
    e2e_artifacts_dir: Path,
    viewport: dict[str, int],
) -> None:
    """Returning/warm Mission Control renders actionable non-cold content."""
    context, page = open_streamlit_page(e2e_browser, e2e_streamlit_url, viewport=viewport)
    try:
        # Same browser context + reload keeps Streamlit's warm session path honest.
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('section[data-testid="stMain"]', timeout=20000)
        page.wait_for_timeout(5000)

        _assert_no_streamlit_exception(page, viewport)
        assert page.query_selector('section[data-testid="stMain"]') is not None, (
            f"[{_vp_id(viewport)}] stMain container missing after warm reload"
        )
        assert page.query_selector('[data-testid="stSidebar"]') is not None, (
            f"[{_vp_id(viewport)}] main navigation/sidebar missing"
        )

        observed = _mission_control_counts(page)
        assert observed["SSR banner"] >= 1, (
            f"[{_vp_id(viewport)}] SSR banner missing in returning state: {observed}"
        )
        assert observed["mission tile"] > 3, (
            f"[{_vp_id(viewport)}] returning state still looks like cold 3-tile mode: {observed}"
        )
        for sel in (
            '[data-testid="e2e-ssr-why-not-others"]',
            '[data-testid="e2e-ssr-contrast"]',
        ):
            assert page.query_selector(sel) is not None, (
                f"[{_vp_id(viewport)}] SSR actionable body selector missing: {sel}"
            )

        body_text = page.inner_text("body")
        assert "Добавьте материалы" not in body_text, (
            f"[{_vp_id(viewport)}] returning state fell back to empty-index first-run hero"
        )
        assert "Ещё режимы" in body_text, (
            f"[{_vp_id(viewport)}] returning state did not expose the collapsed mode inventory"
        )

        primary_buttons = _visible_primary_learning_ctas(page)
        assert len(primary_buttons) == 1, (
            f"[{_vp_id(viewport)}] expected exactly one visible primary CTA, got {primary_buttons}"
        )

        overflow = page.evaluate(OVERFLOW_JS)
        assert overflow["overflowX"] is False, (
            f"[{_vp_id(viewport)}] horizontal overflow: {overflow}"
        )

        page_errors = getattr(page, "_e2e_errors", [])
        assert not page_errors, f"[{_vp_id(viewport)}] pageerror(s): {page_errors[:3]}"
        console_errors = getattr(page, "_e2e_console_errors", [])
        assert not console_errors, f"[{_vp_id(viewport)}] console error(s): {console_errors[:3]}"

        shot = e2e_artifacts_dir / f"mission_control_returning_{_vp_id(viewport)}.png"
        page.screenshot(path=str(shot), full_page=True)
        assert shot.is_file() and shot.stat().st_size > 0
    finally:
        context.close()


@pytest.mark.parametrize("viewport", MISSION_CONTROL_VIEWPORTS, ids=_vp_id)
def test_mission_control_focus_not_covered_by_sticky_chrome_live(
    e2e_browser,
    e2e_streamlit_url: str,
    e2e_artifacts_dir: Path,
    viewport: dict[str, int],
) -> None:
    """Keyboard focus stays visible and is not covered by sticky/fixed chrome."""
    context, page = open_streamlit_page(e2e_browser, e2e_streamlit_url, viewport=viewport)
    try:
        _assert_no_streamlit_exception(page, viewport)
        observed_labels: list[str] = []
        checked: list[dict] = []
        for _ in range(24):
            page.keyboard.press("Tab")
            page.wait_for_timeout(80)
            snap = _active_focus_snapshot(page)
            if not snap.get("focused"):
                continue
            if snap.get("inViewport") is not True:
                # Streamlit keeps some zero-size internal inputs in the tab order;
                # they are not visible learning controls and cannot be occluded by
                # sticky chrome, so they are outside this live visual smoke.
                continue
            label = str(snap.get("label") or snap.get("testid") or snap.get("tag") or "")
            if label and label not in observed_labels:
                observed_labels.append(label)
            checked.append(snap)
            assert not snap.get("blockers"), (
                f"[{_vp_id(viewport)}] sticky/fixed chrome covers focus: {snap}"
            )

        assert len(checked) >= 6, (
            f"[{_vp_id(viewport)}] too few keyboard focus stops checked: {observed_labels}"
        )
        assert any("Короткая учебная сессия" in label or "Начать" in label for label in observed_labels), (
            f"[{_vp_id(viewport)}] keyboard did not reach primary learning CTA: {observed_labels}"
        )

        overflow = page.evaluate(OVERFLOW_JS)
        assert overflow["overflowX"] is False, (
            f"[{_vp_id(viewport)}] horizontal overflow after keyboard traversal: {overflow}"
        )
        page_errors = getattr(page, "_e2e_errors", [])
        assert not page_errors, f"[{_vp_id(viewport)}] pageerror(s): {page_errors[:3]}"
        console_errors = getattr(page, "_e2e_console_errors", [])
        assert not console_errors, f"[{_vp_id(viewport)}] console error(s): {console_errors[:3]}"

        shot = e2e_artifacts_dir / f"mission_control_focus_{_vp_id(viewport)}.png"
        page.screenshot(path=str(shot), full_page=True)
        assert shot.is_file() and shot.stat().st_size > 0
    finally:
        context.close()


def test_mission_control_primary_cta_keyboard_activation_live(
    e2e_browser,
    e2e_streamlit_url: str,
    e2e_artifacts_dir: Path,
) -> None:
    """Primary Mission Control learning/onboarding CTA activates without regressions."""
    viewport = {"width": 1366, "height": 768}
    context, page = open_streamlit_page(e2e_browser, e2e_streamlit_url, viewport=viewport)
    try:
        before = page.inner_text("body")
        assert "Mission Control" in before
        focused = _tab_until_any_label(
            page,
            ("Короткая учебная сессия", "Начать", "Тьютор"),
            max_tabs=120,
        )
        assert focused.get("inViewport") is True, f"primary CTA focused off-screen: {focused}"
        assert not focused.get("blockers"), f"primary CTA focus covered by sticky chrome: {focused}"

        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)
        _assert_no_streamlit_exception(page, viewport)
        after = page.inner_text("body")
        assert "Mission Control" in after or "Ещё режимы" in after or "Чат с тьютором" in after, (
            "keyboard activation left the app in an unexpected state"
        )
        overflow = page.evaluate(OVERFLOW_JS)
        assert overflow["overflowX"] is False, (
            f"[{_vp_id(viewport)}] horizontal overflow after keyboard activation: {overflow}"
        )

        page_errors = getattr(page, "_e2e_errors", [])
        assert not page_errors, f"[{_vp_id(viewport)}] pageerror(s): {page_errors[:3]}"
        console_errors = getattr(page, "_e2e_console_errors", [])
        assert not console_errors, f"[{_vp_id(viewport)}] console error(s): {console_errors[:3]}"

        shot = e2e_artifacts_dir / "mission_control_keyboard_cta_1366x768.png"
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
