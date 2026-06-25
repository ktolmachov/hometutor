"""Unified log-masking policy for observability sinks (wave-pii-masking-redaction)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from app.guardrails import (
    EMAIL_PATTERN,
    GENERIC_API_KEY_PATTERN,
    OPENAI_KEY_PATTERN,
    PHONE_PATTERN,
    redact_sensitive_text,
)

REDACTOR_NAME = "guardrails.redact_sensitive_text"

_LEAK_PATTERNS = (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    OPENAI_KEY_PATTERN,
    GENERIC_API_KEY_PATTERN,
)


class MaskingSink(str, Enum):
    """Observability sinks covered by the unified masking policy."""

    STRUCTURED_LOG = "structured_log"
    OTEL_TRACE = "otel_trace"
    SESSION_TAPE = "session_tape"
    LANGFUSE_EXPORT = "langfuse_export"


SINK_MASKED_FIELDS: dict[str, frozenset[str]] = {
    MaskingSink.STRUCTURED_LOG.value: frozenset(
        {"message", "question", "answer", "prompt", "error", "detail", "body", "text", "exception"}
    ),
    MaskingSink.OTEL_TRACE.value: frozenset(
        {"input", "output", "question", "prompt", "metadata", "attributes", "detail"}
    ),
    MaskingSink.SESSION_TAPE.value: frozenset(
        {"question", "answer", "prompt", "detail", "payload", "error", "body", "text"}
    ),
    MaskingSink.LANGFUSE_EXPORT.value: frozenset(
        {"input", "output", "expectedOutput", "expected_output", "metadata", "question", "answer"}
    ),
}


def _normalize_sink(sink: str | MaskingSink) -> str:
    if isinstance(sink, MaskingSink):
        return sink.value
    return str(sink).strip()


def get_sink_masked_fields(sink: str | MaskingSink) -> frozenset[str]:
    """Return field names that must be redacted for the given sink."""
    key = _normalize_sink(sink)
    return SINK_MASKED_FIELDS.get(key, frozenset())


def describe_sink_policy(sink: str | MaskingSink) -> dict[str, Any]:
    """Serializable policy record for audits and Langfuse export gates."""
    key = _normalize_sink(sink)
    return {
        "sink": key,
        "masked_fields": sorted(get_sink_masked_fields(key)),
        "redactor": REDACTOR_NAME,
    }


def list_sink_policies() -> list[dict[str, Any]]:
    """All sink policies in stable sink-id order."""
    return [describe_sink_policy(sink) for sink in MaskingSink]


def should_mask_field(sink: str | MaskingSink, field_name: str) -> bool:
    """True when the sink policy requires redaction for ``field_name``."""
    name = str(field_name or "").strip()
    if not name:
        return False
    masked = get_sink_masked_fields(sink)
    return name in masked or name.lower() in {item.lower() for item in masked}


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_for_sink(
    sink: str | MaskingSink,
    field_name: str,
    value: Any,
) -> Any:
    """Apply policy redaction to a single field value when the field is masked."""
    if not should_mask_field(sink, field_name):
        return value
    return _redact_value(value)


def redact_sink_payload(
    sink: str | MaskingSink,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a shallow copy of ``payload`` with masked fields redacted per sink policy."""
    masked = get_sink_masked_fields(sink)
    if not masked:
        return dict(payload)
    lowered = {name.lower(): name for name in masked}
    result: dict[str, Any] = {}
    for key, value in payload.items():
        key_str = str(key)
        if key_str in masked or key_str.lower() in lowered:
            result[key_str] = _redact_value(value)
        else:
            result[key_str] = value
    return result


def contains_unmasked_pii(text: str) -> bool:
    """True when ``text`` still matches email/phone/API-key leak patterns."""
    if not text:
        return False
    for pattern in _LEAK_PATTERNS:
        if pattern.search(text):
            return True
    return False


def assert_sink_payload_clean(sink: str | MaskingSink, payload: Mapping[str, Any]) -> None:
    """Raise ValueError when masked fields in ``payload`` still contain detectable PII."""
    masked = get_sink_masked_fields(sink)
    for key, value in payload.items():
        key_str = str(key)
        if key_str not in masked and key_str.lower() not in {name.lower() for name in masked}:
            continue
        if isinstance(value, str) and contains_unmasked_pii(value):
            raise ValueError(f"unmasked PII in sink={_normalize_sink(sink)} field={key_str}")
