"""Color theme presets — single source of truth for all visual worlds."""
from __future__ import annotations

from typing import Final

VALID_UI_THEMES: Final[frozenset[str]] = frozenset({
    "forest",
    "ocean",
    "sunset",
    "cosmos",
    "berry",
})

THEME_META: Final[dict[str, dict[str, str]]] = {
    "forest": {"title_ru": "🌲 Лес", "description_ru": "Тёплая зелень и терракота — уют лесной опушки"},
    "ocean": {"title_ru": "🌊 Океан", "description_ru": "Прохладная бирюза и глубокий синий"},
    "sunset": {"title_ru": "🌅 Закат", "description_ru": "Тёплые розовые и золотые оттенки"},
    "cosmos": {"title_ru": "🚀 Космос", "description_ru": "Тёмные фиолетовые и звёздные тона"},
    "berry": {"title_ru": "🍇 Ягода", "description_ru": "Насыщенные красные и ягодные акценты"},
}

# Map of token name → CSS value for each world.
# Token names match the :root variables in ui_theme.css (without the "--" prefix).
# Each world MUST define ALL tokens — validated by tests.
THEME_TOKENS: Final[dict[str, dict[str, str]]] = {
    "forest": {
        "bg-panel": "rgba(255, 252, 246, 0.92)",
        "bg-card": "rgba(255, 255, 255, 0.9)",
        "ink": "#132019",
        "muted": "#59685f",
        "accent": "#b95631",
        "accent-dark": "#7d351f",
        "forest": "#243b2c",
        "line": "rgba(19, 32, 25, 0.12)",
        "shadow": "0 20px 48px rgba(49, 29, 15, 0.08)",
        "bg-app-1": "rgba(231, 177, 104, 0.18)",
        "bg-app-2": "rgba(86, 126, 89, 0.12)",
        "bg-app-3": "#f8f2e7",
        "bg-hero": "linear-gradient(135deg, rgba(34, 61, 44, 0.97), rgba(101, 56, 35, 0.95))",
        "head-continue": "#1b3224",
        "head-due": "#2e4a39",
        "head-fc": "#6b3820",
        "chip-bg": "rgba(185, 86, 49, 0.1)",
        "chip-border": "rgba(185, 86, 49, 0.14)",
    },
    "ocean": {
        "bg-panel": "rgba(240, 248, 252, 0.92)",
        "bg-card": "rgba(255, 255, 255, 0.9)",
        "ink": "#0d2b3e",
        "muted": "#4d6b7a",
        "accent": "#1a7a8c",
        "accent-dark": "#0f4f5c",
        "forest": "#1a4a5e",
        "line": "rgba(13, 43, 62, 0.12)",
        "shadow": "0 20px 48px rgba(13, 43, 62, 0.08)",
        "bg-app-1": "rgba(127, 199, 217, 0.15)",
        "bg-app-2": "rgba(58, 128, 148, 0.10)",
        "bg-app-3": "#e8f4f8",
        "bg-hero": "linear-gradient(135deg, rgba(15, 60, 80, 0.97), rgba(20, 100, 120, 0.90))",
        "head-continue": "#0f3c50",
        "head-due": "#1a6478",
        "head-fc": "#0f5060",
        "chip-bg": "rgba(26, 122, 140, 0.10)",
        "chip-border": "rgba(26, 122, 140, 0.14)",
    },
    "sunset": {
        "bg-panel": "rgba(255, 247, 240, 0.92)",
        "bg-card": "rgba(255, 255, 255, 0.9)",
        "ink": "#3a1e1a",
        "muted": "#7a5c52",
        "accent": "#c44a3a",
        "accent-dark": "#8a2e22",
        "forest": "#4a2a22",
        "line": "rgba(58, 30, 26, 0.12)",
        "shadow": "0 20px 48px rgba(58, 30, 26, 0.08)",
        "bg-app-1": "rgba(235, 150, 120, 0.18)",
        "bg-app-2": "rgba(220, 120, 80, 0.10)",
        "bg-app-3": "#fdf0ea",
        "bg-hero": "linear-gradient(135deg, rgba(80, 35, 25, 0.97), rgba(160, 70, 40, 0.90))",
        "head-continue": "#502319",
        "head-due": "#8a4028",
        "head-fc": "#c44a3a",
        "chip-bg": "rgba(196, 74, 58, 0.10)",
        "chip-border": "rgba(196, 74, 58, 0.14)",
    },
    "cosmos": {
        "bg-panel": "rgba(245, 240, 250, 0.92)",
        "bg-card": "rgba(255, 255, 255, 0.9)",
        "ink": "#1e1035",
        "muted": "#5a4a6a",
        "accent": "#7a3fa0",
        "accent-dark": "#4f2570",
        "forest": "#2e1a4a",
        "line": "rgba(30, 16, 53, 0.12)",
        "shadow": "0 20px 48px rgba(30, 16, 53, 0.08)",
        "bg-app-1": "rgba(150, 100, 200, 0.12)",
        "bg-app-2": "rgba(80, 40, 130, 0.08)",
        "bg-app-3": "#f0eaf8",
        "bg-hero": "linear-gradient(135deg, rgba(30, 10, 60, 0.97), rgba(80, 40, 130, 0.90))",
        "head-continue": "#1e0a3c",
        "head-due": "#3d1a60",
        "head-fc": "#7a3fa0",
        "chip-bg": "rgba(122, 63, 160, 0.10)",
        "chip-border": "rgba(122, 63, 160, 0.14)",
    },
    "berry": {
        "bg-panel": "rgba(255, 245, 245, 0.92)",
        "bg-card": "rgba(255, 255, 255, 0.9)",
        "ink": "#2a1018",
        "muted": "#6a4050",
        "accent": "#b8345a",
        "accent-dark": "#7a1e3a",
        "forest": "#3a1828",
        "line": "rgba(42, 16, 24, 0.12)",
        "shadow": "0 20px 48px rgba(42, 16, 24, 0.08)",
        "bg-app-1": "rgba(200, 80, 120, 0.12)",
        "bg-app-2": "rgba(160, 50, 80, 0.08)",
        "bg-app-3": "#f8eaee",
        "bg-hero": "linear-gradient(135deg, rgba(60, 15, 30, 0.97), rgba(140, 40, 70, 0.90))",
        "head-continue": "#3c0f1e",
        "head-due": "#6a2038",
        "head-fc": "#b8345a",
        "chip-bg": "rgba(184, 52, 90, 0.10)",
        "chip-border": "rgba(184, 52, 90, 0.14)",
    },
}


def css_vars_for_theme(theme_id: str) -> str:
    """Render ``:root { --key: value; ... }`` CSS block for a theme preset."""
    tokens = THEME_TOKENS.get(theme_id)
    if not tokens:
        return ""
    pairs = "\n".join(f"    --{k}: {v};" for k, v in tokens.items())
    return f":root {{\n{pairs}\n}}"


def get_theme_title(theme_id: str) -> str:
    return THEME_META.get(theme_id, {}).get("title_ru", theme_id)


def get_theme_description(theme_id: str) -> str:
    return THEME_META.get(theme_id, {}).get("description_ru", "")
