"""Local-first web-search link builder for «Живой конспект».

Pure URL construction — **никаких сетевых вызовов**. Приложение остаётся
local-first: пользователь получает готовые ссылки на поисковики и сам решает,
переходить ли в сеть для проверки актуальности/источников.
"""

from __future__ import annotations

from urllib.parse import quote_plus

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
