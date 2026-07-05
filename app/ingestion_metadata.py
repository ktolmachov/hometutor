from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.llm_resilience import complete_with_resilience
from app.logging_config import setup_logging
from app.prompts import INGESTION_ENRICH_PROMPT, INGESTION_SUMMARY_PROMPT
from app.provider import get_ingestion_llm
from app.rag_runtime_preferences import effective_settings
from app.usage_cost import estimate_cost_usd, extract_token_usage

logger = setup_logging()


@dataclass
class DocumentMetadataEnrichment:
    topic: str | None = None
    key_concepts: list[str] = field(default_factory=list)
    doc_type: str | None = None
    difficulty: str | None = None


@dataclass
class LLMCallCost:
    model: str | None = None
    token_usage: dict[str, int] | None = None
    estimated_cost_usd: float | None = None


def _safe_json_loads(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        preview = (raw or "")[:500]
        logger.warning(
            "Failed to parse enrichment JSON | preview=%r",
            preview,
            exc_info=True,
        )
        return None


def _complete_with_cost(prompt: str) -> tuple[Any, LLMCallCost]:
    llm = get_ingestion_llm(settings=effective_settings())
    response = complete_with_resilience(
        llm,
        prompt,
        stage="ingestion.metadata",
    )
    usage = extract_token_usage(response)
    model = getattr(llm, "model", None)
    return response, LLMCallCost(
        model=model,
        token_usage=usage,
        estimated_cost_usd=estimate_cost_usd(model, usage),
    )


def enrich_document_metadata_with_cost(text: str) -> tuple[DocumentMetadataEnrichment | None, LLMCallCost | None]:
    """Вызвать LLM для извлечения семантических metadata по полному тексту документа."""
    snippet = text[:8000]
    if not snippet.strip():
        return None, None

    prompt = INGESTION_ENRICH_PROMPT.format(text=snippet)

    try:
        response, call_cost = _complete_with_cost(prompt)
        raw = getattr(response, "text", None) or str(response)
        data = _safe_json_loads(raw)
        if not data:
            return None, call_cost
        return (
            DocumentMetadataEnrichment(
                topic=data.get("topic"),
                key_concepts=list(data.get("key_concepts") or []),
                doc_type=data.get("doc_type"),
                difficulty=data.get("difficulty"),
            ),
            call_cost,
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.warning("Document metadata enrichment failed", exc_info=True)
        return None, None


def enrich_document_metadata(text: str) -> DocumentMetadataEnrichment | None:
    enrichment, _ = enrich_document_metadata_with_cost(text)
    return enrichment


def build_document_summary_with_cost(text: str) -> tuple[str | None, LLMCallCost | None]:
    """Сделать короткое summary для всего документа через LLM."""
    snippet = text[:8000]
    if not snippet.strip():
        return None, None

    prompt = INGESTION_SUMMARY_PROMPT.format(text=snippet)
    try:
        response, call_cost = _complete_with_cost(prompt)
        summary = getattr(response, "text", None) or str(response)
        return summary.strip() or None, call_cost
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.warning("Document summary generation failed", exc_info=True)
        return None, None


def build_document_summary(text: str) -> str | None:
    summary, _ = build_document_summary_with_cost(text)
    return summary

