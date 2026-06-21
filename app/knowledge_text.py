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
