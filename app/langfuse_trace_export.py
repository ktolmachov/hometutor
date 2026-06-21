"""Langfuse OTLP trace export helpers (wave-langfuse-eval-loop / package 1)."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urljoin

from app.config import get_settings
from app.guardrails import redact_sensitive_text

LANGFUSE_INGESTION_VERSION = "4"
LANGFUSE_OTLP_TRACES_PATH = "/api/public/otel/v1/traces"


def normalize_langfuse_otlp_endpoint(host: str | None) -> str:
    """Build Langfuse self-hosted/cloud OTLP traces endpoint from base host URL."""
    base = (host or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/traces") or "/api/public/otel/" in base:
        return base
    return urljoin(f"{base}/", LANGFUSE_OTLP_TRACES_PATH.lstrip("/"))


def build_langfuse_basic_auth_header(public_key: str | None, secret_key: str | None) -> str | None:
    pub = (public_key or "").strip()
    sec = (secret_key or "").strip()
    if not pub or not sec:
        return None
    token = base64.b64encode(f"{pub}:{sec}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def merge_langfuse_otlp_headers(
    existing: dict[str, str] | None,
    *,
    public_key: str | None,
    secret_key: str | None,
) -> dict[str, str]:
    headers = dict(existing or {})
    auth = build_langfuse_basic_auth_header(public_key, secret_key)
    if auth and "Authorization" not in headers:
        headers["Authorization"] = auth
    headers.setdefault("x-langfuse-ingestion-version", LANGFUSE_INGESTION_VERSION)
    return headers


def resolve_langfuse_otlp_export() -> tuple[str, dict[str, str]]:
    """Resolve OTLP endpoint/headers for Langfuse export without duplicating OTel metrics."""
    settings = get_settings()
    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
    headers = _parse_headers(settings.otel_exporter_otlp_headers)

    if not settings.langfuse_trace_export_enabled:
        return endpoint, headers

    if not endpoint:
        endpoint = normalize_langfuse_otlp_endpoint(settings.langfuse_host)
    headers = merge_langfuse_otlp_headers(
        headers,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
    )
    return endpoint, headers


def sanitize_otel_attribute_value(value: Any) -> Any:
    """Best-effort PII redaction for span attributes until wave-pii-masking-redaction ships."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_sensitive_text(str(value))


def apply_span_attributes(span: Any | None, attrs: dict[str, Any]) -> None:
    if span is None:
        return
    setter = getattr(span, "set_attribute", None)
    if not callable(setter):
        return
    for key, raw in attrs.items():
        if raw is None:
            continue
        try:
            setter(str(key), sanitize_otel_attribute_value(raw))
        except Exception:  # noqa: BLE001 - attribute export must not break hot path
            continue


def apply_langfuse_query_span_attributes(
    span: Any | None,
    *,
    session_id: str | None,
    query_mode: str | None,
    usage: dict[str, int] | None,
    model: str | None,
    estimated_cost_usd: float | None,
    tool_name: str | None = None,
) -> None:
    """Attach session/cost/tool metadata consumable by Langfuse OTLP ingestion."""
    attrs: dict[str, Any] = {
        "langfuse.session.id": (session_id or "").strip() or None,
        "home_rag.query_mode": (query_mode or "").strip() or None,
        "gen_ai.request.model": (model or "").strip() or None,
        "gen_ai.usage.prompt_tokens": (usage or {}).get("prompt_tokens"),
        "gen_ai.usage.completion_tokens": (usage or {}).get("completion_tokens"),
        "gen_ai.usage.total_tokens": (usage or {}).get("total_tokens"),
        "home_rag.estimated_cost_usd": estimated_cost_usd,
        "langfuse.trace.metadata.export": "langfuse_trace_export_v1",
    }
    if tool_name:
        attrs["langfuse.observation.type"] = "tool"
        attrs["gen_ai.tool.name"] = tool_name
    apply_span_attributes(span, attrs)


def _parse_headers(raw_headers: str | None) -> dict[str, str]:
    from app.otel_tracing import _parse_otlp_headers

    return _parse_otlp_headers(raw_headers)


__all__ = [
    "LANGFUSE_INGESTION_VERSION",
    "LANGFUSE_OTLP_TRACES_PATH",
    "apply_langfuse_query_span_attributes",
    "apply_span_attributes",
    "build_langfuse_basic_auth_header",
    "merge_langfuse_otlp_headers",
    "normalize_langfuse_otlp_endpoint",
    "resolve_langfuse_otlp_export",
    "sanitize_otel_attribute_value",
]
