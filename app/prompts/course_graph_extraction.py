"""Prompts for course graph LLM extraction (plan §5.2 vocabulary)."""

from __future__ import annotations

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.core.prompts import ChatPromptTemplate

RELATION_VOCABULARY = (
    "prerequisite",
    "uses",
    "extends",
    "contrasts",
    "part_of",
    "precedes",
    "related",
)

COURSE_GRAPH_EXTRACTION_SYSTEM = """\
You extract normalized concepts and typed relations from a single course document.
Return ONLY valid JSON matching the schema below. No markdown fences, no commentary.

Schema:
{
  "concepts": [
    {
      "label": "display label",
      "normalized_label": "canonical English or transliterated label",
      "aliases": ["optional alias"],
      "description": "one sentence",
      "source_doc_id": "doc id from input",
      "source_chunk_id": "chunk id from input"
    }
  ],
  "relations": [
    {
      "source": "normalized_label of source concept",
      "target": "normalized_label of target concept",
      "type": "one of: prerequisite, uses, extends, contrasts, part_of, precedes, related",
      "evidence_doc_id": "doc id",
      "evidence_chunk_id": "chunk id",
      "confidence": 0.0-1.0
    }
  ]
}

Rules:
- Extract domain concepts, not filenames or lesson titles alone.
- Use relation vocabulary exactly; never invent new types.
- precedes is curriculum order only — do not use it as prerequisite.
- Every concept and relation must cite evidence_doc_id and evidence_chunk_id from the input chunks.
- Prefer multiple specific concepts per document when the text supports them.
- If output would be truncated, return fewer items but keep valid JSON."""

COURSE_GRAPH_EXTRACTION_USER = """\
Document id: {doc_id}
Relative path: {relative_path}
Title: {title}

Chunks (JSON array):
{chunks_json}

Extract concepts and relations for this document only."""


def build_course_graph_extraction_prompt(
    *,
    doc_id: str,
    relative_path: str,
    title: str,
    chunks_json: str,
) -> ChatPromptTemplate:
    return ChatPromptTemplate(
        message_templates=[
            ChatMessage(role=MessageRole.SYSTEM, content=COURSE_GRAPH_EXTRACTION_SYSTEM),
            ChatMessage(
                role=MessageRole.USER,
                content=COURSE_GRAPH_EXTRACTION_USER.format(
                    doc_id=doc_id,
                    relative_path=relative_path,
                    title=title,
                    chunks_json=chunks_json,
                ),
            ),
        ]
    )


def is_truncated_llm_response(finish_reason: str | None, raw_text: str) -> bool:
    """Kill switch: truncated JSON / finish_reason=length blocks publication."""
    reason = str(finish_reason or "").strip().lower()
    if reason in {"length", "max_tokens"}:
        return True
    text = str(raw_text or "").strip()
    if not text:
        return True
    if not text.endswith("}"):
        return True
    return False
