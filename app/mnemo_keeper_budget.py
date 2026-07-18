"""Мнемополис Keeper — budget, cache keys, session helpers (W3a infra slice).

Extracted from :mod:`app.mnemo_keeper` so the request path stays under the
architecture size budget. Read-only: never writes domain state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, MutableMapping

from app.config import get_settings
from app.prompts import mnemo_keeper as prompts

# Vision §6.2 budget table (v1).
MAX_CALLS_PER_SESSION = 4
MAX_INPUT_TOKENS_PER_CALL = 1600
MAX_OUTPUT_TOKENS_PER_CALL = 400
MAX_INPUT_TOKENS_SESSION = 8000
MAX_OUTPUT_TOKENS_SESSION = 1600
DEFAULT_TIMEOUT_LOCAL_SEC = 8.0
DEFAULT_TIMEOUT_CLOUD_SEC = 5.0

# Fail-closed user copy (also in prompts).
KEEPER_SILENT_COPY = prompts.KEEPER_SILENT_COPY

# Session / UI state keys (UI-state only — not user_state DB).
KEEPER_BUDGET_SESSION_KEY = "mnemo_keeper_budget"
KEEPER_CACHE_SESSION_KEY = "mnemo_keeper_cache"


@dataclass
class KeeperBudget:
    """Mutable per-UI-session counters (vision §6.2)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    max_calls: int = MAX_CALLS_PER_SESSION
    max_input_per_call: int = MAX_INPUT_TOKENS_PER_CALL
    max_output_per_call: int = MAX_OUTPUT_TOKENS_PER_CALL
    max_input_session: int = MAX_INPUT_TOKENS_SESSION
    max_output_session: int = MAX_OUTPUT_TOKENS_SESSION

    def can_afford(self, *, est_input: int, est_output: int) -> bool:
        if self.calls >= self.max_calls:
            return False
        if est_input > self.max_input_per_call or est_output > self.max_output_per_call:
            return False
        if self.input_tokens + est_input > self.max_input_session:
            return False
        if self.output_tokens + est_output > self.max_output_session:
            return False
        return True

    def record(self, *, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += max(0, int(input_tokens))
        self.output_tokens += max(0, int(output_tokens))

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "max_calls": self.max_calls,
            "max_input_session": self.max_input_session,
            "max_output_session": self.max_output_session,
        }


