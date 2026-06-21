from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from threading import Lock
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import log_event, reset_request_id, set_request_id, setup_logging


logger = setup_logging()


class LoggingMiddleware(BaseHTTPMiddleware):
    """Simple request/response logging with latency and request id."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.perf_counter()
        request.state.request_id = request_id
        token = set_request_id(request_id)

        log_event(
            logger,
            logging.INFO,
            "http_request_started",
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)

            elapsed_ms = (time.perf_counter() - start) * 1000
            response.headers.setdefault("X-Request-ID", request_id)

            log_event(
                logger,
                logging.INFO,
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=round(elapsed_ms, 3),
            )

            return response
        finally:
            reset_request_id(token)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Простой лимит запросов на IP за скользящее окно 60 с (18 Core; in-memory)."""

    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self.requests_per_minute = max(1, int(requests_per_minute))
        self._lock = Lock()
        self._hits: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        client_host = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = 60.0
        with self._lock:
            dq = self._hits.setdefault(client_host, deque())
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= self.requests_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": {"code": "rate_limited", "message": "Too many requests"}},
                )
            dq.append(now)
        return await call_next(request)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Uniform fallback for unhandled exceptions."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
        token = set_request_id(request_id)
        try:
            return await call_next(request)
        except HTTPException:
            # Let FastAPI's HTTPException handling work as before.
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            log_event(
                logger,
                logging.ERROR,
                "http_unhandled_error",
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "internal_error",
                        "message": "Internal server error",
                    }
                },
            )
        finally:
            reset_request_id(token)

