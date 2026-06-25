"""Learner-facing tag presentation for the flashcard review face.

Cards carry two kinds of tags in one comma-separated string:

* **human topic tags** — ``llm``, ``stateless``, ``архитектура`` — written by the
  card author / generator and meaningful to the learner.
* **internal scope tags** — ``course:<id>``, ``folder:<rel>``, ``source:<path>`` —
  appended by :func:`app.flashcard_service._course_card_tags` so the review queue
  can be filtered by deck/course/source. They are infrastructure, not content.

Dumping the scope tags onto the card face (as the legacy review view did) is noise:
a learner sees ``course:bf00fdd2145b, folder:ии агенты, source:ии агенты/урок_3…md``
mixed in with real topic tags. These helpers split the two groups, surface only a
clean source filename, and HTML-escape everything for safe rendering.
"""

from __future__ import annotations

import html

# Tag namespaces that are plumbing for the review queue, not learner content.
SYSTEM_TAG_PREFIXES = ("course:", "folder:", "source:", "deck:")


def split_card_tags(raw: str | None) -> tuple[list[str], list[str]]:
    """Split a comma-separated tag string into ``(human_tags, system_tags)``.

    Order is preserved and case-insensitive duplicates are dropped. A tag is
    "system" when it starts with one of :data:`SYSTEM_TAG_PREFIXES`.
    """
    human: list[str] = []
    system: list[str] = []
    seen: set[str] = set()
    for part in str(raw or "").split(","):
        tag = part.strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        if any(key.startswith(prefix) for prefix in SYSTEM_TAG_PREFIXES):
            system.append(tag)
        else:
            human.append(tag)
    return human, system


def source_label(system_tags: list[str]) -> str | None:
    """Human-readable source filename from a ``source:`` tag, if any.

    ``source:ии агенты/урок_3_…_поведения.md`` → ``урок_3_…_поведения.md``. Returns
    ``None`` when no usable ``source:`` tag is present.
    """
    for tag in system_tags:
        if tag.lower().startswith("source:"):
            raw = tag.split(":", 1)[1].strip()
            if not raw:
                return None
            tail = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
            return tail or raw
    return None


def escape_multiline(text: str | None) -> str:
    """HTML-escape ``text`` and turn newlines into ``<br>`` for card faces.

    Card ``front``/``back`` come from the LLM (or user uploads) and were
    previously injected raw into ``unsafe_allow_html`` markup — a ``<`` in the
    content would break the layout. This escapes the content and preserves the
    paragraph breaks generated cards rely on (e.g. "Правильный ответ:…\\n\\n…").
    """
    escaped = html.escape(str(text or ""))
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def render_card_tags_html(raw: str | None) -> str:
    """Markup for the card-face tag row: human tags as chips + a muted source.

    Returns ``""`` when there is nothing learner-facing to show, so the caller
    can drop the row entirely.
    """
    human, system = split_card_tags(raw)
    chips = "".join(
        f'<span class="fc-tag-chip">{html.escape(tag)}</span>' for tag in human
    )
    chips_html = f'<div class="fc-tag-chips">{chips}</div>' if chips else ""
    src = source_label(system)
    src_html = f'<div class="fc-tag-source">📄 {html.escape(src)}</div>' if src else ""
    if not chips_html and not src_html:
        return ""
    return f'<div class="fc-card-tags">{chips_html}{src_html}</div>'
