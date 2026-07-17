"""Мнемополис Keeper — LLM narrative infrastructure (W3a).

Read-only narrative layer for the 3D hall / Memory Run. Hard rules:

* never writes domain state (mastery, SR, workbench, gamification, user_state);
* LLM only via provider-layer when explicitly allowed;
* budget + cache + degrade + privacy gate (vision kill switch v3.1 §6.1–6.2);
* first paint must not block on this module (callers use degrade / cache first).

W3a = infra + static degrade + prompt stubs. Scenario LLM polish = W3b/W3c.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping

from app.config import get_settings
from app.prompts import mnemo_keeper as prompts

logger = logging.getLogger(__name__)

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

_DOMAIN_WRITE_MARKERS = (
    "user_state",
    "mastery_vector",
    "workbench",
    "gamification",
    "quiz_results",
    "decay_vector",
)


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


def build_cache_key(
    *,
    scenario: str,
    snapshot_date: str = "",
    route_fp: str = "",
    concept_hash: str = "",
    locale: str = "ru",
    mode: str = "static",
) -> str:
    """Cache key. ``mode`` separates static degrade from LLM prose (W3b)."""
    mode_s = "llm" if str(mode or "").strip().lower() == "llm" else "static"
    parts = [
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


def _static_for_scenario(
    scenario: str,
    *,
    stops: list[dict[str, str]] | None = None,
    threats: list[dict[str, object]] | None = None,
    stop_count: int = 0,
    focus: str = "",
) -> str:
    if scenario == prompts.SCENARIO_GUIDE:
        return prompts.static_guide_text(stops=list(stops or []))
    if scenario == prompts.SCENARIO_THREATS:
        return prompts.static_threats_text(threats=list(threats or []))
    if scenario == prompts.SCENARIO_QUEST:
        return prompts.static_quest_text(stop_count=stop_count, focus=focus)
    if scenario == prompts.SCENARIO_VOICES:
        return prompts.static_voices_text()
    return KEEPER_SILENT_COPY


def build_threats_from_decay(
    *,
    decay_vector: Mapping[str, Any] | None,
    labels: Mapping[str, str] | None = None,
    due_map: Mapping[str, Any] | None = None,
    forget_min: float = 0.28,
    limit: int = 8,
) -> list[dict[str, object]]:
    """Deterministic threat list for scenario B (no LLM).

    ``decay_vector`` values are retention 0..1; forgetting = 1 - retention.
    """
    labels = labels or {}
    due_map = due_map or {}
    rows: list[dict[str, object]] = []
    for cid, raw in (decay_vector or {}).items():
        try:
            ret = float(raw)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= ret <= 1.0):
            continue
        forget = 1.0 - ret
        if forget < forget_min:
            continue
        due_raw = due_map.get(cid)
        due_n = None
        if due_raw is not None:
            try:
                due_n = int(due_raw)
            except (TypeError, ValueError):
                due_n = None
        rows.append(
            {
                "id": str(cid),
                "label": str(labels.get(cid) or cid),
                "retention": round(ret, 3),
                "forget_pct": int(round(forget * 100)),
                "due": due_n,
            }
        )
    rows.sort(key=lambda r: (-int(r.get("forget_pct") or 0), str(r.get("id"))))
    return rows[: max(1, int(limit))]


def request_keeper(
    scenario: str,
    *,
    snapshot_date: str = "",
    day_route: list[str] | None = None,
    stops: list[dict[str, str]] | None = None,
    threats: list[dict[str, object]] | None = None,
    focus: str = "",
    locale: str = "ru",
    allow_llm: bool = False,
    session_state: MutableMapping[str, Any] | None = None,
    llm_complete: Callable[[str, str], str] | None = None,
) -> KeeperResult:
    """Main entry: cache → budget → (optional LLM) → degrade.

    Parameters
    ----------
    allow_llm:
        W3a default **False** (infra + degrade smoke). W3b sets True with provider.
    llm_complete:
        Optional ``(system, user) -> text`` for tests / later provider adapter.
        Must not write domain state.
    """
    scenario = str(scenario or "").strip()
    if scenario not in prompts.KEEPER_SCENARIOS:
        return KeeperResult(
            text=KEEPER_SILENT_COPY,
            scenario=scenario or "unknown",
            source="degrade",
            reason="unknown_scenario",
        )

    stops = list(stops or [])
    threats = list(threats or [])
    route_fp = route_fingerprint(day_route or [str(s.get("id") or "") for s in stops])
    if scenario == prompts.SCENARIO_THREATS:
        c_hash = concept_set_hash([str(t.get("id") or "") for t in threats])
    else:
        c_hash = concept_set_hash([str(s.get("id") or "") for s in stops] or (day_route or []))

    key = build_cache_key(
        scenario=scenario,
        snapshot_date=snapshot_date,
        route_fp=route_fp,
        concept_hash=c_hash,
        locale=locale,
        mode="llm" if allow_llm else "static",
    )
    budget = budget_from_session(session_state)
    cache = cache_from_session(session_state)

    cached = cache.get(key)
    if cached is not None:
        return KeeperResult(
            text=cached,
            scenario=scenario,
            source="cache",
            reason="hit",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )

    # Build static degrade payload (always available offline).
    stop_count = len(day_route or stops)
    static_text = _static_for_scenario(
        scenario,
        stops=stops,
        threats=threats,
        stop_count=stop_count,
        focus=focus,
    )

    if not allow_llm:
        cache.set(key, static_text)
        return KeeperResult(
            text=static_text,
            scenario=scenario,
            source="degrade",
            reason="llm_disabled_w3a",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )

    if cloud_path_blocked():
        cache.set(key, static_text)
        return KeeperResult(
            text=static_text,
            scenario=scenario,
            source="degrade",
            reason="cloud_privacy_gate",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )

    if local_circuit_open():
        # Prefer degrade over hanging on open circuit (W3a fail-closed).
        cache.set(key, static_text)
        return KeeperResult(
            text=static_text,
            scenario=scenario,
            source="degrade",
            reason="circuit_open",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )

    system, user = _prompts_for_scenario(scenario, stops=stops, threats=threats, stop_count=stop_count, focus=focus)
    est_in = estimate_tokens(system) + estimate_tokens(user)
    est_out = min(MAX_OUTPUT_TOKENS_PER_CALL, 200)
    if not budget.can_afford(est_input=est_in, est_output=est_out):
        cache.set(key, static_text)
        return KeeperResult(
            text=static_text,
            scenario=scenario,
            source="degrade",
            reason="budget_exceeded",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )

    completer = llm_complete or _default_llm_complete
    t0 = time.perf_counter()
    try:
        text = completer(system, user)
        text = str(text or "").strip() or static_text
    except Exception as exc:  # noqa: BLE001 — always degrade on LLM failure
        logger.info("mnemo_keeper_llm_failed", extra={"scenario": scenario, "error": str(exc)[:200]})
        cache.set(key, static_text)
        return KeeperResult(
            text=static_text,
            scenario=scenario,
            source="degrade",
            reason=f"llm_error:{type(exc).__name__}",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )

    elapsed = time.perf_counter() - t0
    out_tokens = estimate_tokens(text)
    budget.record(input_tokens=est_in, output_tokens=out_tokens)
    cache.set(key, text)
    logger.info(
        "mnemo_keeper_llm_ok",
        extra={
            "scenario": scenario,
            "elapsed_ms": int(elapsed * 1000),
            "calls": budget.calls,
        },
    )
    return KeeperResult(
        text=text,
        scenario=scenario,
        source="llm",
        reason="ok",
        cache_key=key,
        used_llm=True,
        budget_snapshot=budget.as_dict(),
    )


def _prompts_for_scenario(
    scenario: str,
    *,
    stops: list[dict[str, str]],
    threats: list[dict[str, object]],
    stop_count: int,
    focus: str,
) -> tuple[str, str]:
    if scenario == prompts.SCENARIO_GUIDE:
        return prompts.GUIDE_SYSTEM, prompts.build_guide_user_prompt(stops=stops)
    if scenario == prompts.SCENARIO_THREATS:
        return prompts.THREATS_SYSTEM, prompts.build_threats_user_prompt(threats=threats)
    if scenario == prompts.SCENARIO_QUEST:
        user = f"Остановок: {stop_count}. Фокус: {focus or 'маршрут дня'}."
        return prompts.QUEST_SYSTEM, user
    if scenario == prompts.SCENARIO_VOICES:
        return prompts.VOICES_SYSTEM, "Сгенерируй 3 реплики: Туман, Призрак, Разлом."
    return "You are silent.", ""


def _default_llm_complete(system: str, user: str) -> str:
    """Provider-layer completion (used when allow_llm=True and no mock injected)."""
    # Guard: refuse if someone smuggled domain write markers into prompts.
    blob = f"{system}\n{user}".lower()
    for marker in _DOMAIN_WRITE_MARKERS:
        if f"write {marker}" in blob or f"mutate {marker}" in blob:
            raise RuntimeError("domain write instruction rejected")

    from app.provider import get_llm

    llm = get_llm()
    # LlamaIndex-style: complete(prompt) or chat — keep minimal.
    prompt = f"{system.strip()}\n\n{user.strip()}"
    if hasattr(llm, "complete"):
        resp = llm.complete(prompt)
        return str(getattr(resp, "text", None) or resp)
    if hasattr(llm, "chat"):
        resp = llm.chat(prompt)
        return str(resp)
    raise TypeError("LLM client has no complete/chat")
