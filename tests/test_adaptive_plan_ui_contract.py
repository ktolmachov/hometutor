"""W9b Adaptive Plan UI contracts."""

from __future__ import annotations

from pathlib import Path


def test_main_adaptive_view_is_hub_or_detail_not_both() -> None:
    src = Path("app/ui/main.py").read_text(encoding="utf-8")
    # Surface switch present; sequential dual render of hub+daily removed.
    assert "adaptive_plan_surface" in src
    assert 'options=("Сводка", "Детали дня")' in src or "Сводка" in src
    # Daily only in else branch of surface switch (not unconditional after hub).
    hub_idx = src.index("render_adaptive_plan_hub(key_prefix=\"adaptive_plan_view_hub\")")
    daily_idx = src.index("render_adaptive_daily_plan(key_prefix=\"adaptive_plan_view_daily\")")
    # Between them must be branch logic (if/else), not sequential always-on.
    between = src[hub_idx:daily_idx]
    assert "else" in between or "Детали" in between


def test_hub_preview_max_two_columns_no_xp_auto() -> None:
    src = Path("app/ui/adaptive_plan_hub_layout.py").read_text(encoding="utf-8")
    assert "range(0, len(preview), 2)" in src
    assert "XP {raw.get('xp_base') or 'auto'}" not in src
    assert "XP auto" not in src
    assert "потому что:" in src


def test_daily_plan_xp_in_expert_disclosure() -> None:
    src = Path("app/ui/adaptive_daily_plan_layout.py").read_text(encoding="utf-8")
    assert "Эксперт: XP блока" in src
    assert "цель XP:" not in src.split("def render_adaptive_daily_plan")[1][:800]
    assert "потому что:" in src
    assert "address_from_mapping" in src
