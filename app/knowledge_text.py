"""Shared text/normalization helpers for knowledge catalog and synthesis."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def split_concepts(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    seen: set[str] = set()
    concepts: list[str] = []
    for item in raw_value.split(","):
        normalized = item.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        concepts.append(normalized)
    return concepts


def normalize_topic_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None


def tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.lower() for item in _TOKEN_RE.findall(value) if len(item) >= 3}


# RU+EN стоп-лист для token-overlap скоринга: голый tokenize() режет только по длине
# (>=3 символа), союзы/предлоги типа "как"/"для"/"the"/"and" проходят и искажают скор
# (используется в app/section_index.py::best_section_for; кандидат для будущего
# переиспользования в app/knowledge_synthesis.py::_score_chunk_for_synthesis).
STOPWORDS_RU: set[str] = {
    "или", "как", "что", "это", "эта", "этот", "эти", "тот", "которая", "который",
    "которое", "которые", "для", "при", "без", "чтобы", "если", "когда", "где", "кто",
    "есть", "быть", "был", "была", "было", "были", "всё", "все", "весь", "вся", "только",
    "ещё", "уже", "очень", "более", "менее", "самый", "самая", "самое", "самые", "себя",
    "свой", "своя", "своё", "свои", "они", "она", "оно", "мы", "вы", "наш", "ваш", "их",
    "его", "её", "там", "тут", "здесь", "туда", "сюда", "потому", "поэтому", "чем",
    "либо", "также", "тоже", "между", "после", "через", "из-за", "про", "над", "под",
    "перед",
}
STOPWORDS_EN: set[str] = {
    "the", "and", "for", "with", "are", "was", "were", "this", "that", "these", "those",
    "its", "from", "into", "than", "then", "but", "not", "such", "can", "will", "would",
    "should", "could", "has", "have", "had", "does", "did", "you", "your", "our", "they",
    "their", "he", "she", "his", "her", "when", "where", "which", "who", "whom", "what",
    "how", "why", "about", "there", "here",
}
STOPWORDS: set[str] = STOPWORDS_RU | STOPWORDS_EN


def tokenize_filtered(value: str | None) -> set[str]:
    """``tokenize()`` минус RU+EN стоп-слова — для token-overlap скоринга."""
    return {tok for tok in tokenize(value) if tok not in STOPWORDS}
