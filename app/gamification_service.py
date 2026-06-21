"""
Геймификация (P1): XP, уровни, ежедневный стрик, quiz-стрик, бейджи.
Хранение: одна JSON-запись в ``app_kv`` (без отдельного класса UserState).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.user_state import get_kv, set_kv

logger = logging.getLogger(__name__)

_KV_KEY = "gamification_state_v1"

BADGE_DEFS: list[tuple[str, str, str]] = [
    ("streak_7", "🔥 7-дневный стрик", "7 дней активности подряд"),
    ("docs_10", "📚 10 документов", "≥10 материалов с прогрессом ≥85%"),
    ("quiz_streak_3", "🎯 Три quiz подряд", "3 успешных quiz подряд (≥70%)"),
    ("xp_1000", "⭐ 1000 XP", "Набрано ≥1000 очков опыта"),
    ("daily_plan_master", "📅 Daily Plan Master", "≥5 блоков Adaptive Daily Plan за день"),
    ("concept_graduation", "🎓 Тема освоена", "Мастеринг концепта (ceremony / ≥80%)"),
]

CONCEPT_GRADUATION_BADGE_ID = "concept_graduation"


def _today_utc() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "total_xp": 0,
        "daily_streak": 0,
        "last_activity_date": "",
        "quiz_streak": 0,
        "badges": [],
        "daily_xp_today": 0,
        "gamification_daily_date": "",
        "blocks_completed_today": 0,
        "last_block_completed_iso": "",
        "adp_completed_keys": [],
        "xp_daily_history": {},
    }


def _load_state() -> dict[str, Any]:
    raw = get_kv(_KV_KEY)
    if not raw:
        return _default_state()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    out = _default_state()
    out.update(data)
    out["badges"] = list(out.get("badges") or [])
    _ensure_daily_counters(out)
    return out


def _ensure_daily_counters(state: dict[str, Any]) -> None:
    """Сброс дневных счётчиков XP / блоков плана при смене UTC-даты."""
    today = _today_utc()
    prev = str(state.get("gamification_daily_date") or "")
    if prev == today:
        return
    hist = state.setdefault("xp_daily_history", {})
    if not isinstance(hist, dict):
        hist = {}
        state["xp_daily_history"] = hist
    if prev:
        hist[prev] = int(state.get("daily_xp_today") or 0)
    state["gamification_daily_date"] = today
    state["daily_xp_today"] = 0
    state["blocks_completed_today"] = 0
    state["adp_completed_keys"] = []


def _prune_xp_history(hist: dict[str, Any], *, keep: int = 45) -> None:
    if len(hist) <= keep:
        return
    keys = sorted(hist.keys())[-keep:]
    drop = [k for k in hist if k not in keys]
    for k in drop:
        del hist[k]


def _snapshot_xp_daily(state: dict[str, Any]) -> None:
    """Записать сегодняшний накопленный daily XP в историю (для графика)."""
    hist = state.setdefault("xp_daily_history", {})
    if not isinstance(hist, dict):
        return
    hist[_today_utc()] = int(state.get("daily_xp_today") or 0)
    _prune_xp_history(hist)


def _save_state(state: dict[str, Any]) -> None:
    try:
        set_kv(_KV_KEY, json.dumps(state, ensure_ascii=False))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.exception("gamification save failed")


def level_from_total_xp(total_xp: int) -> int:
    """Уровень 1+; пороги по 1000 XP."""
    xp = max(0, int(total_xp))
    return min(99, xp // 1000 + 1)


def level_title(level: int) -> str:
    lv = max(1, min(99, int(level)))
    if lv <= 2:
        return "Newbie"
    if lv <= 5:
        return "Apprentice"
    if lv <= 10:
        return "Scholar"
    if lv <= 20:
        return "Expert"
    return "Master"


def xp_progress_in_level(total_xp: int) -> tuple[int, int, int]:
    """Текущий XP в уровне, ширина полосы, номер уровня."""
    xp = max(0, int(total_xp))
    lv = level_from_total_xp(xp)
    floor = (lv - 1) * 1000
    ceiling = lv * 1000
    cur = xp - floor
    width = max(1, ceiling - floor)
    return cur, width, lv


def _count_mastered_reading_rows() -> int:
    from app.user_state import count_reading_at_least_progress

    try:
        return int(count_reading_at_least_progress(0.85))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("count_reading_at_least_progress failed", exc_info=True)
        return 0


def _update_daily_streak(state: dict[str, Any]) -> None:
    today = _today_utc()
    last = (state.get("last_activity_date") or "").strip()
    if not last:
        state["daily_streak"] = 1
        state["last_activity_date"] = today
        return
    try:
        last_d = datetime.fromisoformat(last).date()
        today_d = datetime.fromisoformat(today).date()
    except ValueError:
        state["daily_streak"] = 1
        state["last_activity_date"] = today
        return
    if last_d == today_d:
        return
    if last_d == today_d - timedelta(days=1):
        state["daily_streak"] = int(state.get("daily_streak") or 0) + 1
    else:
        state["daily_streak"] = 1
    state["last_activity_date"] = today


def _badge_label(badge_id: str) -> str:
    for bid, lab, _ in BADGE_DEFS:
        if bid == badge_id:
            return lab
    return badge_id


def _unlock_badges(state: dict[str, Any], unlocked_before: set[str]) -> list[dict[str, str]]:
    new: list[dict[str, str]] = []
    have = set(state.get("badges") or [])
    mastered_docs = _count_mastered_reading_rows()
    total_xp = int(state.get("total_xp") or 0)
    ds = int(state.get("daily_streak") or 0)
    qs = int(state.get("quiz_streak") or 0)

    blocks_today = int(state.get("blocks_completed_today") or 0)
    checks: list[tuple[str, bool]] = [
        ("streak_7", ds >= 7),
        ("docs_10", mastered_docs >= 10),
        ("quiz_streak_3", qs >= 3),
        ("xp_1000", total_xp >= 1000),
        ("daily_plan_master", blocks_today >= 5),
    ]
    for bid, ok in checks:
        if ok and bid not in have and bid not in unlocked_before:
            new.append({"id": bid, "label": _badge_label(bid)})
            have.add(bid)
    state["badges"] = sorted(have)
    return new


def record_concept_graduation_badge() -> dict[str, Any]:
    """Сохраняет бейдж выпуска концепта через KV-слой gamification."""
    state = _load_state()
    have = set(state.get("badges") or [])
    if CONCEPT_GRADUATION_BADGE_ID in have:
        return {"new_badges": [], "badges_all": sorted(have)}
    have.add(CONCEPT_GRADUATION_BADGE_ID)
    state["badges"] = sorted(have)
    _save_state(state)
    lab = _badge_label(CONCEPT_GRADUATION_BADGE_ID)
    return {
        "new_badges": [{"id": CONCEPT_GRADUATION_BADGE_ID, "label": lab}],
        "badges_all": list(state["badges"]),
    }


def record_quiz_activity(
    *,
    score_0_1: float,
    scope: str | None = None,
) -> dict[str, Any]:
    """
    Начислить XP и обновить стрики после quiz / micro-quiz / scoped.
    ``scope``: ``micro`` | ``topic`` | ``document`` | ``scoped`` | None.
    """
    state = _load_state()
    unlocked_before = set(state.get("badges") or [])
    _update_daily_streak(state)

    sc = float(score_0_1)
    sc = max(0.0, min(1.0, sc))
    base = int(round(sc * 35))
    if scope == "topic":
        bonus = 20
    elif scope in ("document", "scoped"):
        bonus = 15
    elif scope == "micro":
        bonus = 12
    else:
        bonus = 10
    xp_gain = max(5, min(95, base + bonus))

    prev_xp = int(state.get("total_xp") or 0)
    state["total_xp"] = prev_xp + xp_gain
    old_level = level_from_total_xp(prev_xp)
    new_level = level_from_total_xp(state["total_xp"])
    level_up = new_level > old_level

    if sc >= 0.7:
        state["quiz_streak"] = int(state.get("quiz_streak") or 0) + 1
    else:
        state["quiz_streak"] = 0

    state["daily_xp_today"] = int(state.get("daily_xp_today") or 0) + xp_gain
    _snapshot_xp_daily(state)

    badge_candidates = _unlock_badges(state, unlocked_before)
    _save_state(state)

    return {
        "xp_gained": xp_gain,
        "total_xp": int(state["total_xp"]),
        "level": new_level,
        "level_title": level_title(new_level),
        "level_up": level_up,
        "old_level": old_level,
        "daily_streak": int(state.get("daily_streak") or 0),
        "quiz_streak": int(state.get("quiz_streak") or 0),
        "new_badges": badge_candidates,
        "badges_all": list(state.get("badges") or []),
    }


_BASE_XP_BY_TYPE: dict[str, int] = {
    "review": 25,
    "gap": 40,
    "new": 35,
    "motivation": 15,
    "auto_loop": 10,
}


def _block_fingerprint(
    *,
    plan_date: str,
    block_index: int | None,
    block: dict[str, Any],
) -> str:
    bt = str(block.get("type") or "unknown")
    conc = str(block.get("concept") or "").strip()
    if block_index is not None and int(block_index) == -1 and bt == "auto_loop":
        return f"{plan_date}:auto_loop:-1"
    bi = str(block_index) if block_index is not None else "x"
    return f"{plan_date}:{bi}:{bt}:{conc}"


def get_streak(user_id: str | None = None) -> int:
    _ = user_id
    return int(_load_state().get("daily_streak") or 0)


def get_total_xp(user_id: str | None = None) -> int:
    _ = user_id
    return int(_load_state().get("total_xp") or 0)


def get_daily_xp(user_id: str | None = None) -> int:
    _ = user_id
    return int(_load_state().get("daily_xp_today") or 0)


def get_xp_history(user_id: str | None = None, *, days: int = 7) -> list[dict[str, Any]]:
    """
    XP по дням (UTC) за последние ``days`` дней для графика.
    Сегодняшнее значение берётся из ``daily_xp_today`` (живое).
    """
    _ = user_id
    state = _load_state()
    hist_raw = state.get("xp_daily_history")
    hist: dict[str, Any] = hist_raw if isinstance(hist_raw, dict) else {}
    today_d = datetime.now(timezone.utc).date()
    out: list[dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        d = (today_d - timedelta(days=i)).isoformat()
        xp = int(hist.get(d, 0))
        if d == today_d.isoformat():
            xp = int(state.get("daily_xp_today") or 0)
        out.append({"date": d, "xp": xp})
    return out


def get_streak_message(streak: int) -> str:
    s = int(streak)
    if s <= 0:
        return ""
    return f"Стрик {s} дн."


def award_xp_for_block(
    user_id: str,
    block: dict[str, Any],
    *,
    completion_time_min: int | None = None,
    block_index: int | None = None,
    plan_date: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Начислить XP за блок Adaptive Daily Plan (KV ``gamification_state_v1``).

    Множители: emotional recovery (motivation при frustrated/bored), velocity >0.15,
    mastery gap (current_mastery <0.5), streak, быстрое завершение (<70% от duration_min).
    """
    state = _load_state()
    unlocked_before = set(state.get("badges") or [])
    _ensure_daily_counters(state)

    uid = (user_id or "").strip() or "local"
    bt = str(block.get("type") or "").strip()
    if not bt:
        return {"ok": False, "error": "empty_block_type", "xp_earned": 0, "message": "Нет типа блока."}

    pdate = (plan_date or "").strip() or _today_utc()
    fp = _block_fingerprint(plan_date=pdate, block_index=block_index, block=block)
    done = list(state.get("adp_completed_keys") or [])
    if fp in done:
        return {
            "ok": True,
            "already_awarded": True,
            "xp_earned": 0,
            "multiplier": 1.0,
            "message": "Этот блок уже засчитан сегодня.",
        }

    raw_base = block.get("xp_base")
    try:
        base = int(raw_base) if raw_base is not None else _BASE_XP_BY_TYPE.get(bt, 20)
    except (TypeError, ValueError):
        base = _BASE_XP_BY_TYPE.get(bt, 20)

    from app.learner_model_service import get_personalized_learner_profile

    profile = get_personalized_learner_profile(uid, session_id=session_id)
    mult = 1.0
    parts: list[str] = []

    es = str(profile.emotional_state)
    if es in ("frustrated", "bored") and bt == "motivation":
        mult *= 1.2
        parts.append("emotional recovery +20%")

    if float(profile.learning_velocity) > 0.15:
        mult *= 1.5
        parts.append("velocity ×1.5")

    cm_raw = block.get("current_mastery")
    if cm_raw is not None:
        try:
            cm = float(cm_raw)
            if cm < 0.5:
                mult *= 2.0
                parts.append("mastery gap ×2")
        except (TypeError, ValueError):
            pass

    streak = int(state.get("daily_streak") or 0)
    streak_mult = 1.0 + streak * 0.05
    mult *= streak_mult
    if streak > 0:
        parts.append(f"streak ×{streak_mult:.2f}")

    dur = int(block.get("duration_min") or 10)
    if completion_time_min is not None and dur > 0:
        try:
            if float(completion_time_min) < float(dur) * 0.7:
                mult *= 1.25
                parts.append("fast ×1.25")
        except (TypeError, ValueError):
            pass

    xp_earned = max(1, int(round(base * mult)))

    prev_xp = int(state.get("total_xp") or 0)
    state["total_xp"] = prev_xp + xp_earned
    state["daily_xp_today"] = int(state.get("daily_xp_today") or 0) + xp_earned
    state["blocks_completed_today"] = int(state.get("blocks_completed_today") or 0) + 1
    state["last_block_completed_iso"] = datetime.now(timezone.utc).isoformat()
    done.append(fp)
    state["adp_completed_keys"] = done[-200:]

    _update_daily_streak(state)

    badge_candidates = _unlock_badges(state, unlocked_before)
    _snapshot_xp_daily(state)
    _save_state(state)

    mult_round = round(mult, 2)
    streak_msg = get_streak_message(int(state.get("daily_streak") or 0))
    msg = f"+{xp_earned} XP (×{mult_round})"
    if parts:
        msg += f" — {', '.join(parts)}"
    if streak_msg:
        msg += f" · {streak_msg}"

    return {
        "ok": True,
        "already_awarded": False,
        "xp_earned": xp_earned,
        "multiplier": mult_round,
        "multiplier_parts": parts,
        "new_total": int(state["total_xp"]),
        "daily_xp_today": int(state.get("daily_xp_today") or 0),
        "blocks_completed_today": int(state.get("blocks_completed_today") or 0),
        "new_badges": badge_candidates,
        "message": msg,
    }


