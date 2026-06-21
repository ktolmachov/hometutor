"""Multi-query expansion prompt (multi_query_expansion_v1)."""

from __future__ import annotations

from llama_index.core.base.llms.types import ChatMessage, MessageRole

PROMPT_ID = "multi_query_expansion_v1"

MULTI_QUERY_EXPANSION_SYSTEM = """\
You generate alternative search queries for a knowledge-base retrieval system.
Return ONLY valid JSON: a JSON array of 2–4 distinct query strings (plain strings).
No markdown fences, no commentary, no numbering prefix.

Rules:
- Each variant must be a standalone search query (not a full sentence answer).
- Preserve the user's intent; paraphrase with different vocabulary and angles.
- Do not repeat the anchor query verbatim.
- Prefer concise keyword-style phrases suitable for hybrid BM25+vector search."""

MULTI_QUERY_EXPANSION_USER = """\
Anchor query: {effective_query}

Generate {variant_count} alternative retrieval queries as a JSON string array."""


def build_multi_query_expansion_messages(
    *,
    effective_query: str,
    variant_count: int,
) -> list[ChatMessage]:
    """Build chat messages for multi-query expansion LLM call."""
    count = max(2, min(int(variant_count), 4))
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=MULTI_QUERY_EXPANSION_SYSTEM),
        ChatMessage(
            role=MessageRole.USER,
            content=MULTI_QUERY_EXPANSION_USER.format(
                effective_query=effective_query.strip(),
                variant_count=count,
            ),
        ),
    ]


def format_multi_query_expansion_prompt(*, effective_query: str, variant_count: int) -> str:
    """Flatten chat messages into a single prompt for ``complete_with_resilience``."""
    parts: list[str] = []
    for message in build_multi_query_expansion_messages(
        effective_query=effective_query,
        variant_count=variant_count,
    ):
        parts.append(str(message.content or "").strip())
    return "\n\n".join(part for part in parts if part)


def parse_multi_query_variants(raw_text: str, *, max_count: int) -> list[str]:
    """Parse JSON array or newline-separated variants; clamp to ``max_count``."""
    import json

    text = (raw_text or "").strip()
    if not text:
        return []

    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text.removeprefix(prefix).strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    variants: list[str] = []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                variants = [" ".join(str(item).split()).strip() for item in parsed]
        except json.JSONDecodeError:
            variants = []

    if not variants:
        variants = [
            " ".join(line.split()).strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("[")
        ]

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in variants:
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)

    return cleaned[: max(2, min(int(max_count), 4))]
