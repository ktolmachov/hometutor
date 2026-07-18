"""Мнемополис «Хранитель» — prompt stubs (W3a).

Source-of-truth texts for Keeper scenarios. Runtime must import from here
(or ``app.prompts``), never hardcode prose in routers/UI.

W3a ships stubs only; W3b/W3c wire generation. Tone: respectful, never shaming.
"""

from __future__ import annotations

# Fail-closed copy when LLM is unavailable / budget exhausted (vision §6.2).
KEEPER_SILENT_COPY = "Хранитель молчит — данные на месте."

# Scenario ids (stable contract for cache keys + callers).
SCENARIO_GUIDE = "guide"  # A — экскурсовод
SCENARIO_THREATS = "threats"  # B — сводка угроз
SCENARIO_QUEST = "quest"  # D — квестмейстер
SCENARIO_VOICES = "voices"  # H — голоса антагонистов

KEEPER_SCENARIOS = frozenset(
    {
        SCENARIO_GUIDE,
        SCENARIO_THREATS,
        SCENARIO_QUEST,
        SCENARIO_VOICES,
    }
)

# --- System prompts (short; inputs are compact labels only, not raw corpus) ---

GUIDE_SYSTEM = """Ты — Хранитель Мнемополиса, экскурсовод Memory Run.
Дано: список остановок дня (название + короткая причина worth).
Задача: для каждой остановки 1–2 уважительных предложения на русском.
Не стыди ученика. Не выдумывай факты вне списка. Не предлагай монеты/XP/магазин.
Формат: по одной строке на остановку «N. <имя>: <текст>»."""

THREATS_SYSTEM = """Ты — Хранитель памяти. Дан детерминированный список угроз
(концепт, % забывания, due-карточки). Сформулируй краткую сводку 2–4 предложения
на русском: что повторить и зачем. Тон уважительный, без стыда.
Не меняй числа. Не добавляй угрозы, которых нет в списке."""

QUEST_SYSTEM = """Ты — квестмейстер Memory Run. Дано: N остановок и фокус дня.
Одна строка цели утра (≤160 символов), уважительно, без новой валюты."""

VOICES_SYSTEM = """Ты пишешь короткие реплики антагонистов Мнемополиса (Туман/Призрак/Разлом).
По 1 строке на угрозу. Уважительный юмор. Никогда не стыди («ты забыл/слабый» — запрещено).
Пример тона Тумана: «Я подожду. Я всегда жду.»"""

# Static degrade banks (no LLM) — honest placeholders until W3b/W3c polish.

STATIC_VOICES = (
    "Туман: «Я подожду. Я всегда жду.»",
    "Призрак: «Кажется, ты уверен… проверим?»",
    "Разлом: «Здесь не хватает опоры — можно перепрыгнуть.»",
)


def build_guide_user_prompt(*, stops: list[dict[str, str]]) -> str:
    """Compact user payload for scenario A (labels + worth_reason only)."""
    lines = []
    for i, s in enumerate(stops, start=1):
        name = str(s.get("label") or s.get("id") or f"stop-{i}").strip()
        reason = str(s.get("worth_reason") or "").strip()
        if reason:
            lines.append(f"{i}. {name} — {reason}")
        else:
            lines.append(f"{i}. {name}")
    return "Остановки маршрута дня:\n" + "\n".join(lines)


def build_threats_user_prompt(*, threats: list[dict[str, object]]) -> str:
    """Compact user payload for scenario B (deterministic threat rows)."""
    lines = []
    for t in threats:
        name = str(t.get("label") or t.get("id") or "?").strip()
        forget_pct = t.get("forget_pct")
        due = t.get("due")
        bits = [name]
        if forget_pct is not None:
            bits.append(f"забывание ~{forget_pct}%")
        if due is not None:
            bits.append(f"due={due}")
        lines.append(" · ".join(bits))
    return "Угрозы (детерминированный список):\n" + "\n".join(lines)


def static_guide_text(*, stops: list[dict[str, str]]) -> str:
    """Degrade for A: worth_reason lines already on the card."""
    if not stops:
        return KEEPER_SILENT_COPY
    parts = []
    for i, s in enumerate(stops, start=1):
        name = str(s.get("label") or s.get("id") or f"stop-{i}").strip()
        reason = str(s.get("worth_reason") or "в маршруте дня").strip()
        parts.append(f"{i}. {name}: {reason}")
    return "\n".join(parts)


def static_threats_text(*, threats: list[dict[str, object]]) -> str:
    """Degrade for B: list without prose."""
    if not threats:
        return "Явных угроз забывания в снимке нет."
    lines = ["Сводка без Хранителя (детерминированно):"]
    for t in threats:
        name = str(t.get("label") or t.get("id") or "?").strip()
        forget_pct = t.get("forget_pct")
        due = t.get("due")
        extra = []
        if forget_pct is not None:
            extra.append(f"~{forget_pct}%")
        if due is not None:
            extra.append(f"due {due}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"• {name}{suffix}")
    lines.append("Повтор (🔁) развеет туман — без спешки.")
    return "\n".join(lines)


def static_quest_text(
    *,
    stop_count: int,
    focus: str = "",
    done_count: int = 0,
) -> str:
    """Degrade for D: honest «N из M» (+ optional focus). No currency / XP."""
    n = max(0, int(stop_count or 0))
    d = max(0, min(int(done_count or 0), n)) if n else 0
    if n <= 0:
        return "Маршрут дня пока пуст — Memory Run ждёт остановки."
    focus_bit = f" Фокус: {focus}." if str(focus or "").strip() else ""
    return f"Цель утра: {d} из {n}.{focus_bit}"


def static_voices_text() -> str:
    return "\n".join(STATIC_VOICES)
