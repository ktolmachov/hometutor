"""Zero-new-LLM flashcards from konspekt «Важные термины и концепции» (role ``terms``).

Локальный шаблон конспекта форматирует термины как ``- **Термин** — определение.``
(см. ``section_index.section_role``). Парсинг детерминированный: карточка = сохранённая
пара термин/определение из конспекта, без нового LLM-вызова на этапе создания колоды.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.section_index import _cached_parse_sections, sections_by_role

# Маркер списка (- или *) + **термин** + тире (—/–/-) + определение до конца строки.
_TERM_LINE_RE = re.compile(
    r"^[-*]\s*\*\*(?P<term>[^*]+?)\*\*\s*[—–-]\s*(?P<definition>.+)$",
    re.MULTILINE,
)


def source_tag_value(md: Path) -> str:
    """Значение для системного тега ``source:`` — относительный путь корпуса.

    Конвенция Flashcards (``_course_card_tags``, ``source_path_from_card``) — «relative
    path in the corpus»: относительный путь переживает перенос ``user_state.db`` на другую
    машину и смену ``HOME_RAG_HOME``; абсолютный — нет. Файл вне корпуса — фолбэк на
    абсолютный (лучше хрупкий провенанс, чем никакого).
    """
    try:
        from app.obsidian_export import corpus_root

        return md.resolve().relative_to(corpus_root().resolve()).as_posix()
    except Exception:  # noqa: BLE001 - вне корпуса / corpus_root недоступен
        return str(md)


def parse_term_cards(section_text: str) -> list[dict[str, str]]:
    """``[{front, back}, ...]`` из тела раздела-роли ``terms``.

    Дедуп по термину (casefold) ВНУТРИ одного раздела — сохраняет первое определение.
    """
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _TERM_LINE_RE.finditer(section_text):
        term = " ".join(match.group("term").split()).strip()
        definition = " ".join(match.group("definition").split()).strip()
        key = term.casefold()
        if not term or not definition or key in seen:
            continue
        seen.add(key)
        cards.append({"front": term, "back": definition})
    return cards


def term_cards_from_documents(md_paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Термины-карточки из раздела-роли ``terms`` каждого конспекта (по уникальным md-путям).

    Каждая карточка получает системный тег ``source:<path>`` (провенанс не теряется при сохранении
    колоды). Дедуп по термину МЕЖДУ документами — первое совпадение побеждает, чтобы фронт
    карточки (термин) оставался уникальным в колоде.

    Возвращает ``(cards, source_docs)`` — ``source_docs`` содержит только файлы, из которых
    реально удалось извлечь хотя бы одну карточку (для honest-подписи в UI).
    """
    cards: list[dict[str, Any]] = []
    source_docs: list[str] = []
    seen_terms: set[str] = set()
    for md in md_paths:
        try:
            parsed = _cached_parse_sections(Path(md))
        except OSError:
            continue
        terms_section = sections_by_role(parsed).get("terms")
        if terms_section is None:
            continue
        doc_name = Path(md).name
        source_tag = source_tag_value(Path(md))
        added_any = False
        for card in parse_term_cards(terms_section.text):
            key = card["front"].casefold()
            if key in seen_terms:
                continue
            seen_terms.add(key)
            cards.append({**card, "tags": f"source:{source_tag}"})
            added_any = True
        if added_any:
            source_docs.append(doc_name)
    return cards, source_docs