@dataclass
class KeeperResult:
    """Read-only narrative result. Never a domain mutation ticket."""

    text: str
    scenario: str
    source: str  # cache | degrade | llm
    reason: str = ""
    cache_key: str = ""
    used_llm: bool = False
    budget_snapshot: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(str(self.text or "").strip())


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars/4). Enough for budget gates without a tokenizer."""
    s = str(text or "")
    if not s:
        return 0
    return max(1, (len(s) + 3) // 4)


def route_fingerprint(day_route: list[str] | tuple[str, ...] | None) -> str:
    ids = [str(x).strip() for x in (day_route or []) if str(x).strip()]
    raw = "|".join(ids)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def concept_set_hash(concept_ids: list[str] | tuple[str, ...] | None) -> str:
    ids = sorted({str(x).strip() for x in (concept_ids or []) if str(x).strip()})
    raw = "|".join(ids)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _provider_model_ids() -> tuple[str, str]:
    """Best-effort provider/model identity for cache isolation (vision §6.1).

    Must mirror :func:`app.provider.get_llm` routing:
    * ``cloud_fast`` → OPENAI_API_BASE + llm_model
    * ``local_strict`` / ``balanced`` (local path) → LMSTUDIO_API_BASE + llm_model
    * ``balanced`` with open CB + ready fallback → fallback base/model

    Do **not** prefer ``openai_api_base`` for local profiles (it is non-empty by
    default and would hide LMSTUDIO_API_BASE changes).
    """
    try:
        from app.llm_local_circuit import is_open
        from app.provider import (
            _lmstudio_api_base,
            _resolve_primary_fallback_api_base,
            _resolve_primary_fallback_model,
            normalize_openai_compatible_api_base,
            primary_chat_fallback_ready,
        )

        settings = get_settings()
        profile = str(
            getattr(settings, "home_rag_local_profile", "balanced") or "balanced"
        ).strip().lower()
        default_model = str(getattr(settings, "llm_model", "") or "").strip() or "unknown-model"

        if profile == "cloud_fast":
            base = normalize_openai_compatible_api_base(
                str(getattr(settings, "openai_api_base", "") or "")
            )
            model = default_model
        else:
            local_base = normalize_openai_compatible_api_base(_lmstudio_api_base(settings))
            use_fallback = False
            if profile == "balanced":
                try:
                    cb_open = bool(local_base and is_open(local_base))
                    use_fallback = cb_open and primary_chat_fallback_ready(settings)
                except Exception:  # noqa: BLE001 - CB probe must not break cache path
                    use_fallback = False
            if use_fallback:
                fb_base = _resolve_primary_fallback_api_base(settings) or ""
                fb_model = _resolve_primary_fallback_model(settings) or ""
                base = normalize_openai_compatible_api_base(fb_base) if fb_base else local_base
                model = str(fb_model).strip() or default_model
            else:
                base = local_base
                model = default_model

        provider = base or profile or "default"
        provider_id = hashlib.sha256(provider.encode("utf-8")).hexdigest()[:12]
        model_id = model[:64]
        return provider_id, model_id
    except Exception:  # noqa: BLE001 - cache key must not break degrade path
        return "unknown-provider", "unknown-model"


def build_cache_key(
    *,
    scenario: str,
    snapshot_date: str = "",
    route_fp: str = "",
    concept_hash: str = "",
    locale: str = "ru",
    mode: str = "static",
    provider_id: str = "",
    model_id: str = "",
    prompt_version: str = "",
) -> str:
    """Cache key (vision §6.1).

    Minimum: provider_id, model_id, prompt_version, scenario, snapshot_date|day,
    locale, route_fingerprint|concept_set_hash, plus mode (static vs llm).
    """
    mode_s = "llm" if str(mode or "").strip().lower() == "llm" else "static"
    if not provider_id or not model_id:
        pid, mid = _provider_model_ids()
        provider_id = provider_id or pid
        model_id = model_id or mid
    if not prompt_version:
        prompt_version = str(getattr(prompts, "KEEPER_PROMPT_VERSION", "unknown") or "unknown")
    parts = [
        str(provider_id or "").strip() or "unknown-provider",
        str(model_id or "").strip() or "unknown-model",
        str(prompt_version or "").strip() or "unknown",
        str(scenario or "").strip(),
        str(snapshot_date or "").strip() or "no-date",
        str(route_fp or "").strip() or "no-route",
        str(concept_hash or "").strip() or "no-concepts",
        str(locale or "ru").strip() or "ru",
        mode_s,
    ]
    return "|".join(parts)


class KeeperCache:
    """In-process / session cache. TTL logical: until snapshot_date or route_fp change (key)."""

    def __init__(self, store: MutableMapping[str, str] | None = None) -> None:
        self._store: MutableMapping[str, str] = store if store is not None else {}

    def get(self, key: str) -> str | None:
        val = self._store.get(key)
        if val is None:
            return None
        text = str(val).strip()
        return text or None

    def set(self, key: str, text: str) -> None:
        self._store[key] = str(text or "")

    def __len__(self) -> int:
        return len(self._store)


def budget_from_session(state: MutableMapping[str, Any] | None) -> KeeperBudget:
    """Load or create budget counters from UI session-state mapping."""
    if state is None:
        return KeeperBudget()
    raw = state.get(KEEPER_BUDGET_SESSION_KEY)
    if isinstance(raw, KeeperBudget):
        return raw
    if isinstance(raw, dict):
        b = KeeperBudget(
            calls=int(raw.get("calls") or 0),
            input_tokens=int(raw.get("input_tokens") or 0),
            output_tokens=int(raw.get("output_tokens") or 0),
        )
        state[KEEPER_BUDGET_SESSION_KEY] = b
        return b
    b = KeeperBudget()
    state[KEEPER_BUDGET_SESSION_KEY] = b
    return b


def cache_from_session(state: MutableMapping[str, Any] | None) -> KeeperCache:
    if state is None:
        return KeeperCache()
    raw = state.get(KEEPER_CACHE_SESSION_KEY)
    if isinstance(raw, KeeperCache):
        return raw
    if isinstance(raw, dict):
        c = KeeperCache(store=raw)
        state[KEEPER_CACHE_SESSION_KEY] = c
        return c
    store: dict[str, str] = {}
    c = KeeperCache(store=store)
    state[KEEPER_CACHE_SESSION_KEY] = c
    return c


def cloud_path_blocked(settings=None) -> bool:
    """Privacy gate: cloud_fast Keeper path requires existing cloud consent.

    Reuses ``home_rag_llm_cloud_consent`` (no second consent flag).
    """
    s = settings or get_settings()
    profile = str(getattr(s, "home_rag_local_profile", "balanced") or "balanced").strip().lower()
    consent = bool(getattr(s, "home_rag_llm_cloud_consent", False))
    if profile == "cloud_fast" and not consent:
        return True
    return False


def local_circuit_open() -> bool:
    try:
        from app.provider import local_primary_chat_circuit_open

        return bool(local_primary_chat_circuit_open())
    except Exception:  # noqa: BLE001 — CB probe must not break degrade path
        return False


def keeper_timeout_sec() -> float:
    """Wall timeout for Keeper LLM (vision §6.2 local 8s / cloud 5s)."""
    try:
        settings = get_settings()
        profile = str(getattr(settings, "home_rag_local_profile", "balanced") or "").lower()
        if profile == "cloud_fast":
            return float(DEFAULT_TIMEOUT_CLOUD_SEC)
    except Exception:  # noqa: BLE001
        pass
    return float(DEFAULT_TIMEOUT_LOCAL_SEC)
