"""Shared rating-button constants for the flashcard review loop.

Split out of ``app.ui.flashcards_review_view`` so the interactive-card iframe
builder (:mod:`app.ui.flashcards_interactive_card`) can share the same labels/
colours without importing the review view (which itself imports the card
builder) — that would form an import cycle. No UI dependency here: this module
is plain data.
"""

from __future__ import annotations

# label, q_label, SM-2 quality, colour.
RATING_BUTTONS = [
    ("🔴 Снова", "again", 0, "#c0392b"),
    ("🟡 Трудно", "hard", 3, "#d68910"),
    ("🟢 Хорошо", "good", 4, "#1e8449"),
    ("⭐ Легко", "easy", 5, "#1a5276"),
]

# Self-assessment meaning shown above each rating button — the recall judgement
# the learner is making, which the bare label ("Трудно") does not convey.
RATING_MEANINGS = {
    "again": "не вспомнил",
    "hard": "с трудом",
    "good": "вспомнил",
    "easy": "сразу",
}
