from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError

import app.api_services as services
from app.config import Settings, get_settings
from app.guardrails import InputGuardrailError, OutputGuardrailError
from app.logging_config import get_request_id


def request_id_from_request(request: Request | None) -> str | None:
    if request is None:
        return get_request_id()
    return getattr(request.state, "request_id", None) or get_request_id()


def classify_error_kind(exc: Exception) -> str:
    if isinstance(exc, (InputGuardrailError, OutputGuardrailError, RequestValidationError)):
        return "guardrail"
    if isinstance(exc, HTTPException):
        return "http"

    error_type = type(exc).__name__.lower()
    message = str(exc).lower()
    provider_markers = (
        "openai",
        "api key",
        "api_base",
        "model",
        "rate limit",
        "timeout",
        "connection",
        "provider",
    )
    if any(marker in error_type for marker in ("openai", "api", "authentication")):
        return "provider"
    if any(marker in message for marker in provider_markers):
        return "provider"
    return "runtime"


def record_api_error(
    *,
    endpoint: str,
    exc: Exception,
    request: Request | None = None,
    status_code: int | None = None,
) -> None:
    services.record_error(
        request_id=request_id_from_request(request),
        endpoint=endpoint,
        error_kind=classify_error_kind(exc),
        error_type=type(exc).__name__,
        status_code=status_code,
        message=str(exc),
    )


def _cors_list(raw: str | None, default: str) -> list[str]:
    value = (raw or "").strip() or default.strip()
    if value == "*":
        return ["*"]
    return [x.strip() for x in value.split(",") if x.strip()]


def cors_origins_list() -> list[str]:
    default = str(Settings.model_fields["cors_origins"].default)
    return _cors_list(get_settings().cors_origins, default)


def cors_methods_list() -> list[str]:
    default = str(Settings.model_fields["cors_methods"].default)
    return _cors_list(get_settings().cors_methods, default)


def cors_headers_list() -> list[str]:
    default = str(Settings.model_fields["cors_headers"].default)
    return _cors_list(get_settings().cors_headers, default)
