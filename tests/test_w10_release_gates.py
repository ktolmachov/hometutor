"""W10 Release / visual gates — inventory + static contracts.

Does not claim full screenshot matrix pass. Automates what can be checked
without a running Streamlit stack: reduced-motion surface audit, foundation
sizing/focus, SSR AA text tokens, library overflow hooks, and critical
surface contract presence. Full viewport screenshot + keyboard/200% zoom
remain manual / Playwright-on-live-app gates (see implementation plan §W10).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from app.ui.design_tokens import (
    FOUNDATION_TOKENS,
    FULL_DARK_DECISION,
    SPATIAL_DARK_TOKENS,
    UI_MODES,
)

ROOT = Path(__file__).resolve().parents[1]

# Target matrix from docs/ui_ux_design_review_implementation_plan.md §W10
W10_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (1366, 768),
    (1920, 1080),
    (390, 844),
    (1440, 900),  # optional desktop sanity
)

# Critical surfaces for release gates (product list from W10 DoD).
W10_CRITICAL_SURFACES: tuple[str, ...] = (
    "mission_control",
    "global_navigation",
    "mnemo_3d_hall",
    "flashcards_review",
    "quiz",
    "living_konspekt",
    "library",
    "tutor_chat",
    "adaptive_plan",
    "onboarding",
)

# Automated coverage already living in targeted unit/contract tests.
EXISTING_AUTO_GATES: dict[str, tuple[str, ...]] = {
    "quiz_integrity": ("tests/test_interactive_quiz_ui_contract.py",),
    "onboarding": ("tests/test_tutorial_activation_flow.py",),
    "design_tokens_foundation": ("tests/test_ui_design_tokens.py",),
    "theme_portals_full_dark_deferred": ("tests/test_theme_portals_contract.py",),
    "flashcards_a11y_sizing": ("tests/test_flashcards_interactive_card.py",),
    "flashcards_keyboard": ("tests/test_flashcards_review_keyboard.py",),
    "mnemo_3d_viewport_overflow_playwright": ("tests/test_knowledge_graph_counters.py",),
    "navigation_ia": ("tests/test_global_navigation.py", "tests/test_navigation_visibility.py"),
    "living_konspekt_reader": ("tests/test_living_konspekt_view_smoke.py",),
    "library_3_2_1": ("tests/test_library_schedule_ui_contract.py", "tests/test_source_address.py"),
    "tutor_chat": ("tests/test_tutor_chat_ui_contract.py", "tests/test_tutor_chat_handoff_scroll.py"),
    "adaptive_plan": ("tests/test_adaptive_plan_ui_contract.py", "tests/test_adaptive_plan_progress.py"),
    "mission_control": (
        "tests/test_mission_control_navigation.py",
        "tests/test_mission_control_progressive.py",
    ),
}

# Gates that still need live UI / manual / full-app Playwright (not static-only).
MANUAL_OR_LIVE_GATES: tuple[str, ...] = (
    "screenshot_dom_regression_full_streamlit_app",
    "keyboard_only_smoke_full_app",
    "focus_vs_sticky_live_interaction",
    "empty_loading_error_offline_visual_pass",
    "screen_reader_smoke_audit",
)

# Pure-HTML Playwright matrix (no Streamlit): tests/test_w10_visual_matrix.py
EXISTING_PLAYWRIGHT_HTML_GATES: tuple[str, ...] = (
    "flashcard_viewport_overflow_touch",
    "flashcard_reduced_motion",
    "flashcard_keyboard_flip",
    "host_chrome_ssr_lib_mission_overflow_aa",
    "host_chrome_200pct_zoom",
    "host_reduced_motion_hover",
    "d3_reduced_motion_mobile_overflow",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance for #RRGGBB."""
    h = hex_color.removeprefix("#")
    assert len(h) == 6, hex_color
    channels = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg: str, bg: str) -> float:
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _css_color_value(rule_body: str) -> str:
    color_m = re.search(r"^\s*color:\s*([^;]+);", rule_body, flags=re.M)
    assert color_m, "missing color declaration"
    return color_m.group(1).strip()


def _fallback_hex(value: str) -> str:
    hex_m = re.search(r"#[0-9a-fA-F]{6}", value)
    assert hex_m, f"missing computable hex fallback in {value!r}"
    return hex_m.group(0)


# ── Inventory / matrix constants ─────────────────────────────────────────────


def test_w10_viewport_matrix_documented() -> None:
    assert (1366, 768) in W10_VIEWPORTS
    assert (1920, 1080) in W10_VIEWPORTS
    assert (390, 844) in W10_VIEWPORTS
    plan = _read("docs/ui_ux_design_review_implementation_plan.md")
    for w, h in ((1366, 768), (1920, 1080), (390, 844)):
        assert f"{w}×{h}" in plan or f"{w}x{h}" in plan