def count_completed_plan_blocks(*, plan_date: str, blocks: list[Any]) -> int:
    """Сколько блоков текущего плана уже засчитаны сегодня по тем же fingerprint, что и XP."""
    pdate = str(plan_date or "").strip() or _today_utc()
    done = set(_load_state().get("adp_completed_keys") or [])
    count = 0
    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            continue
        fp = _block_fingerprint(plan_date=pdate, block_index=i, block=raw)
        if fp in done:
            count += 1
    return count


def get_snapshot() -> dict[str, Any]:
    """Сводка для UI / dashboard."""
    state = _load_state()
    tx = int(state.get("total_xp") or 0)
    cur, width, lv = xp_progress_in_level(tx)
    return {
        "total_xp": tx,
        "level": lv,
        "level_title": level_title(lv),
        "xp_in_level": cur,
        "xp_for_level_span": width,
        "daily_streak": int(state.get("daily_streak") or 0),
        "quiz_streak": int(state.get("quiz_streak") or 0),
        "badges": list(state.get("badges") or []),
        "mastered_documents_estimate": _count_mastered_reading_rows(),
        "daily_xp_today": int(state.get("daily_xp_today") or 0),
        "blocks_completed_today": int(state.get("blocks_completed_today") or 0),
    }


__all__ = [
    "BADGE_DEFS",
    "CONCEPT_GRADUATION_BADGE_ID",
    "award_xp_for_block",
    "count_completed_plan_blocks",
    "get_daily_xp",
    "get_snapshot",
    "get_streak",
    "get_streak_message",
    "get_total_xp",
    "get_xp_history",
    "level_from_total_xp",
    "level_title",
    "record_concept_graduation_badge",
    "record_quiz_activity",
    "xp_progress_in_level",
]
