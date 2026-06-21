"""Post-generation grounded answer validation (ADR-025 proposed)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import get_settings
from app.guardrails import get_safe_fallback_message, is_abstain_phrase

AnswerStatus = Literal["grounded", "abstain", "guardrails_fallback"]

CITATION_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

HOMEWORK_RELAXED_ASSISTANCE_LEVELS = frozenset({"error_review", "full_solution"})
ABSTAIN_RATE_MAX_DELTA_PP = 10.0


class GroundedAnswerError(Exception):
    """Raised when strict grounded validation fails."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        validation_errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.validation_errors = list(validation_errors or [])


class CitationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cite_index: int
    relative_path: str | None = None
    provenance_type: Literal["source", "graph_evidence", "tool"] = "source"
    graph_evidence_id: str | None = None


class GroundedFactBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    provenance: list[CitationProvenance]


class GroundedAnswerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grounded: Literal[True] = True
    facts: list[GroundedFactBlock]


class AbstainResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: Literal[True] = True
    reason_code: str
    message: str


@dataclass
class GroundedValidationResult:
    answer_text: str
    answer_status: AnswerStatus | None = None
    schema: GroundedAnswerSchema | AbstainResponse | None = None
    debug: dict[str, Any] = field(default_factory=dict)
    guardrails_patch: dict[str, Any] | None = None
    skipped: bool = False


def _strip_weak_context_disclaimer(answer_text: str) -> str:
    disclaimer = get_settings().retrieval_weak_context_disclaimer.strip()
    if not disclaimer:
        return answer_text
    prefix = disclaimer + "\n\n"
    if answer_text.startswith(prefix):
        return answer_text[len(prefix) :]
    if answer_text.startswith(disclaimer):
        remainder = answer_text[len(disclaimer) :].lstrip("\n")
        return remainder
    return answer_text


def _is_sources_footer_block(text: str) -> bool:
    return bool(re.match(r"^(?:источники|sources)\s*:", text, re.IGNORECASE))


def _segment_fact_blocks(answer_text: str) -> list[str]:
    body = _strip_weak_context_disclaimer(answer_text).strip()
    if not body:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    blocks: list[str] = []
    for paragraph in paragraphs:
        if _is_sources_footer_block(paragraph):
            continue
        if len(paragraph) > 240 and ". " in paragraph:
            sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
            for sentence in sentences:
                if _is_sources_footer_block(sentence):
                    continue
                blocks.append(sentence)
        else:
            blocks.append(paragraph)
    return [block for block in blocks if block]


