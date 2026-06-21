from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any
import re
import hashlib

from app.user_state_core import *

def parse_flashcard_tags(tags: str | None) -> list[str]:
    """Return canonical tag tokens from the free-form TEXT column."""
    if not tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _FLASHCARD_TAG_SEPARATORS_RE.split(str(tags)):
        tag = " ".join(part.strip().split()).casefold()
        if tag and tag not in seen:
            out.append(tag)
            seen.add(tag)
    return out


def normalize_flashcard_tags(tags: str | None) -> str | None:
    parsed = parse_flashcard_tags(tags)
    return ", ".join(parsed) if parsed else None


def _flashcard_matches_tags(card_tags: str | None, requested_tags: set[str]) -> bool:
    if not requested_tags:
        return True
    return bool(set(parse_flashcard_tags(card_tags)) & requested_tags)


def create_flashcard_deck(
    name: str,
    source_type: str = "document",
    source_id: str | None = None,
) -> int:
    """Insert a new deck and return its id."""
    now = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO flashcard_decks(name, source_type, source_id, card_count, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (name, source_type, source_id, now, now),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    return _with_db(_work, write=True)


def save_flashcards_to_deck(deck_id: int, cards: list[dict[str, Any]]) -> int:
    """Insert cards into a deck, update card_count. Returns count inserted."""
    now = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> int:
        for card in cards:
            conn.execute(
                """
                INSERT INTO flashcards(deck_id, front, back, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    deck_id,
                    card.get("front", ""),
                    card.get("back", ""),
                    normalize_flashcard_tags(card.get("tags")),
                    now,
                    now,
                ),
            )
        n = len(cards)
        conn.execute(
            "UPDATE flashcard_decks SET card_count = card_count + ?, updated_at = ? WHERE id = ?",
            (n, now, deck_id),
        )
        conn.commit()
        return n

    return _with_db(_work, write=True)


def list_flashcard_decks() -> list[dict[str, Any]]:
    """Return all decks with live due_count."""

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT d.id, d.name, d.source_type, d.source_id, d.card_count, d.created_at, d.updated_at,
                   COUNT(CASE WHEN f.next_review IS NULL OR datetime(f.next_review) <= datetime('now') THEN 1 END) AS due_count
            FROM flashcard_decks d
            LEFT JOIN flashcards f ON f.deck_id = d.id
            GROUP BY d.id
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_db(_work)


def get_flashcard_deck(deck_id: int) -> dict[str, Any] | None:
    """Return deck row with all its cards."""

    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)
        ).fetchone()
        if not row:
            return None
        deck = dict(row)
        cards = conn.execute(
            "SELECT * FROM flashcards WHERE deck_id = ? ORDER BY id", (deck_id,)
        ).fetchall()
        deck["cards"] = [dict(c) for c in cards]
        return deck

    return _with_db(_work)


def delete_flashcard_deck(deck_id: int) -> bool:
    def _work(conn: sqlite3.Connection) -> bool:
        cur = conn.execute("DELETE FROM flashcard_decks WHERE id = ?", (deck_id,))
        conn.commit()
        return cur.rowcount > 0

    return _with_db(_work, write=True)


def get_due_flashcards(
    limit: int = 50,
    *,
    deck_id: int | None = None,
    tags: str | None = None,
) -> list[dict[str, Any]]:
    """Cards with next_review IS NULL (new) or <= now(), ordered by next_review ASC."""
    requested_tags = set(parse_flashcard_tags(tags))

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        where = ["(f.next_review IS NULL OR datetime(f.next_review) <= datetime('now'))"]
        params: list[Any] = []
        if deck_id is not None:
            where.append("f.deck_id = ?")
            params.append(deck_id)
        sql = f"""
            SELECT f.*, d.name AS deck_name, d.source_type AS deck_source_type, d.source_id AS deck_source_id
            FROM flashcards f
            JOIN flashcard_decks d ON d.id = f.deck_id
            WHERE {" AND ".join(where)}
            ORDER BY f.next_review ASC NULLS LAST
        """
        if not requested_tags:
            sql += "\n            LIMIT ?"
            params.append(limit)
        rows = conn.execute(
            sql,
            params,
        ).fetchall()
        cards = [dict(r) for r in rows]
        if requested_tags:
            cards = [
                card
                for card in cards
                if _flashcard_matches_tags(card.get("tags"), requested_tags)
            ][:limit]
        return cards

    return _with_db(_work)


def count_due_flashcards(
    *,
    deck_id: int | None = None,
    tags: str | None = None,
) -> int:
    requested_tags = set(parse_flashcard_tags(tags))

    def _work(conn: sqlite3.Connection) -> int:
        where = ["(next_review IS NULL OR datetime(next_review) <= datetime('now'))"]
        params: list[Any] = []
        if deck_id is not None:
            where.append("deck_id = ?")
            params.append(deck_id)
        if requested_tags:
            # Tags stored as "tag1, tag2"; normalize separators then match with LIKE.
            # (',' || REPLACE(tags, ', ', ',') || ',') LIKE '%,tagN,%' avoids false positives.
            tag_clauses = [
                "(',' || COALESCE(REPLACE(tags, ', ', ','), '') || ',') LIKE ?"
                for _ in requested_tags
            ]
            where.append(f"({' OR '.join(tag_clauses)})")
            params.extend(f"%,{t},%" for t in requested_tags)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM flashcards WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
        return int(row["n"]) if row else 0

    return _with_db(_work)


def get_flashcard_schedule_summary(
    *,
    deck_id: int | None = None,
    tags: str | None = None,
) -> dict[str, Any]:
    """Return the nearest future review date and safely undoable recovery count."""
    requested_tags = set(parse_flashcard_tags(tags))

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        where = ["datetime(next_review) > datetime('now')"]
        params: list[Any] = []
        if deck_id is not None:
            where.append("deck_id = ?")
            params.append(deck_id)
        rows = conn.execute(
            f"SELECT * FROM flashcards WHERE {' AND '.join(where)} ORDER BY next_review ASC",
            params,
        ).fetchall()
        cards = [dict(row) for row in rows]
        if requested_tags:
            cards = [card for card in cards if _flashcard_matches_tags(card.get("tags"), requested_tags)]
        if not cards:
            return {"next_review": None, "next_count": 0, "undoable_count": 0}

        next_review = str(cards[0]["next_review"])
        next_date = next_review[:10]
        return {
            "next_review": next_review,
            "next_count": sum(1 for card in cards if str(card.get("next_review"))[:10] == next_date),
            "undoable_count": sum(
                1
                for card in cards
                if int(card.get("repetitions") or 0) == 0
                and int(card.get("interval_days") or 0) == 0
                and not card.get("last_review")
            ),
        }

    return _with_db(_work)


def undo_pristine_flashcard_recovery(
    *,
    deck_id: int | None = None,
    tags: str | None = None,
) -> int:
    """Restore future, never-reviewed cards deferred by the recovery action."""
    requested_tags = set(parse_flashcard_tags(tags))

    def _work(conn: sqlite3.Connection) -> int:
        where = [
            "datetime(next_review) > datetime('now')",
            "COALESCE(repetitions, 0) = 0",
            "COALESCE(interval_days, 0) = 0",
            "last_review IS NULL",
        ]
        params: list[Any] = []
        if deck_id is not None:
            where.append("deck_id = ?")
            params.append(deck_id)
        rows = conn.execute(
            f"SELECT id, tags FROM flashcards WHERE {' AND '.join(where)}",
            params,
        ).fetchall()
        card_ids = [
            int(row["id"])
            for row in rows
            if not requested_tags or _flashcard_matches_tags(row["tags"], requested_tags)
        ]
        if not card_ids:
            return 0
        placeholders = ", ".join("?" for _ in card_ids)
        cur = conn.execute(
            f"UPDATE flashcards SET next_review = NULL, updated_at = ? WHERE id IN ({placeholders})",
            (_utc_now_iso(), *card_ids),
        )
        conn.commit()
        return cur.rowcount or 0

    return _with_db(_work, write=True)


def defer_due_flashcards_for_recovery(
    *,
    keep_limit: int = 7,
    stagger_days: int = 5,
    deck_id: int | None = None,
    tags: str | None = None,
) -> int:
    """Keep first ``keep_limit`` due cards; shift ``next_review`` for the rest (E26-A, US-7.2 parity).

    Ordering matches :func:`get_due_flashcards` (priority queue). Cards that remain in the
    tail receive staggered future ``next_review`` dates; SM-2 fields are unchanged.
    """
    keep_limit = max(1, min(int(keep_limit), 50))
    stagger_days = max(1, min(int(stagger_days), 14))

    due = get_due_flashcards(500, deck_id=deck_id, tags=tags)
    if len(due) <= keep_limit:
        return 0

    rest = due[keep_limit:]
    now = datetime.now(tz=timezone.utc)
    now_iso = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> int:
        entries = [
            (int(card["id"]), (now + timedelta(days=1 + (i % stagger_days))).isoformat())
            for i, card in enumerate(rest)
        ]
        case_sql = " ".join("WHEN ? THEN ?" for _ in entries)
        placeholders = ", ".join("?" for _ in entries)
        case_params: list[Any] = []
        for card_id, next_iso in entries:
            case_params.extend([card_id, next_iso])
        id_params = [card_id for card_id, _ in entries]
        cur = conn.execute(
            f"""
            UPDATE flashcards
            SET next_review = CASE id {case_sql} END,
                updated_at = ?
            WHERE id IN ({placeholders})
              AND (next_review IS NULL OR datetime(next_review) <= datetime('now'))
            """,
            (*case_params, now_iso, *id_params),
        )
        conn.commit()
        return cur.rowcount or 0

    return _with_db(_work, write=True)


def get_flashcard_progress_stats() -> dict[str, int]:
    """Сводка для Progress tab: всего карточек, «освоено» (interval > 21 дня), due сейчас."""

    def _work(conn: sqlite3.Connection) -> dict[str, int]:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN interval_days > ? THEN 1 ELSE 0 END), 0) AS mastered,
                COALESCE(
                    SUM(CASE WHEN next_review IS NULL OR datetime(next_review) <= datetime('now') THEN 1 ELSE 0 END),
                    0
                ) AS due
            FROM flashcards
            """,
            (FLASHCARD_MASTERED_INTERVAL_DAYS,),
        ).fetchone()
        if not row:
            return {"total": 0, "mastered": 0, "due": 0}
        return {
            "total": int(row["total"] or 0),
            "mastered": int(row["mastered"] or 0),
            "due": int(row["due"] or 0),
        }

    return _with_db(_work)


def get_flashcard_deck_progress(deck_id: int) -> dict[str, float | int]:
    """Return mastered/total/percent for one deck."""

    def _work(conn: sqlite3.Connection) -> dict[str, float | int]:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN interval_days > ? THEN 1 ELSE 0 END), 0) AS mastered
            FROM flashcards
            WHERE deck_id = ?
            """,
            (FLASHCARD_MASTERED_INTERVAL_DAYS, deck_id),
        ).fetchone()
        total = int(row["total"] or 0) if row else 0
        mastered = int(row["mastered"] or 0) if row else 0
        percent = round((mastered / total) * 100, 2) if total else 0.0
        return {"deck_id": deck_id, "mastered": mastered, "total": total, "percent": percent}

    return _with_db(_work)


def update_flashcard_sr(
    card_id: int,
    easiness: float,
    interval_days: int,
    repetitions: int,
    next_review: str,
    last_review: str,
) -> None:
    now = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE flashcards
            SET easiness = ?, interval_days = ?, repetitions = ?,
                next_review = ?, last_review = ?, updated_at = ?
            WHERE id = ?
            """,
            (easiness, interval_days, repetitions, next_review, last_review, now, card_id),
        )
        conn.commit()

    _with_db(_work, write=True)