def test_w10_existing_auto_gate_files_present() -> None:
    for gate, files in EXISTING_AUTO_GATES.items():
        for rel in files:
            path = ROOT / rel
            assert path.is_file(), f"missing auto-gate file for {gate}: {rel}"


def test_w10_manual_gates_listed_for_honesty() -> None:
    # Prevent silent “all green” without acknowledging live-app gates.
    assert "screenshot_dom_regression_full_streamlit_app" in MANUAL_OR_LIVE_GATES
    assert len(MANUAL_OR_LIVE_GATES) >= 4
    assert len(W10_CRITICAL_SURFACES) >= 8
    assert len(EXISTING_PLAYWRIGHT_HTML_GATES) >= 5
    assert (ROOT / "tests" / "test_w10_visual_matrix.py").is_file()


# ── Foundation / theme invariants (release package) ──────────────────────────


def test_w10_foundation_type_and_control_floors() -> None:
    assert FOUNDATION_TOKENS["type-meta"] == "12px"
    assert FOUNDATION_TOKENS["type-body"] == "16px"
    assert FOUNDATION_TOKENS["control-default"] == "40px"
    assert FOUNDATION_TOKENS["control-touch"] == "44px"


def test_w10_full_dark_still_deferred_base_light() -> None:
    assert FULL_DARK_DECISION == "deferred"
    assert "dark" not in UI_MODES
    cfg = _read(".streamlit/config.toml")
    assert 'base = "light"' in cfg


def test_w10_spatial_dark_text_on_surface_meets_aa_normal() -> None:
    ratio = _contrast_ratio(SPATIAL_DARK_TOKENS["text"], SPATIAL_DARK_TOKENS["surface"])
    assert ratio >= 4.5, f"spatial-dark text/surface contrast {ratio:.2f} < 4.5"


def test_w10_status_tokens_on_light_surface_meet_aa() -> None:
    # Card/surface default used with status text chips (white/panel).
    light_bg = "#ffffff"
    for key in ("status-ok", "status-warn", "status-error", "status-info"):
        ratio = _contrast_ratio(FOUNDATION_TOKENS[key], light_bg)
        assert ratio >= 4.5, f"{key} contrast {ratio:.2f} on {light_bg}"


# ── Reduced-motion audit (all custom surfaces in host + iframes) ─────────────


@pytest.mark.parametrize(
    "rel",
    [
        "app/ui_theme.css",
        "app/ui/assets/kg_3d_template.html",
        "app/ui/assets/knowledge_graph_d3_template.html",
        "app/ui/flashcards_interactive_card_style.py",
        "app/ui/tutor_chat_header.py",
        "app/ui/tutor_chat_session.py",
    ],
)
def test_w10_custom_surface_declares_prefers_reduced_motion(rel: str) -> None:
    text = _read(rel)
    assert "prefers-reduced-motion" in text, f"{rel} missing reduced-motion gate"


def test_w10_host_reduced_motion_kills_card_hover_transforms() -> None:
    css = _read("app/ui_theme.css")
    # Extract first/global reduced-motion block that covers card hovers.
    assert ".home-dash-card:hover" in css
    assert ".mode-card:hover" in css
    blocks = re.findall(
        r"@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{(.*?)\n\}",
        css,
        flags=re.S,
    )
    joined = "\n".join(blocks)
    assert ".home-dash-card" in joined
    assert ".mode-card" in joined
    assert "transform: none" in joined
    assert ".hero-grid--4-3 .mission-tile" in joined


def test_w10_d3_template_disables_infinite_pulse_under_reduced_motion() -> None:
    html = _read("app/ui/assets/knowledge_graph_d3_template.html")
    assert "frontier-halo" in html
    assert "decay-ring" in html
    assert "prefers-reduced-motion" in html
    # Within reduce media, animations must be cancelled.
    m = re.search(
        r"@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}",
        html,
        flags=re.S,
    )
    assert m, "missing reduced-motion media block in D3 template"
    body = m.group(0)
    assert "animation:none" in body.replace(" ", "")
    assert "frontier-halo" in body
    assert "decay-ring" in body


def test_w10_d3_template_gates_js_transitions_under_reduced_motion() -> None:
    html = _read("app/ui/assets/knowledge_graph_d3_template.html")
    compact = re.sub(r"\s+", "", html)
    assert "constprefersReducedMotion=" in compact
    assert "if(prefersReducedMotion)svg.call(zoom.transform,t);" in compact
    assert (
        "if(prefersReducedMotion){routeG.selectAll('.rt')"
        ".attr('stroke-opacity',0.92);return;}"
    ) in compact
    assert "if(prefersReducedMotion)svg.call(zoom.transform,fitTransform);" in compact


