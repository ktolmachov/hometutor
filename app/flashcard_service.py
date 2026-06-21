"""Flashcard generation, persistence and SM-2 review (E12)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.llm_resilience import complete_with_resilience
from app.logging_config import log_event
from app.request_cache import consume_llm_cache_hit, reset_llm_cache_hit_flag
from app.prompts import FLASHCARD_GENERATION_PROMPT, FLASHCARD_JSON_REPAIR_PROMPT
from app.quiz_service import get_quiz_llm_for_generation
from app.spaced_repetition import apply_sm2
from app.user_state import (
    add_flashcard,
    count_due_flashcards,
    create_flashcard_deck,
    defer_due_flashcards_for_recovery,
    delete_flashcard,
    delete_flashcard_deck,
    get_due_flashcards,
    get_flashcard_by_id,
    get_flashcard_deck,
    get_flashcard_deck_progress,
    get_flashcard_schedule_summary,
    get_kv,
    list_flashcard_decks,
    normalize_flashcard_tags,
    parse_flashcard_tags,
    save_flashcards_to_deck,
    record_flashcard_review_log,
    set_kv,
    update_flashcard,
    update_flashcard_sr,
    undo_pristine_flashcard_recovery,
)

logger = logging.getLogger(__name__)

_MAX_CONTEXT_CHARS = 14_000
_DEFAULT_NUM_CARDS = 12


def _record_flashcard_workflow_event(action: str, payload: dict[str, Any]) -> None:
    try:
        from app.metrics import record_knowledge_workflow_event

        record_knowledge_workflow_event(
            action=f"flashcards.{action}",
            knowledge_product_trace={"workflow_label": "flashcards"},
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 - metrics must not break generation.
        logger.debug("flashcard workflow metrics skipped: %s", exc)


def _median_ms(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 2)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# LLM generation
# ─────────────────────────────────────────────────────────────

def _parse_flashcard_json(raw: str) -> list[dict[str, str]]:
    """Extract and validate JSON array of {front, back, tags} from LLM response."""
    text = (raw or "").strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    # Find first '[' to handle any prefix text
    start = text.find("[")
    if start != -1:
        text = text[start:]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("flashcard JSON parse error: %s | raw=%r", exc, raw[:300])
        return []

    if not isinstance(data, list):
        return []

    cards: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        front = str(item.get("front") or "").strip()
        back = str(item.get("back") or "").strip()
        if not front or not back:
            continue
        cards.append({
            "front": front,
            "back": back,
            "tags": str(item.get("tags") or "").strip(),
        })
    return cards


def _e2e_offline_flashcards_enabled() -> bool:
    env_value = str(os.getenv("HOME_RAG_E2E_OFFLINE", "")).strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    from app.config import get_settings
    return get_settings().home_rag_e2e_offline


def _stub_flashcards_from_text(text: str, title: str, num_cards: int) -> list[dict[str, str]]:
    """Deterministic cards for Playwright e2e when no LLM key (HOME_RAG_E2E_OFFLINE)."""
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not lines:
        lines = ["(empty source)", "(no extractable lines)"]
    cards: list[dict[str, str]] = []
    for i in range(num_cards):
        line = lines[i % len(lines)]
        cards.append({
            "front": f"Вопрос {i + 1}: {line[:240]}",
            "back": f"Ответ {i + 1} (e2e): {line[:240]}",
            "tags": "e2e-offline",
        })
    return cards


def _stub_flashcards_from_source_path(source_path: str, num_cards: int) -> list[dict[str, str]]:
    """Deterministic offline fallback for missing course files in e2e."""
    base = source_path.strip() or "unknown-source"
    cards: list[dict[str, str]] = []
    for i in range(num_cards):
        cards.append(
            {
                "front": f"Вопрос {i + 1}: ключевая идея из {base}",
                "back": f"Ответ {i + 1} (e2e course): материал {base}",
                "tags": "e2e-offline",
            }
        )
    return cards


def generate_flashcards(
    *,
    scope: str,
    identifier: str | None = None,
    content: str | None = None,
    num_cards: int = _DEFAULT_NUM_CARDS,
) -> dict[str, Any]:
    """Generate flashcard preview (not persisted).

    scope='document' — identifier is relative_path in data/.
    scope='upload'   — content is pre-extracted text.

    Returns {"success": bool, "cards": [...], "deck_title": str, "error": str|None}
    """
    num_cards = max(5, min(20, int(num_cards)))

    # ── Resolve content ──
    title = identifier or "Документ"
    if scope == "document" and identifier:
        try:
            from app.explain_service import _read_file  # type: ignore[attr-defined]

            text = _read_file(identifier, max_chars=_MAX_CONTEXT_CHARS)
        except Exception as exc:  # noqa: BLE001 - content fetch returns a controlled error response.
            logger.warning("flashcard content fetch failed: %s", exc)
            return {"success": False, "cards": [], "deck_title": title, "error": str(exc)}
    elif scope == "upload" and content:
        text = content
    else:
        return {
            "success": False,
            "cards": [],
            "deck_title": title,
            "error": "scope must be 'document' (with identifier) or 'upload' (with content)",
        }

    trimmed = text[:_MAX_CONTEXT_CHARS]

    if _e2e_offline_flashcards_enabled():
        cards = _stub_flashcards_from_text(trimmed, title, num_cards)
        return {
            "success": True,
            "cards": cards,
            "deck_title": title,
            "error": None,
            "latency_ms": 0.0,
            "llm_cache_hit": False,
        }

    prompt = FLASHCARD_GENERATION_PROMPT.format(
        title=title,
        context_str=trimmed,
        num_cards=num_cards,
    )

    started = time.perf_counter()
    try:
        llm = get_quiz_llm_for_generation()
        reset_llm_cache_hit_flag()
        response = complete_with_resilience(
            llm,
            prompt,
            stage="flashcards.generate",
            temperature=0.3,
        )
        raw = getattr(response, "text", str(response))
    except Exception as exc:  # noqa: BLE001 - LLM failure returns a controlled error response.
        logger.error("flashcard LLM call failed: %s", exc)
        return {"success": False, "cards": [], "deck_title": title, "error": str(exc)}

    cards = _parse_flashcard_json(raw)
    if not cards:
        logger.info("flashcard_json_repair_started", extra={"stage": "flashcards.generate_json_repair"})
        repair_prompt = FLASHCARD_JSON_REPAIR_PROMPT.format(
            num_cards=num_cards,
            raw_response=raw[:20_000],
        )
        try:
            repaired_response = complete_with_resilience(
                llm,
                repair_prompt,
                stage="flashcards.generate_json_repair",
                temperature=0.0,
            )
            repaired_raw = getattr(repaired_response, "text", str(repaired_response))
            cards = _parse_flashcard_json(repaired_raw)
        except Exception as exc:  # noqa: BLE001 - bounded repair failure becomes a controlled generation error.
            logger.warning("flashcard JSON repair failed: %s", exc)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    llm_cache_hit = consume_llm_cache_hit()
    if not cards:
        return {
            "success": False,
            "cards": [],
            "deck_title": title,
            "error": "LLM returned invalid flashcard JSON after one repair attempt",
            "latency_ms": latency_ms,
            "llm_cache_hit": llm_cache_hit,
        }

    log_event(
        logger,
        logging.INFO,
        "flashcard_generate_doc_done",
        scope=scope,
        identifier=identifier,
        cards_count=len(cards),
        latency_ms=latency_ms,
        llm_cache_hit=llm_cache_hit,
    )
    _record_flashcard_workflow_event(
        "generate_doc_done",
        {
            "scope": scope,
            "identifier": identifier,
            "cards_count": len(cards),
            "latency_ms": latency_ms,
            "llm_cache_hit": llm_cache_hit,
        },
    )
    return {
        "success": True,
        "cards": cards,
        "deck_title": title,
        "error": None,
        "latency_ms": latency_ms,
        "llm_cache_hit": llm_cache_hit,
    }


def _course_card_tags(
    *,
    base_tags: str | None,
    course_id: str | None,
    folder_rel: str | None,
    source_path: str,
) -> str:
    tags = parse_flashcard_tags(base_tags)
    if course_id:
        tags.append(f"course:{course_id}")
    if folder_rel:
        tags.append(f"folder:{folder_rel}")
    tags.append(f"source:{source_path}")
    return ", ".join(dict.fromkeys(tags))


def _merge_course_document_cards(
    *,
    path: str,
    result: dict[str, Any],
    course_id: str | None,
    folder_rel: str | None,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for card in result.get("cards") or []:
        front = str(card.get("front") or "").strip()
        back = str(card.get("back") or "").strip()
        if not front or not back:
            continue
        merged.append(
            {
                "front": front,
                "back": back,
                "tags": _course_card_tags(
                    base_tags=card.get("tags"),
                    course_id=course_id,
                    folder_rel=folder_rel,
                    source_path=path,
                ),
            }
        )
    return merged


def _generate_course_document_result(path: str, *, per_doc: int) -> tuple[str, dict[str, Any]]:
    result = generate_flashcards(scope="document", identifier=path, num_cards=per_doc)
    if not result.get("success") and _e2e_offline_flashcards_enabled():
        result = {
            "success": True,
            "cards": _stub_flashcards_from_source_path(path, per_doc),
            "deck_title": path,
            "error": None,
            "latency_ms": 0.0,
            "llm_cache_hit": False,
        }
    return path, result


def generate_course_flashcards(
    *,
    source_paths: list[str],
    course_title: str,
    course_id: str | None = None,
    folder_rel: str | None = None,
    num_cards_per_document: int = 5,
) -> dict[str, Any]:
    """Generate one preview deck by batching over course documents."""
    paths = [str(path).strip() for path in source_paths if str(path).strip()]
    if not paths:
        return {
            "success": False,
            "cards": [],
            "deck_title": course_title or "Курс",
            "error": "source_paths required for scope=course",
        }

    per_doc = max(5, min(20, int(num_cards_per_document)))
    cards: list[dict[str, str]] = []
    errors: list[str] = []
    doc_latencies: list[float] = []
    cache_hits = 0
    docs_ok = 0
    started = time.perf_counter()
    workers = min(get_settings().flashcard_course_parallel_workers, len(paths))

    def _consume_doc(path: str, result: dict[str, Any], *, index: int) -> None:
        nonlocal docs_ok, cache_hits
        if not result.get("success"):
            errors.append(f"{path}: {result.get('error') or 'generation failed'}")
            log_event(
                logger,
                logging.WARNING,
                "flashcard_generate_doc_done",
                scope="course",
                identifier=path,
                doc_index=index,
                docs_total=len(paths),
                cards_count=0,
                latency_ms=result.get("latency_ms"),
                llm_cache_hit=bool(result.get("llm_cache_hit")),
                success=False,
            )
            return
        docs_ok += 1
        if result.get("llm_cache_hit"):
            cache_hits += 1
        latency = result.get("latency_ms")
        if isinstance(latency, (int, float)):
            doc_latencies.append(float(latency))
        doc_cards = _merge_course_document_cards(
            path=path,
            result=result,
            course_id=course_id,
            folder_rel=folder_rel,
        )
        cards.extend(doc_cards)
        log_event(
            logger,
            logging.INFO,
            "flashcard_generate_doc_done",
            scope="course",
            identifier=path,
            doc_index=index,
            docs_total=len(paths),
            cards_count=len(doc_cards),
            latency_ms=result.get("latency_ms"),
            llm_cache_hit=bool(result.get("llm_cache_hit")),
            success=True,
        )

    if workers <= 1:
        for index, path in enumerate(paths, start=1):
            _, result = _generate_course_document_result(path, per_doc=per_doc)
            _consume_doc(path, result, index=index)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_generate_course_document_result, path, per_doc=per_doc): (index, path)
                for index, path in enumerate(paths, start=1)
            }
            for future in as_completed(future_map):
                index, path = future_map[future]
                try:
                    resolved_path, result = future.result()
                except Exception as exc:  # noqa: BLE001 - one failed doc must not abort the batch.
                    errors.append(f"{path}: {exc}")
                    continue
                _consume_doc(resolved_path, result, index=index)

    total_latency_ms = round((time.perf_counter() - started) * 1000, 2)
    generation_stats = {
        "docs_total": len(paths),
        "docs_ok": docs_ok,
        "docs_failed": len(errors),
        "cards_total": len(cards),
        "latency_ms": total_latency_ms,
        "cache_hits": cache_hits,
        "p50_doc_latency_ms": _median_ms(doc_latencies),
        "parallel_workers": workers,
    }

    if not cards:
        _record_flashcard_workflow_event("generate_course_failed", generation_stats)
        return {
            "success": False,
            "cards": [],
            "deck_title": course_title or "Курс",
            "error": "; ".join(errors) if errors else "No valid cards generated",
            "source_paths": paths,
            "generation_stats": generation_stats,
        }

    log_event(
        logger,
        logging.INFO,
        "flashcard_generate_course_done",
        course_id=course_id,
        folder_rel=folder_rel,
        **generation_stats,
    )
    _record_flashcard_workflow_event("generate_course_done", generation_stats)
    return {
        "success": True,
        "cards": cards,
        "deck_title": course_title or "Курс",
        "error": None,
        "source_paths": paths,
        "generation_errors": errors,
        "generation_stats": generation_stats,
        "course_metadata": {
            "course_id": course_id,
            "folder_rel": folder_rel,
        },
    }


# ─────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────

def save_deck(
    name: str,
    source_type: str,
    source_identifier: str | None,
    cards: list[dict[str, str]],
) -> dict[str, Any]:
    """Persist a deck and its cards. Returns {deck_id, card_count}."""
    deck_id = create_flashcard_deck(name, source_type, source_identifier)
    count = save_flashcards_to_deck(deck_id, cards)
    return {"deck_id": deck_id, "card_count": count}


def cards_from_scoped_quiz_items(questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Map interactive quiz items to flashcard rows: front=вопрос, back=верный вариант + пояснение (US-15.6)."""
    out: list[dict[str, str]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qtext = str(q.get("question") or "").strip()
        if not qtext:
            continue
        opts = q.get("options") or []
        try:
            ok_idx = int(q.get("correct_index", 0))
        except (TypeError, ValueError):
            ok_idx = 0
        correct = ""
        if isinstance(opts, list) and 0 <= ok_idx < len(opts):
            correct = str(opts[ok_idx]).strip()
        expl = str(q.get("explanation") or "").strip()
        back_parts: list[str] = []
        if correct:
            back_parts.append(f"Правильный ответ: {correct}")
        if expl:
            back_parts.append(expl)
        back = "\n\n".join(back_parts) if back_parts else "—"
        out.append({
            "front": qtext[:2000],
            "back": back[:8000],
            "tags": "source:scoped-quiz",
        })
    return out


# ─────────────────────────────────────────────────────────────
# SM-2 review
# ─────────────────────────────────────────────────────────────

# UI quality mapping: "again"=0, "hard"=3, "good"=4, "easy"=5
QUALITY_MAP: dict[str, int] = {"again": 0, "hard": 3, "good": 4, "easy": 5}

_FLASHCARD_RATING_KV_KEY = "flashcard_expert_rating_history_v1"
_FLASHCARD_EXPERT_SETTINGS_KV_KEY = "flashcard_expert_settings_v1"
_MAX_RATINGS_PER_CARD = 10


def _parse_iso_utc(ts: str | None) -> datetime | None:
    if not ts or not str(ts).strip():
        return None
    raw = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_rating_kv() -> dict[str, list[dict[str, Any]]]:
    raw = get_kv(_FLASHCARD_RATING_KV_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_rating_kv(data: dict[str, list[dict[str, Any]]]) -> None:
    set_kv(_FLASHCARD_RATING_KV_KEY, json.dumps(data, ensure_ascii=False))


def append_flashcard_rating_history(card_id: int, entry: dict[str, Any]) -> None:
    """Append one review event for expert history (local app_kv, capped per card)."""
    key = str(int(card_id))
    data = _load_rating_kv()
    bucket = list(data.get(key) or [])
    bucket.append(entry)
    data[key] = bucket[-_MAX_RATINGS_PER_CARD:]
    _save_rating_kv(data)


def get_flashcard_rating_history(card_id: int, *, limit: int = 10) -> list[dict[str, Any]]:
    key = str(int(card_id))
    rows = list(_load_rating_kv().get(key) or [])
    if limit > 0:
        rows = rows[-limit:]
    return rows


def get_flashcard_expert_settings() -> dict[str, Any]:
    raw = get_kv(_FLASHCARD_EXPERT_SETTINGS_KV_KEY)
    if not raw:
        return {}
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def set_flashcard_expert_settings(partial: dict[str, Any]) -> None:
    cur = dict(get_flashcard_expert_settings())
    for k, v in (partial or {}).items():
        if v is None:
            cur.pop(str(k), None)
        else:
            cur[str(k)] = v
    set_kv(_FLASHCARD_EXPERT_SETTINGS_KV_KEY, json.dumps(cur, ensure_ascii=False))


def filter_due_cards_expert(
    cards: list[dict[str, Any]],
    *,
    interval_min: int | None = None,
    interval_max: int | None = None,
    ef_min: float | None = None,
    ef_max: float | None = None,
    overdue_only: bool = False,
) -> list[dict[str, Any]]:
    """Filter an in-memory due list for expert queue controls (no extra SQL)."""
    if interval_min is not None and interval_max is not None and interval_min > interval_max:
        interval_min, interval_max = interval_max, interval_min
    if ef_min is not None and ef_max is not None and ef_min > ef_max:
        ef_min, ef_max = ef_max, ef_min
    now = datetime.now(tz=timezone.utc)
    out: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        try:
            iv = int(card.get("interval_days") or 0)
        except (TypeError, ValueError):
            iv = 0
        try:
            ef = float(card.get("easiness") or card.get("ease_factor") or 2.5)
        except (TypeError, ValueError):
            ef = 2.5
        if interval_min is not None and iv < int(interval_min):
            continue
        if interval_max is not None and iv > int(interval_max):
            continue
        if ef_min is not None and ef < float(ef_min):
            continue
        if ef_max is not None and ef > float(ef_max):
            continue
        if overdue_only:
            nr = card.get("next_review")
            if nr is None or str(nr).strip() == "":
                pass  # new cards count as due/overdue bucket
            else:
                nrd = _parse_iso_utc(str(nr))
                if nrd is not None and nrd > now:
                    continue
        out.append(card)
    return out


def build_flashcards_session_audit_export(
    *,
    deck_label: str,
    scope_signature: str,
    events: list[dict[str, Any]],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Structured JSON for local expert inspection (session-scoped)."""
    return {
        "kind": "flashcards_review_session",
        "deck_label": deck_label,
        "scope_signature": scope_signature,
        "stats": dict(stats or {}),
        "events": list(events or []),
    }


def review_flashcard(card_id: int, quality: int) -> dict[str, Any]:
    """Apply SM-2 to a single card and persist. Returns updated state."""
    card = get_flashcard_by_id(card_id)
    if not card:
        return {"error": f"card {card_id} not found"}

    q = max(0, min(5, int(quality)))
    new_ef, new_interval, new_reps = apply_sm2(
        card["easiness"],
        card["interval_days"] if card["interval_days"] > 0 else 1,
        card["repetitions"],
        q,
    )

    from app.config import get_settings

    max_interval = getattr(get_settings(), "sr_max_interval_days", 3650)
    new_interval = min(new_interval, max_interval)

    settings = get_flashcard_expert_settings()
    if "min_easiness" in settings:
        try:
            floor_ef = float(settings["min_easiness"])
            if 1.3 <= floor_ef <= 5.0:
                new_ef = max(new_ef, floor_ef)
        except (TypeError, ValueError):
            pass

    last_review = _utc_now_iso()
    next_review = (
        datetime.now(tz=timezone.utc) + timedelta(days=new_interval)
    ).isoformat()

    update_flashcard_sr(card_id, new_ef, new_interval, new_reps, next_review, last_review)
    try:
        record_flashcard_review_log(
            card_id=card_id,
            deck_id=int(card["deck_id"]),
            quality=q,
            easiness_before=float(card["easiness"]),
            easiness_after=float(new_ef),
            interval_before=int(card["interval_days"] or 0),
            interval_after=int(new_interval),
            repetitions=int(new_reps),
            reviewed_at=last_review,
        )
    except Exception as exc:  # noqa: BLE001 - review state is already persisted
        logger.debug("flashcard_review_log insert failed: %s", exc)

    try:
        from app.user_state import increment_weekly_progress

        increment_weekly_progress("reviews", 1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("increment_weekly_progress(reviews) failed", exc_info=True)

    try:
        append_flashcard_rating_history(
            card_id,
            {
                "at": last_review,
                "quality": q,
                "interval_days": new_interval,
                "easiness": round(new_ef, 3),
                "next_review": next_review,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("flashcard expert rating history append failed: %s", exc)

    return {
        "card_id": card_id,
        "easiness": round(new_ef, 3),
        "interval_days": new_interval,
        "repetitions": new_reps,
        "next_review": next_review,
        "last_review": last_review,
    }


def defer_overdue_flashcards_for_recovery(
    *,
    keep_limit: int = 7,
    stagger_days: int = 5,
    deck_id: int | None = None,
    tags: str | None = None,
) -> int:
    """Spread the tail of the due queue across upcoming days (parity with SRS ``defer_overdue_reviews_for_recovery``)."""
    return defer_due_flashcards_for_recovery(
        keep_limit=keep_limit,
        stagger_days=stagger_days,
        deck_id=deck_id,
        tags=tags,
    )


def get_flashcard_recovery_schedule(
    *,
    deck_id: int | None = None,
    tags: str | None = None,
) -> dict[str, Any]:
    return get_flashcard_schedule_summary(deck_id=deck_id, tags=tags)


def undo_overdue_flashcards_recovery(
    *,
    deck_id: int | None = None,
    tags: str | None = None,
) -> int:
    return undo_pristine_flashcard_recovery(deck_id=deck_id, tags=tags)


# ─────────────────────────────────────────────────────────────
# Anki export
# ─────────────────────────────────────────────────────────────

def export_deck_to_anki(deck_id: int) -> tuple[bytes | None, str | None]:
    """Return (apkg_bytes, error_message)."""
    deck = get_flashcard_deck(deck_id)
    if not deck:
        return None, f"Deck {deck_id} not found"

    cards = deck.get("cards") or []
    if not cards:
        return None, "Deck has no cards"

    pairs: list[tuple[str, str]] = [(c["front"], c["back"]) for c in cards]

    from app.export_utils import anki_apkg_from_pairs

    apkg_bytes, error = anki_apkg_from_pairs(deck["name"], pairs)
    return apkg_bytes, error


# ─────────────────────────────────────────────────────────────
# Home mode UX hints (wave-home-mode-selection-v2)
# ─────────────────────────────────────────────────────────────

FLASHCARD_HOME_HINT_AVG_SECONDS_PER_CARD = 45
FLASHCARD_HOME_HINT_LARGE_DUE_THRESHOLD = 48


def estimate_flashcard_due_clear_minutes(due_n: int) -> int:
    """Грубая оценка минут на очередь due для подписи на главной (не SLA)."""
    n = int(due_n)
    if n <= 0:
        return 0
    total_sec = n * FLASHCARD_HOME_HINT_AVG_SECONDS_PER_CARD
    return max(1, (total_sec + 59) // 60)


def flashcard_home_effort_hint_lines(due_n: int) -> list[str]:
    """Строки под карточкой Flashcards: счётчик, время, no-due и recovery при большой очереди."""
    n = int(due_n)
    if n <= 0:
        return ["Сейчас нет карточек к повторению."]
    minutes = estimate_flashcard_due_clear_minutes(n)
    primary = f"К повторению: {n} · около {minutes} мин"
    if n >= FLASHCARD_HOME_HINT_LARGE_DUE_THRESHOLD:
        recovery = (
            "Большая очередь — лучше несколько коротких заходов; при необходимости "
            "воспользуйтесь восстановлением очереди во вкладке Flashcards."
        )
        return [primary, recovery]
    return [primary]


# ─────────────────────────────────────────────────────────────
# Re-exports for API layer convenience
# ─────────────────────────────────────────────────────────────

__all__ = [
    "generate_flashcards",
    "generate_course_flashcards",
    "save_deck",
    "cards_from_scoped_quiz_items",
    "review_flashcard",
    "defer_overdue_flashcards_for_recovery",
    "get_flashcard_recovery_schedule",
    "undo_overdue_flashcards_recovery",
    "export_deck_to_anki",
    "QUALITY_MAP",
    # user_state pass-throughs
    "list_flashcard_decks",
    "get_flashcard_deck",
    "get_flashcard_deck_progress",
    "delete_flashcard_deck",
    "get_due_flashcards",
    "count_due_flashcards",
    "estimate_flashcard_due_clear_minutes",
    "flashcard_home_effort_hint_lines",
    "FLASHCARD_HOME_HINT_AVG_SECONDS_PER_CARD",
    "FLASHCARD_HOME_HINT_LARGE_DUE_THRESHOLD",
    "parse_flashcard_tags",
    "normalize_flashcard_tags",
    "update_flashcard",
    "add_flashcard",
    "delete_flashcard",
]