def update_flashcard(card_id: int, front: str | None, back: str | None, tags: str | None) -> bool:
    now = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return False
        new_front = front if front is not None else row["front"]
        new_back = back if back is not None else row["back"]
        new_tags = normalize_flashcard_tags(tags) if tags is not None else row["tags"]
        conn.execute(
            "UPDATE flashcards SET front = ?, back = ?, tags = ?, updated_at = ? WHERE id = ?",
            (new_front, new_back, new_tags, now, card_id),
        )
        conn.commit()
        return True

    return _with_db(_work, write=True)


def add_flashcard(deck_id: int, front: str, back: str, tags: str | None = None) -> int:
    now = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO flashcards(deck_id, front, back, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (deck_id, front, back, normalize_flashcard_tags(tags), now, now),
        )
        conn.execute(
            "UPDATE flashcard_decks SET card_count = card_count + 1, updated_at = ? WHERE id = ?",
            (now, deck_id),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    return _with_db(_work, write=True)


def delete_flashcard(card_id: int) -> bool:
    now = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT deck_id FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return False
        deck_id = row["deck_id"]
        conn.execute("DELETE FROM flashcards WHERE id = ?", (card_id,))
        conn.execute(
            "UPDATE flashcard_decks SET card_count = MAX(0, card_count - 1), updated_at = ? WHERE id = ?",
            (now, deck_id),
        )
        conn.commit()
        return True

    return _with_db(_work, write=True)


def get_flashcard_by_id(card_id: int) -> dict[str, Any] | None:
    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (card_id,)).fetchone()
        return dict(row) if row else None

    return _with_db(_work)