def _source_by_cite_index(sources: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for idx, source in enumerate(sources, start=1):
        cite_index = source.get("cite_index")
        key = int(cite_index) if cite_index is not None else idx
        indexed[key] = source
    return indexed


def _provenance_for_cite(
    cite_index: int,
    source_lookup: dict[int, dict[str, Any]],
) -> CitationProvenance | None:
    source = source_lookup.get(cite_index)
    if source is None:
        return None
    graph_evidence = source.get("graph_evidence")
    if isinstance(graph_evidence, list) and graph_evidence:
        first = graph_evidence[0] if isinstance(graph_evidence[0], dict) else {}
        evidence_id = str(
            first.get("id")
            or first.get("evidence_id")
            or first.get("graph_evidence_id")
            or ""
        ).strip()
        return CitationProvenance(
            cite_index=cite_index,
            relative_path=source.get("relative_path"),
            provenance_type="graph_evidence",
            graph_evidence_id=evidence_id or None,
        )
    return CitationProvenance(
        cite_index=cite_index,
        relative_path=source.get("relative_path"),
        provenance_type="source",
    )


def _extract_cite_indices(block_text: str) -> list[int]:
    indices: list[int] = []
    for match in CITATION_MARKER_RE.finditer(block_text):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                indices.append(int(part))
    return indices


def _try_parse_fenced_json(answer_text: str) -> GroundedAnswerSchema | AbstainResponse | None:
    match = FENCED_JSON_RE.search(answer_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("abstain") is True:
        return AbstainResponse.model_validate(payload)
    if payload.get("grounded") is True:
        return GroundedAnswerSchema.model_validate(payload)
    return None


def _build_facts_from_text(
    answer_text: str,
    sources: list[dict[str, Any]],
    *,
    homework_mode: bool,
    assistance_level: str | None,
) -> tuple[list[GroundedFactBlock], list[str]]:
    source_lookup = _source_by_cite_index(sources)
    relax_provenance = homework_mode and (assistance_level or "").strip().lower() in HOMEWORK_RELAXED_ASSISTANCE_LEVELS
    validation_errors: list[str] = []
    facts: list[GroundedFactBlock] = []
    for block in _segment_fact_blocks(answer_text):
        cite_indices = _extract_cite_indices(block)
        provenance: list[CitationProvenance] = []
        for cite_index in cite_indices:
            prov = _provenance_for_cite(cite_index, source_lookup)
            if prov is None:
                validation_errors.append(f"invalid_cite_index:{cite_index}")
            else:
                provenance.append(prov)
        if not provenance:
            if cite_indices:
                # Block cites only out-of-range indices; drop it.
                continue
            if not relax_provenance:
                validation_errors.append("missing_provenance")
                # Drop uncited block (symmetric with over-citation).
                # If ALL blocks are uncited, empty facts list → abstain upstream.
                continue
            facts.append(GroundedFactBlock(text=block, provenance=provenance))
            continue
        facts.append(GroundedFactBlock(text=block, provenance=provenance))
    return facts, validation_errors


def build_provenance_ledger(
    schema: GroundedAnswerSchema | AbstainResponse | None,
    *,
    retrieval_confidence: Any = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    if isinstance(schema, AbstainResponse):
        payload: dict[str, Any] = {
            "abstain": True,
            "reason_code": schema.reason_code,
        }
        if retrieval_confidence is not None:
            payload["retrieval_confidence"] = retrieval_confidence
        return payload
    if schema is None or not isinstance(schema, GroundedAnswerSchema):
        return []
    ledger: list[dict[str, Any]] = []
    for fact in schema.facts:
        for prov in fact.provenance:
            ledger.append(
                {
                    "fact_text": fact.text,
                    "cite_index": prov.cite_index,
                    "relative_path": prov.relative_path,
                    "provenance_type": prov.provenance_type,
                }
            )
    return ledger


def _citation_coverage(facts: list[GroundedFactBlock]) -> float | None:
    if not facts:
        return None
    cited = sum(1 for fact in facts if fact.provenance)
    return round(cited / len(facts), 4)


def _build_grounded_debug(
    *,
    schema_validated: bool,
    schema: GroundedAnswerSchema | AbstainResponse | None,
    validation_errors: list[str],
    retrieval_confidence: Any = None,
) -> dict[str, Any]:
    facts_count = len(schema.facts) if isinstance(schema, GroundedAnswerSchema) else 0
    coverage = _citation_coverage(schema.facts) if isinstance(schema, GroundedAnswerSchema) else None
    abstain_reason_code = schema.reason_code if isinstance(schema, AbstainResponse) else None
    return {
        "schema_validated": schema_validated,
        "abstain_reason_code": abstain_reason_code,
        "facts_count": facts_count,
        "citation_coverage": coverage,
        "provenance_ledger": build_provenance_ledger(schema, retrieval_confidence=retrieval_confidence),
        "validation_errors": list(validation_errors),
    }


def _resolve_strict_flags(
    *,
    query_mode: str | None,
    homework_mode: bool,
) -> tuple[bool, bool]:
    settings = get_settings()
    is_tutor = (query_mode or "").strip().lower() == "tutor"
    strict_qa = settings.grounded_answer_strict_qa and not is_tutor
    strict_tutor = settings.grounded_answer_strict_tutor and is_tutor
    if homework_mode and not is_tutor:
        strict_qa = settings.grounded_answer_strict_qa
    return strict_qa, strict_tutor


def validate_and_normalize(
    answer_text: str,
    sources: list[dict[str, Any]],
    *,
    strict: bool,
    homework_mode: bool = False,
    assistance_level: str | None = None,
    retrieval_confidence: Any = None,
) -> GroundedValidationResult:
    validation_errors: list[str] = []
    relax_provenance = homework_mode and (assistance_level or "").strip().lower() in HOMEWORK_RELAXED_ASSISTANCE_LEVELS
    if is_abstain_phrase(answer_text):
        schema = AbstainResponse(
            abstain=True,
            reason_code="model_abstain",
            message=answer_text.strip(),
        )
        debug = _build_grounded_debug(
            schema_validated=True,
            schema=schema,
            validation_errors=validation_errors,
            retrieval_confidence=retrieval_confidence,
        )
        return GroundedValidationResult(
            answer_text=answer_text.strip(),
            answer_status="abstain",
            schema=schema,
            debug=debug,
            guardrails_patch={
                "input_validated": True,
                "output_validated": True,
                "fallback_applied": False,
                "code": "grounded_abstain",
                "message": schema.reason_code,
            },
        )

    parsed = _try_parse_fenced_json(answer_text)
    if isinstance(parsed, AbstainResponse):
        debug = _build_grounded_debug(
            schema_validated=True,
            schema=parsed,
            validation_errors=validation_errors,
            retrieval_confidence=retrieval_confidence,
        )
        return GroundedValidationResult(
            answer_text=parsed.message,
            answer_status="abstain",
            schema=parsed,
            debug=debug,
            guardrails_patch={
                "input_validated": True,
                "output_validated": True,
                "fallback_applied": False,
                "code": "grounded_abstain",
                "message": parsed.reason_code,
            },
        )
    if isinstance(parsed, GroundedAnswerSchema):
        schema = parsed
    else:
        facts, fact_errors = _build_facts_from_text(
            answer_text,
            sources,
            homework_mode=homework_mode,
            assistance_level=assistance_level,
        )
        validation_errors.extend(fact_errors)
        if not facts:
            schema = AbstainResponse(
                abstain=True,
                reason_code="insufficient_provenance",
                message=get_safe_fallback_message("grounded_abstain"),
            )
            debug = _build_grounded_debug(
                schema_validated=False,
                schema=schema,
                validation_errors=validation_errors or ["zero_facts"],
                retrieval_confidence=retrieval_confidence,
            )
            if strict:
                return GroundedValidationResult(
                    answer_text=schema.message,
                    answer_status="abstain",
                    schema=schema,
                    debug=debug,
                    guardrails_patch={
                        "input_validated": True,
                        "output_validated": True,
                        "fallback_applied": False,
                        "code": "grounded_abstain",
                        "message": schema.reason_code,
                    },
                )
            return GroundedValidationResult(
                answer_text=answer_text,
                answer_status="abstain",
                schema=schema,
                debug=debug,
            )
        schema = GroundedAnswerSchema(facts=facts)

    missing_provenance = any(not fact.provenance for fact in schema.facts)
    if relax_provenance:
        missing_provenance = False
        validation_errors = [err for err in validation_errors if err != "missing_provenance"]

    fatal_validation_errors = [
        err
        for err in validation_errors
        if err != "missing_provenance" and not err.startswith("invalid_cite_index:")
    ]

    if fatal_validation_errors or missing_provenance:
        if not validation_errors:
            validation_errors.append("insufficient_provenance")
        abstain = AbstainResponse(
            abstain=True,
            reason_code="insufficient_provenance",
            message=get_safe_fallback_message("grounded_abstain"),
        )
        debug = _build_grounded_debug(
            schema_validated=False,
            schema=abstain,
            validation_errors=validation_errors,
            retrieval_confidence=retrieval_confidence,
        )
        if strict:
            return GroundedValidationResult(
                answer_text=abstain.message,
                answer_status="abstain",
                schema=abstain,
                debug=debug,
                guardrails_patch={
                    "input_validated": True,
                    "output_validated": True,
                    "fallback_applied": False,
                    "code": "grounded_abstain",
                    "message": abstain.reason_code,
                },
            )
        return GroundedValidationResult(
            answer_text=answer_text,
            answer_status="abstain",
            schema=abstain,
            debug=debug,
        )

    debug = _build_grounded_debug(
        schema_validated=True,
        schema=schema,
        validation_errors=validation_errors,
        retrieval_confidence=retrieval_confidence,
    )
    return GroundedValidationResult(
        answer_text=answer_text,
        answer_status="grounded",
        schema=schema,
        debug=debug,
    )


def apply_grounded_validation(
    *,
    answer_text: str,
    sources: list[dict[str, Any]],
    query_mode: str | None,
    homework_mode: bool,
    assistance_level: str | None,
    cache_hit: bool,
    answer_path_mode: str | None = None,
) -> GroundedValidationResult:
    settings = get_settings()
    if not settings.grounded_answer_contract_enabled or cache_hit:
        return GroundedValidationResult(answer_text=answer_text, skipped=True)

    if not sources:
        return GroundedValidationResult(answer_text=answer_text, skipped=True)

    if not str(answer_text or "").strip():
        return GroundedValidationResult(answer_text=answer_text, skipped=True)

    if (answer_path_mode or "").strip() == "two_stage_early":
        return GroundedValidationResult(answer_text=answer_text, skipped=True)

    from app.guardrails import detect_output_violation

    violation = detect_output_violation(answer_text, sources)
    if violation.triggered and violation.code in (
        "empty_answer",
        "missing_sources",
        "pii_detected",
        "suspicious_output",
    ):
        return GroundedValidationResult(answer_text=answer_text, skipped=True)

    strict_qa, strict_tutor = _resolve_strict_flags(
        query_mode=query_mode,
        homework_mode=homework_mode,
    )
    is_tutor = (query_mode or "").strip().lower() == "tutor"
    strict = strict_tutor if is_tutor else strict_qa
    try:
        return validate_and_normalize(
            answer_text,
            sources,
            strict=strict,
            homework_mode=homework_mode,
            assistance_level=assistance_level,
        )
    except GroundedAnswerError as exc:
        abstain = AbstainResponse(
            abstain=True,
            reason_code=exc.reason_code,
            message=exc.message or get_safe_fallback_message("grounded_abstain"),
        )
        debug = _build_grounded_debug(
            schema_validated=False,
            schema=abstain,
            validation_errors=exc.validation_errors or [exc.reason_code],
        )
        if strict:
            raise
        return GroundedValidationResult(
            answer_text=answer_text,
            answer_status="abstain",
            schema=abstain,
            debug=debug,
        )
    except ValidationError as exc:
        debug = _build_grounded_debug(
            schema_validated=False,
            schema=None,
            validation_errors=[str(exc)],
        )
        if strict:
            raise GroundedAnswerError("schema_invalid", str(exc), validation_errors=[str(exc)]) from exc
        return GroundedValidationResult(
            answer_text=answer_text,
            answer_status="abstain",
            debug=debug,
        )


def load_abstain_rate_baseline_summary() -> dict[str, Any] | None:
    from app.eval_baseline import _load_baseline

    path = get_settings().eval_baseline_json
    baseline = _load_baseline(path)
    if not isinstance(baseline, dict):
        return None
    summary = baseline.get("summary")
    return summary if isinstance(summary, dict) else baseline


def evaluate_abstain_rate_gate(
    current_abstain_rate: float,
    baseline_summary: dict[str, Any] | None,
    *,
    max_delta_pp: float = ABSTAIN_RATE_MAX_DELTA_PP,
) -> dict[str, Any]:
    baseline_rate = None
    baseline_id = None
    if isinstance(baseline_summary, dict):
        baseline_rate = baseline_summary.get("abstain_rate")
        baseline_id = baseline_summary.get("baseline_id") or baseline_summary.get("run_id")
    delta_pp = None
    passed = True
    if baseline_rate is not None:
        delta_pp = round((current_abstain_rate - float(baseline_rate)) * 100.0, 4)
        passed = delta_pp <= max_delta_pp
    return {
        "passed": passed,
        "baseline_id": baseline_id,
        "baseline_abstain_rate": baseline_rate,
        "current_abstain_rate": current_abstain_rate,
        "delta_pp": delta_pp,
        "max_delta_pp": max_delta_pp,
    }


__all__ = [
    "AbstainResponse",
    "AnswerStatus",
    "CitationProvenance",
    "GroundedAnswerError",
    "GroundedAnswerSchema",
    "GroundedFactBlock",
    "GroundedValidationResult",
    "apply_grounded_validation",
    "build_provenance_ledger",
    "evaluate_abstain_rate_gate",
    "load_abstain_rate_baseline_summary",
    "validate_and_normalize",
]
