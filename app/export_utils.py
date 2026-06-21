"""Shared export helpers (Anki APKG) used by services and UI without backend→UI imports."""

from __future__ import annotations

import csv
import json
import os
import random
import tempfile
from io import StringIO


def anki_field_safe(text: str, *, preserve_newlines: bool = False) -> str:
    t = str(text or "").replace("\t", " ")
    if preserve_newlines:
        t = t.replace("\r\n", "\n").replace("\r", "\n")
    else:
        t = t.replace("\r", " ").replace("\n", " ")
    return t.strip()


def format_interactive_quiz_correct_for_export(q: dict) -> str:
    c = q.get("correct")
    if isinstance(c, list):
        return json.dumps(c, ensure_ascii=False)
    return str(c)


def interactive_quiz_back_text(q: dict, *, for_apkg: bool) -> str:
    expl = (q.get("explanation") or "").strip()
    qt = (q.get("type") or "").strip()
    sep = "\n\n" if for_apkg else "\n"
    back = f"{expl}{sep}Тип: {qt}\nПравильный ответ: {format_interactive_quiz_correct_for_export(q)}"
    if q.get("concept"):
        back += f"\nКонцепт: {q['concept']}"
    return back


def interactive_quiz_csv_bytes(quiz: dict) -> bytes:
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["Front", "Back"])
    for q in quiz.get("questions", []):
        front = (q.get("q") or "").strip()
        w.writerow([front, interactive_quiz_back_text(q, for_apkg=False)])
    return buf.getvalue().encode("utf-8-sig")


def interactive_quiz_apkg_bytes(quiz: dict) -> tuple[bytes | None, str | None]:
    title = (quiz.get("quiz_title") or "Quiz")[:100]
    pairs = [
        ((q.get("q") or "").strip(), interactive_quiz_back_text(q, for_apkg=True))
        for q in quiz.get("questions", [])
    ]
    return anki_apkg_from_pairs(
        title,
        pairs,
        model_name="Home RAG Quiz",
        preserve_field_newlines=True,
    )


def anki_apkg_from_pairs(
    title: str,
    pairs: list[tuple[str, str]],
    *,
    model_name: str = "Home RAG Study Deck",
    preserve_field_newlines: bool = False,
) -> tuple[bytes | None, str | None]:
    try:
        import genanki
    except ImportError:
        return None, "Установите genanki: pip install genanki"

    safe_title = (title or "Study Deck").strip()[:100] or "Study Deck"
    rng = random.Random(hash((safe_title, len(pairs))) & 0xFFFFFFFF)
    deck_id = rng.randint(1 << 30, (1 << 31) - 1)
    model_id = rng.randint(1 << 30, (1 << 31) - 1)
    model = genanki.Model(
        model_id,
        model_name,
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": '{{Front}}<hr id="answer">{{Back}}',
            }
        ],
    )
    deck = genanki.Deck(deck_id, safe_title)
    for front, back in pairs:
        f = anki_field_safe(front, preserve_newlines=preserve_field_newlines)
        b = anki_field_safe(back, preserve_newlines=preserve_field_newlines)
        if f and b:
            deck.add_note(genanki.Note(model=model, fields=[f, b]))
    fd, path = tempfile.mkstemp(suffix=".apkg")
    os.close(fd)
    try:
        genanki.Package(deck).write_to_file(path)
        with open(path, "rb") as fh:
            return fh.read(), None
    except Exception as e:
        return None, str(e)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


__all__ = [
    "anki_apkg_from_pairs",
    "anki_field_safe",
    "format_interactive_quiz_correct_for_export",
    "interactive_quiz_apkg_bytes",
    "interactive_quiz_back_text",
    "interactive_quiz_csv_bytes",
]
