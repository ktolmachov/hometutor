"""Per-endpoint circuit breaker for the local OpenAI-compatible LLM.

When ``record_failure`` is called ``failure_threshold`` times within a short
window for the same ``base_url``, the circuit opens: subsequent ``is_open``
checks return ``True`` for ``reset_after_sec`` seconds. This lets callers
(e.g. the SSR Why-Now generator) short-circuit straight to the deterministic
template fallback instead of waiting on N×timeout against a dead endpoint.

This is intentionally process-local and lock-free: a stale read at worst
causes one extra real attempt and is preferable to introducing a lock in a
UI hot path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.logging_config import log_event

logger = logging.getLogger(__name__)


DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RESET_AFTER_SEC = 60.0
DEFAULT_FAILURE_WINDOW_SEC = 30.0


@dataclass
class _EndpointState:
    failures: list[float] = field(default_factory=list)  # monotonic timestamps
    opened_at: float | None = None
    last_error_type: str | None = None


_STATE_BY_BASE: dict[str, _EndpointState] = {}


def _normalise(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return base_url.rstrip("/").lower()


def _now() -> float:
    return time.monotonic()


def _trim(state: _EndpointState, *, now: float, window: float) -> None:
    cutoff = now - window
    state.failures = [t for t in state.failures if t >= cutoff]


def is_open(
    base_url: str | None,
    *,
    reset_after_sec: float | None = None,
    now: float | None = None,
) -> bool:
    """Whether new calls to this endpoint should be skipped."""
    key = _normalise(base_url)
    if not key:
        return False
    state = _STATE_BY_BASE.get(key)
    if state is None or state.opened_at is None:
        return False
    current = _now() if now is None else now
    reset_after = get_settings().llm_local_cb_reset_sec if reset_after_sec is None else reset_after_sec
    if current - state.opened_at >= reset_after:
        # Auto half-open: clear opened_at and allow one real attempt; on success
        # callers will reset, on failure the circuit re-opens immediately.
        state.opened_at = None
        state.failures.clear()
        log_event(
            logger,
            logging.INFO,
            "llm_local_circuit_half_open",
            base_url=base_url,
            last_error_type=state.last_error_type,
        )
        return False
    return True


def record_failure(
    base_url: str | None,
    *,
    error_type: str | None = None,
    failure_threshold: int | None = None,
    failure_window_sec: float | None = None,
    now: float | None = None,
) -> bool:
    """Record a failed call. Returns ``True`` if the circuit just transitioned to open."""
    key = _normalise(base_url)
    if not key:
        return False
    current = _now() if now is None else now
    settings = get_settings()
    threshold = settings.llm_local_cb_failures if failure_threshold is None else failure_threshold
    window_sec = settings.llm_local_cb_window_sec if failure_window_sec is None else failure_window_sec
    state = _STATE_BY_BASE.setdefault(key, _EndpointState())
    state.last_error_type = error_type or state.last_error_type
    _trim(state, now=current, window=window_sec)
    state.failures.append(current)
    if state.opened_at is None and len(state.failures) >= threshold:
        state.opened_at = current
        log_event(
            logger,
            logging.WARNING,
            "llm_local_circuit_opened",
            base_url=base_url,
            error_type=error_type,
            failures=len(state.failures),
            window_sec=window_sec,
        )
        return True
    return False


def record_success(base_url: str | None, *, now: float | None = None) -> None:
    """Record a successful call. Closes the circuit if it was open."""
    key = _normalise(base_url)
    if not key:
        return
    state = _STATE_BY_BASE.get(key)
    if state is None:
        return
    was_open = state.opened_at is not None
    state.failures.clear()
    state.opened_at = None
    if was_open:
        log_event(
            logger,
            logging.INFO,
            "llm_local_circuit_closed",
            base_url=base_url,
        )


def reset_all() -> None:
    """Drop all circuit state. Intended for tests."""
    _STATE_BY_BASE.clear()


def snapshot() -> dict[str, dict[str, object]]:
    """Read-only view of current circuit state, for debugging/observability."""
    out: dict[str, dict[str, object]] = {}
    for key, state in _STATE_BY_BASE.items():
        out[key] = {
            "failures": len(state.failures),
            "opened": state.opened_at is not None,
            "last_error_type": state.last_error_type,
        }
    return out