def test_w10_kg3d_template_reduced_motion_and_no_external_cdn() -> None:
    html = _read("app/ui/assets/kg_3d_template.html")
    assert "prefers-reduced-motion" in html
    # Offline / local-first hall: no CDN script tags.
    assert "cdn." not in html.lower()
    assert "unpkg.com" not in html.lower()


def test_w10_tutor_handoff_animation_has_reduced_motion() -> None:
    src = _read("app/ui/tutor_chat_session.py")
    assert "qaTutorHandoffIn" in src
    assert "prefers-reduced-motion" in src
    assert "animation: none" in src or "animation:none" in src.replace(" ", "")


# ── SSR / Mission Control AA text gate (W10 bugfix) ─────────────────────────


def test_w10_ssr_kicker_and_toggle_meet_aa_on_sky_banner() -> None:
    """Normal text on SSR sky gradient must clear WCAG AA (≥4.5:1)."""
    css = _read("app/ui_theme.css")
    # Approximate mid sky surface from gradient stop.
    sky_bg = "#ebf5ff"
    # Extract .ssr-kicker color after W10 fix.
    kicker = re.search(r"\.ssr-kicker\s*\{([^}]+)\}", css, flags=re.S)
    assert kicker, "missing .ssr-kicker rule"
    kicker_body = kicker.group(1)
    kicker_color = _css_color_value(kicker_body)
    assert "var(--ssr-accent-readable" in kicker_color
    fg = _fallback_hex(kicker_color)
    ratio = _contrast_ratio(fg, sky_bg)
    assert ratio >= 4.5, f"ssr-kicker {fg} on {sky_bg} contrast {ratio:.2f} < 4.5"
    # Meaningful text floor.
    assert "var(--type-meta" in kicker_body or "12px" in kicker_body
    # Legacy failing color must not remain as computed text color.
    toggle = re.search(r"\.ssr-details-toggle\s*\{([^}]+)\}", css, flags=re.S)
    assert toggle
    toggle_body = toggle.group(1)
    toggle_color = _css_color_value(toggle_body)
    assert "var(--ssr-accent-readable" in toggle_color
    assert fg.lower() != "#4a9fd4"
    toggle_fg = _fallback_hex(toggle_color)
    assert toggle_fg.lower() != "#4a9fd4"
    toggle_ratio = _contrast_ratio(toggle_fg, sky_bg)
    assert toggle_ratio >= 4.5, (
        f"ssr-details-toggle {toggle_fg} on {sky_bg} "
        f"contrast {toggle_ratio:.2f} < 4.5"
    )


# ── Overflow / layout hooks ──────────────────────────────────────────────────


def test_w10_library_grid_has_overflow_safe_columns() -> None:
    css = _read("app/ui_theme.css")
    assert "lib-card" in css
    assert "max-width: 100%" in css
    assert "min-width: min(100%, 280px)" in css or "min-width: 100%" in css
    assert "flex-wrap: wrap" in css


def test_w10_focus_visible_foundation_present() -> None:
    css = _read("app/ui_theme.css")
    assert "focus-visible" in css
    assert "W3 accessibility foundation" in css
    assert "--focus-ring-color" in css or "var(--focus-ring-color" in css


# ── Critical surface source contracts (smoke) ────────────────────────────────


def test_w10_critical_surface_modules_exist() -> None:
    expected = {
        "mission_control": ("app.ui.mission_control", "render_mission_control"),
        "global_navigation": ("app.ui.global_navigation", "render_primary_destination_rail"),
        "mnemo_3d_hall": ("app/ui/assets/kg_3d_template.html", None),
        "flashcards_review": ("app.ui.flashcards_review_view", "render_review"),
        "quiz": ("app.ui.interactive_quiz", "_render_interactive_quiz_tab"),
        "living_konspekt": ("app.ui.living_konspekt_view", "render_living_konspekt_view"),
        "library": ("app.ui.library_schedule", "render_library_schedule"),
        "tutor_chat": ("app.ui.tutor_chat_session", "render_tutor_chat_tab"),
        "adaptive_plan": ("app.ui.adaptive_plan_hub_layout", "render_adaptive_plan_hub"),
        "onboarding": ("app.ui.mission_control_first_session", "render_first_session_block"),
    }
    for name in W10_CRITICAL_SURFACES:
        target, attr = expected[name]
        if attr is None:
            assert (ROOT / target).is_file(), f"critical surface {name}: missing {target}"
            continue
        mod = importlib.import_module(target)
        assert callable(getattr(mod, attr, None)), f"{name}: missing callable {target}.{attr}"


