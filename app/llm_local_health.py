"""Health probe for the local OpenAI-compatible LLM endpoint (e.g. LM Studio).

Used at ``/ui/bootstrap`` to surface a clear "local model unavailable" signal in
the UI instead of letting every SSR card individually time out.

Probe rules:
- If the SSR endpoint shares the main OpenAI base (cloud provider), skip the
  probe — we do not want to hit a paid endpoint just to check liveness.
- Otherwise, ``GET {base}/v1/models`` with a strict timeout. Treat any
  connection/timeout/HTTP error as ``reachable=False``.
- When a model id is configured, also report whether it appears in the
  returned model list (``model_loaded``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.logging_config import log_event

logger = logging.getLogger(__name__)

DEFAULT_PROBE_TIMEOUT_SEC = 1.5


def primary_chat_latency_budgets_sec(settings: Any) -> dict[str, float]:
    """Soft/hard read budgets primary chat локального маршрута (дубли bootstrap/banner без env в модуле)."""
    soft = float(getattr(settings, "home_rag_llm_local_soft_timeout_sec", 8.0))
    hard = float(getattr(settings, "home_rag_llm_local_hard_timeout_sec", 20.0))
    legacy = float(getattr(settings, "llm_request_timeout", 60))
    return {
        "soft_timeout_sec": max(0.2, soft),
        "hard_timeout_sec": max(0.2, hard),
        "effective_local_read_timeout_sec": max(0.2, min(legacy, hard)),
    }


def _models_url(base_url: str) -> str:
    endpoint = base_url.rstrip("/")
    if endpoint.endswith("/v1"):
        return endpoint + "/models"
    return endpoint + "/v1/models"


def probe_local_llm(
    base_url: str | None,
    model: str | None,
    *,
    timeout_sec: float = DEFAULT_PROBE_TIMEOUT_SEC,
    shares_main_base: bool = False,
) -> dict[str, Any]:
    """Return a small JSON-serialisable status dict suitable for /ui/bootstrap.

    Always returns; never raises.
    """
    result: dict[str, Any] = {
        "base_url": base_url,
        "model": model,
        "reachable": False,
        "model_loaded": None,
        "latency_ms": None,
        "error": None,
        "skipped": False,
    }
    if shares_main_base:
        result["skipped"] = True
        result["reason"] = "ssr_shares_main_base"
        return result
    if not base_url:
        result["error"] = "no_base_url"
        return result

    url = _models_url(base_url)
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=max(0.2, float(timeout_sec))) as client:
            response = client.get(url)
            result["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        result["error"] = f"timeout: {exc}"
        return result
    except httpx.HTTPError as exc:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    except ValueError as exc:  # JSON decode
        result["error"] = f"invalid_json: {exc}"
        return result

    result["reachable"] = True
    if model:
        ids: list[str] = []
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            ids = [str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")]
        result["model_loaded"] = model in ids
        result["models_count"] = len(ids)
        if not result["model_loaded"]:
            log_event(
                logger,
                logging.WARNING,
                "llm_local_model_missing",
                base_url=base_url,
                wanted_model=model,
                available_models=ids[:10],
            )
    return result
