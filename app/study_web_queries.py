"""Local-first web-search link builder for «Живой конспект».

Pure URL construction — **никаких сетевых вызовов**. Приложение остаётся
local-first: пользователь получает готовые ссылки на поисковики и сам решает,
переходить ли в сеть для проверки актуальности/источников.

Плюс «источник этих знаний» без сети: :func:`harvest_links_from_rows` достаёт
markdown-ссылки, которые лектор сам приложил к материалу (тексты собранных
разделов + раздел-роль ``external_links`` их конспектов).
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import quote_plus

from app.knowledge_text import tokenize_filtered, tokenize_filtered_ordered

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

_ENGINES: tuple[tuple[str, str], ...] = (
    ("Google", "https://www.google.com/search?q={query}"),
    ("Google Scholar", "https://scholar.google.com/scholar?q={query}"),
    ("arXiv", "https://arxiv.org/search/?searchtype=all&query={query}"),
    ("Perplexity", "https://www.perplexity.ai/search?q={query}"),
    ("YouTube", "https://www.youtube.com/results?search_query={query}"),
)


def build_query_terms(
    *,
    heading_texts: list[str] | None = None,
    key_concepts: list[str] | None = None,
) -> str:
    """Собрать одну поисковую строку из заголовков разделов + key_concepts (дедуп, порядок сохранён)."""
    terms: list[str] = []
    seen: set[str] = set()
    for value in [*(heading_texts or []), *(key_concepts or [])]:
        cleaned = " ".join(str(value or "").split()).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        terms.append(cleaned)
    return " ".join(terms)


def build_web_search_links(query: str) -> list[tuple[str, str]]:
    """Вернуть ``[(label, url), ...]`` для готовых поисковых запросов по всем движкам."""
    cleaned = " ".join(str(query or "").split()).strip()
    if not cleaned:
        return []
    encoded = quote_plus(cleaned)
    return [(label, template.format(query=encoded)) for label, template in _ENGINES]


def build_query_from_rows(
    rows: list[Mapping[str, Any]],
    *,
    max_heading_terms: int = 5,
) -> str:
    """Короткий осмысленный запрос из rows корзины: концепты + топ-N токенов заголовков.

    Свалка ВСЕХ заголовков при 5+ разделах давала запрос на ~30 слов, по которому
    поисковики не находят ничего осмысленного. Токены заголовков ранжируются по частоте
    (стоп-слова уже срезаны ``tokenize_filtered``), токены, повторяющие концепты, не дублируются.
    """
    concepts: list[str] = []
    seen_concepts: set[str] = set()
    for row in rows:
        concept = " ".join(str(row.get("concept") or "").split()).strip()
        key = concept.lower()
        if concept and key not in seen_concepts:
            seen_concepts.add(key)
            concepts.append(concept)

    # Ordered-токенизация: порядок появления в заголовках — детерминированный тай-брейк
    # (set-итерация нестабильна между запусками, а query виден пользователю).
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for row in rows:
        for token in tokenize_filtered_ordered(str(row.get("heading_text") or "")):
            counts[token] = counts.get(token, 0) + 1
            order.setdefault(token, len(order))

    concept_tokens = tokenize_filtered(" ".join(concepts))
    top_tokens = [
        token
        for token in sorted(counts, key=lambda t: (-counts[t], order[t]))
        if token not in concept_tokens
    ][:max_heading_terms]

    return " ".join([*concepts, *top_tokens])


def harvest_links_from_rows(rows: list[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Markdown-ссылки лектора: из текстов собранных разделов + из ``external_links``-секции
    их конспектов («🌐 Дополнительные материалы…»). Дедуп по URL, порядок сохранён.

    Вход — rows корзины (не голые ``ParsedSection``): для чтения конспекта нужен
    провенанс ``konspekt_md_abs``. Недоступный/удалённый файл молча пропускается.
    """
    texts = [str(row.get("text") or "") for row in rows]

    md_paths: list[str] = []
    for row in rows:
        md = str(row.get("konspekt_md_abs") or "")
        if md and md not in md_paths:
            md_paths.append(md)
    if md_paths:
        try:
            # Lazy: section_index тянет ingestion-стек (llama-index) — не грузим его,
            # пока в корзине нет разделов с провенансом.
            from pathlib import Path

            from app.section_index import _cached_parse_sections, sections_by_role

            for md in md_paths:
                try:
                    parsed = _cached_parse_sections(Path(md))
                except OSError:
                    continue
                external = sections_by_role(parsed).get("external_links")
                if external is not None:
                    texts.append(external.text)
        except Exception:  # noqa: BLE001 - harvest опционален, поисковики остаются
            pass

    links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for text in texts:
        for label, url in _MD_LINK_RE.findall(text):
            if url not in seen_urls:
                seen_urls.add(url)
                links.append((" ".join(label.split()).strip(), url))
    return links
