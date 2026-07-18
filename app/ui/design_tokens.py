"""W3 semantic design foundation (pure, no Streamlit).

Shared space/type/control/motion tokens + modes contract.
Brand worlds stay in ``theme_presets.THEME_TOKENS``; foundation is global.
"""

from __future__ import annotations

from typing import Final

# Full Streamlit dark base remains deferred until Base Web portals are verified.
FULL_DARK_DECISION: Final[str] = "deferred"  # approved | rejected | deferred
FULL_DARK_RATIONALE: Final[str] = (
    "Streamlit base stays light: Base Web select/multiselect portals historically "
    "render black backgrounds under dark base. Modes in use: light (shell) + "
    "spatial-dark (Mnemonopolis hall). Full dark re-evaluate after portal spike."
)

# Keys that live in CSS :root but are NOT per-world brand tokens.
FOUNDATION_TOKEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "space-1",
        "space-2",
        "space-3",
        "space-4",
        "space-6",
        "space-8",
        "space-12",
        "radius-control",
        "radius-card",
        "radius-panel",
        "radius-overlay",
        "type-meta",
        "type-label",
        "type-body",
        "type-section",
        "type-title",
        "control-default",
        "control-touch",
        "motion-fast",
        "motion-default",
        "motion-panel",
        "ease-standard",
        "surface",
        "surface-card",
        "text",
        "text-muted",
        "border",
        "focus-ring-color",
        "status-ok",
        "status-warn",
        "status-error",
        "status-info",
        "ssr-accent-readable",
        "ssr-accent-readable-hover",
        "elevation-1",
        "elevation-2",
    }
)

FOUNDATION_TOKENS: Final[dict[str, str]] = {
    "space-1": "4px",
    "space-2": "8px",
    "space-3": "12px",
    "space-4": "16px",
    "space-6": "24px",
    "space-8": "32px",
    "space-12": "48px",
    "radius-control": "8px",
    "radius-card": "12px",
    "radius-panel": "16px",
    "radius-overlay": "20px",
    "type-meta": "12px",
    "type-label": "13px",
    "type-body": "16px",
    "type-section": "18px",
    "type-title": "24px",
    "control-default": "40px",
    "control-touch": "44px",
    "motion-fast": "120ms",
    "motion-default": "180ms",
    "motion-panel": "240ms",
    "ease-standard": "cubic-bezier(0.2, 0.8, 0.2, 1)",
    # Semantic aliases → brand tokens (resolved at CSS level via var())
    "surface": "var(--bg-panel)",
    "surface-card": "var(--bg-card)",
    "text": "var(--ink)",
    "text-muted": "var(--muted)",
    "border": "var(--line)",
    "focus-ring-color": "var(--accent-outline)",
    "status-ok": "#1e8449",
    # W10 AA: previous #b9770e was ~3.7:1 on white for normal text.
    "status-warn": "#92600a",
    "status-error": "#a93226",
    "status-info": "#1a5276",
    "ssr-accent-readable": "#1f6a9a",
    "ssr-accent-readable-hover": "#2e6da4",
    "elevation-1": "0 4px 12px rgba(0, 0, 0, 0.08)",
    "elevation-2": "0 12px 32px rgba(0, 0, 0, 0.12)",
}

# Spatial-dark (Mnemonopolis hall) — maps to --kgx-* names used in the 3D template.
SPATIAL_DARK_TOKENS: Final[dict[str, str]] = {
    "surface": "#0e101b",
    "surface-2": "#151728",
    "text": "#faf9ff",
    "text-muted": "#aeb5cf",
    "border": "rgba(223, 229, 255, 0.15)",
    "accent": "#42e8e0",
    "accent-2": "#9a6cff",
    "status-ok": "#72f1a5",
    "status-warn": "#ffc857",
    "status-error": "#ff6b8a",
    "night": "#080812",
}

UI_MODES: Final[tuple[str, ...]] = ("light", "spatial-dark")
# "dark" is a candidate only — not enabled until FULL_DARK_DECISION == "approved"
PORTAL_SELECTORS: Final[tuple[str, ...]] = (
    'div[data-baseweb="popover"]',
    'div[data-baseweb="select"]',
    'div[data-baseweb="modal"]',
    'div[data-baseweb="tooltip"]',
    'ul[role="listbox"]',
)


def foundation_css_block() -> str:
    """Render foundation ``:root`` declarations (without wrapping braces)."""
    lines = [f"    --{k}: {v};" for k, v in FOUNDATION_TOKENS.items()]
    return "\n".join(lines)


def is_world_theme_token(key: str) -> bool:
    """True if key belongs to brand worlds, not global foundation."""
    if key.startswith("font-"):
        return False
    return key not in FOUNDATION_TOKEN_KEYS


__all__ = [
    "FOUNDATION_TOKEN_KEYS",
    "FOUNDATION_TOKENS",
    "FULL_DARK_DECISION",
    "FULL_DARK_RATIONALE",
    "PORTAL_SELECTORS",
    "SPATIAL_DARK_TOKENS",
    "UI_MODES",
    "foundation_css_block",
    "is_world_theme_token",
]
