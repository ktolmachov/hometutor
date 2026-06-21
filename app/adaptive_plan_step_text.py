"""Тексты и классификаторы блоков Adaptive Daily Plan (без Streamlit).

Вынесено из adaptive_plan_card для переиспользования SSR-слоем без UI-зависимостей.
"""
from __future__ import annotations

from typing import Any

PLACEHOLDER_CONCEPT_SLUGS = frozenset({"general", "auto", "qa", "neutral"})

FALLBACK_CONCEPT_LINE_RU = (
    "без отдельной названной темы — в чате выберете, о чём займётесь"
)

BLOCK_TYPE_LABEL_RU = {
    "review": "Повторение",
    "gap": "Мини-практика",
    "new": "Новая тема",
    "motivation": "Мотивация",
    "auto_loop": "Auto-loop",
}

BLOCK_TYPE_BADGE = {
    "review": "REVIEW",
    "gap": "GAP",
    "new": "NEW",
    "motivation": "FOCUS",
    "auto_loop": "LOOP",
}


def is_placeholder_plan_concept(raw: str | None) -> bool:
    s = str(raw or "").strip().lower()
    return (not s) or s in PLACEHOLDER_CONCEPT_SLUGS


def plan_block_concept_line(block: dict[str, Any]) -> str:
    c = str(block.get("concept") or "").strip()
    if is_placeholder_plan_concept(c):
        return FALLBACK_CONCEPT_LINE_RU
    if c:
        return c
    return str(block.get("description") or "").strip()


def build_plan_step_reason(block: dict[str, Any]) -> str:
    bt = str(block.get("type") or "").strip()
    c_raw = str(block.get("concept") or "").strip()
    c_ok = None if is_placeholder_plan_concept(c_raw) else c_raw
    if bt == "review" and c_ok:
        return (
            f"Приоритет сейчас: вернуть в активную память «{c_ok}» по расписанию spaced repetition."
        )
    if bt == "review" and not c_ok:
        return (
            "Пора немного повторить — можно начать в чате: тему подстроим под твои вопросы и базу."
        )
    if bt == "gap" and c_ok:
        return (
            f"Сейчас полезно чуть позаниматься «{c_ok}», чтобы дальше было спокойнее и понятнее."
        )
    if bt == "gap" and not c_ok:
        return (
            "Система советует короткую практику. На старте это нормально: название темы появится, "
            "когда поработаешь с материалами или спросишь тьютора."
        )
    if bt == "new" and c_ok:
        return (
            f"Лучший следующий шаг: открыть новую тему «{c_ok}» и привязать её к уже знакомому контексту."
        )
    if bt == "new" and not c_ok:
        return (
            "Хороший момент открыть что-то новое из базы — выберем маленький первый шаг в диалоге с тьютором."
        )
    if bt == "motivation":
        return "Сначала короткий разогрев, чтобы войти в темп без перегруза."
    desc = str(block.get("description") or "").strip()
    return desc[:220] if desc else "Следующий шаг уже подготовлен в плане на сегодня."


def block_badge_label(block: dict[str, Any]) -> str:
    bt = str(block.get("type") or "").strip()
    return BLOCK_TYPE_BADGE.get(bt, (bt or "step").upper())