def test_w10_empty_or_offline_entry_points_present() -> None:
    """Structural empty/offline hooks (visual pass still manual)."""
    offline = importlib.import_module("app.ui.offline_banner")
    assert callable(getattr(offline, "render_offline_banner", None))
    library_mod = importlib.import_module("app.ui.library_schedule")
    assert callable(getattr(library_mod, "_render_empty", None))
    library = _read("app/ui/library_schedule.py")
    assert "_render_empty" in library
    flashcards = _read("app/ui/flashcards_ui.py")
    assert "fc-empty-state" in flashcards or "empty" in flashcards.casefold()


def test_w10_demo_screenshots_dir_is_inventory_not_gate() -> None:
    """Historical demo frames exist; W10 does not blanket-overwrite them."""
    shots = ROOT / "docs" / "screenshots" / "final"
    assert shots.is_dir()
    # At least one scenario folder for inventory honesty.
    scenarios = [p for p in shots.iterdir() if p.is_dir() and p.name.startswith("scenario_")]
    assert scenarios, "expected docs/screenshots/final/scenario_* inventory"


def test_w10_full_app_e2e_status_is_documented_without_blocking_future_suite() -> None:
    """Honesty gate: live e2e scaffold exists; full pixel regression still open.

    W10.F1 (2026-07-18) landed ``tests/e2e`` with a Mission Control live smoke
    against a running stack. That closes *one* live gate; it does **not** close
    pixel baseline/diff, focus-vs-sticky, full-app keyboard, SR smoke, or
    empty/loading/error/offline visuals. The plan must say so unambiguously.

    A bare word match on ``pixel`` would silently pass even if the plan later
    claimed ``pixel baseline done`` (and mixed-status lines like
    ``auto gates ✓; ... pixel ... open`` make per-line done-token bans brittle).
    Instead we require a structured anchor ``[W10-PIXEL-OPEN]`` whose checkbox
    stays open — flipping it to ``[x]`` is the only way to mark pixel done, and
    that flip is itself a review checkpoint.
    """
    plan = _read("docs/ui_ux_design_review_implementation_plan.md")
    e2e_dir = ROOT / "tests" / "e2e"
    assert e2e_dir.is_dir(), "tests/e2e must exist after W10.F1"
    assert (e2e_dir / "test_mission_control_live.py").is_file(), (
        "Mission Control live smoke missing in tests/e2e"
    )
    # Plan must acknowledge the W10.F1 wave.
    assert "W10.F1" in plan, "plan must reference W10.F1 live e2e wave"
    assert "tests/e2e" in plan

    # Structured anchor: the plan must carry exactly one ``[W10-PIXEL-OPEN]``
    # checkbox item whose status stays open. Other lines may *mention* the
    # anchor in prose (cross-references are fine); only the checkbox line is
    # authoritative. Flipping that one checkbox to ``[x]`` is the only way to
    # mark pixel regression done, and that flip is itself a review checkpoint.
    anchor = "[W10-PIXEL-OPEN]"
    anchor_lines = [ln for ln in plan.splitlines() if anchor in ln]
    assert anchor_lines, (
        f"plan must contain the {anchor} anchor marking pixel regression open"
    )
    checkbox_lines = [ln for ln in anchor_lines if ln.lstrip().startswith(("- [ ]", "- [x]", "- [~]"))]
    assert len(checkbox_lines) == 1, (
        f"exactly one {anchor} checkbox item expected, found {len(checkbox_lines)}: "
        f"{checkbox_lines}"
    )
    anchor_line = checkbox_lines[0]
    assert "[ ]" in anchor_line, (
        f"{anchor} checkbox must stay OPEN ([ ]): {anchor_line!r}"
    )
    assert "[x]" not in anchor_line, (
        f"{anchor} checkbox must NOT be closed ([x]): {anchor_line!r}"
    )
    # And the anchor paragraph must explicitly say "open".
    window = plan.split(anchor)[1][:160].lower()
    assert "open" in window, (
        f"{anchor} anchor must state the status is open near the marker"
    )

    # KG visual smoke remains part of W10 evidence until full-app e2e lands.
    kg_tests = _read("tests/test_knowledge_graph_counters.py")
    assert "3d_visual_smoke_viewport_matrix" in kg_tests or "viewport" in kg_tests


def test_w10_live_e2e_is_explicit_opt_in_not_default_collection() -> None:
    """Live Playwright tests must not contaminate the normal pytest suite."""
    root_conftest = _read("tests/conftest.py")
    pyproject = _read("pyproject.toml")
    live_test = _read("tests/e2e/test_mission_control_live.py")
    readme = _read("tests/e2e/README.md")

    assert "pytest_ignore_collect" in root_conftest
    assert "_E2E_ROOT" in root_conftest
    assert "_explicit_e2e_arg" in root_conftest
    assert "pytest tests/e2e" in root_conftest
    assert "e2e: live Streamlit/Playwright tests" in pyproject
    assert "pytestmark = pytest.mark.e2e" in live_test
    assert "excluded from default `pytest` collection" in readme
