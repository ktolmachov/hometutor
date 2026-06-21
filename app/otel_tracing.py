"""
Опциональный OpenTelemetry OTLP (HTTP) — включается ENABLE_OTEL_TRACING.
Без пакетов opentelemetry-* импорт тихо пропускается.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_provider_initialized = False


def _otlp_endpoint_reachable(endpoint: str, timeout_s: float = 1.0) -> bool:
    """Probe collector host:port before enabling BatchSpanProcessor (avoid retry tail)."""
    from urllib.parse import urlparse

    import socket

    raw = (endpoint or "").strip()
    if not raw:
        return False
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _parse_otlp_headers(raw_headers: str | None) -> dict[str, str]:
    """Parse the OTEL comma-separated ``name=value`` header format."""
    headers: dict[str, str] = {}
    for item in (raw_headers or "").split(","):
        name, separator, value = item.strip().partition("=")
        if separator and name.strip() and value.strip():
            headers[name.strip()] = value.strip()
    return headers


def init_otel_if_enabled() -> None:
    global _provider_initialized
    if _provider_initialized:
        return
    from app.config import get_settings

    s = get_settings()
    if not s.enable_otel_tracing:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        logger.warning("OpenTelemetry packages not installed; tracing disabled")
        return

    from app.langfuse_trace_export import resolve_langfuse_otlp_export

    endpoint, header_map = resolve_langfuse_otlp_export()
    if not endpoint:
        logger.warning("ENABLE_OTEL_TRACING set but OTLP endpoint empty (set OTEL_EXPORTER_OTLP_ENDPOINT or LANGFUSE_HOST)")
        return

    if not _otlp_endpoint_reachable(endpoint):
        logger.warning(
            "OpenTelemetry OTLP collector unreachable at %s; tracing disabled (set ENABLE_OTEL_TRACING=false locally to silence)",
            endpoint,
        )
        return

    resource = Resource.create(
        {
            "service.name": (s.otel_service_name or "home-rag").strip() or "home-rag",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers=header_map,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider_initialized = True
    logger.info("OpenTelemetry OTLP tracing enabled endpoint=%s", endpoint)


def shutdown_otel_if_needed() -> None:
    global _provider_initialized
    if not _provider_initialized:
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception as e:  # noqa: BLE001 - OTel setup must not block local app startup.
        logger.warning("OTel shutdown failed: %s", e)
    _provider_initialized = False


def get_tracer(name: str) -> Any:
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpSpan:
    def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> Iterator[_NoOpSpan]:
        yield _NoOpSpan()


@contextmanager
def trace_tool_span(tool_name: str, *, session_id: str | None = None) -> Iterator[Any]:
    """OTLP tool span for Langfuse observation mapping."""
    from app.config import get_settings
    from app.langfuse_trace_export import apply_langfuse_query_span_attributes

    if not get_settings().enable_otel_tracing:
        yield None
        return
    tracer = get_tracer("home_rag.tools")
    with tracer.start_as_current_span(f"tool.{tool_name}") as span:
        apply_langfuse_query_span_attributes(
            span,
            session_id=session_id,
            query_mode=None,
            usage=None,
            model=None,
            estimated_cost_usd=None,
            tool_name=tool_name,
        )
        yield span


@contextmanager
def trace_ssr_llm_explanation() -> Iterator[Any]:
    """Спан ``ssr_llm_explanation`` при ``ENABLE_OTEL_TRACING``; иначе ``yield None``."""
    from app.config import get_settings

    if not get_settings().enable_otel_tracing:
        yield None
        return
    tracer = get_tracer("app.ssr_llm")
    with tracer.start_as_current_span("ssr_llm_explanation") as span:
        yield span


def set_ssr_span_attributes(span: Any | None, attrs: dict[str, Any]) -> None:
    """Атрибуты с префиксом ``ssr.`` для OTLP (строки/числа/булевы)."""
    if span is None:
        return
    setter = getattr(span, "set_attribute", None)
    if not callable(setter):
        return
    for key, raw in attrs.items():
        if raw is None:
            continue
        name = key if str(key).startswith("ssr.") else f"ssr.{key}"
        try:
            setter(name, raw)
        except Exception:  # noqa: BLE001 - атрибуты не должны ломать UI
            continue
