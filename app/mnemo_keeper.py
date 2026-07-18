"""Мнемополис Keeper — LLM narrative infrastructure (W3a).

Read-only narrative layer for the 3D hall / Memory Run. Hard rules:

* never writes domain state (mastery, SR, workbench, gamification, user_state);
* LLM only via provider-layer when explicitly allowed;
* budget + cache + degrade + privacy gate (vision kill switch v3.1 §6.1–6.2);
* first paint must not block on this module (callers use degrade / cache first).

Budget/cache helpers live in :mod:`app.mnemo_keeper_budget` (size-budget split).
W3a = infra + static degrade + prompt stubs. Scenario LLM polish = W3b/W3c.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping, MutableMapping

from app.mnemo_keeper_budget import (
    DEFAULT_TIMEOUT_CLOUD_SEC,
    DEFAULT_TIMEOUT_LOCAL_SEC,
    KEEPER_BUDGET_SESSION_KEY,
    KEEPER_CACHE_SESSION_KEY,
    KEEPER_SILENT_COPY,
    MAX_CALLS_PER_SESSION,
    MAX_INPUT_TOKENS_PER_CALL,
    MAX_INPUT_TOKENS_SESSION,
    MAX_OUTPUT_TOKENS_PER_CALL,
    MAX_OUTPUT_TOKENS_SESSION,
    KeeperBudget,
    KeeperCache,
    KeeperResult,
    budget_from_session,
    build_cache_key,
    cache_from_session,
    cloud_path_blocked,
    concept_set_hash,
    estimate_tokens,
    keeper_timeout_sec,
    local_circuit_open,
    route_fingerprint,
)
from app.prompts import mnemo_keeper as prompts

logger = logging.getLogger(__name__)

# Re-export public surface for callers/tests (`import app.mnemo_keeper as keeper`).
__all__ = [
    "DEFAULT_TIMEOUT_CLOUD_SEC",
    "DEFAULT_TIMEOUT_LOCAL_SEC",
    "KEEPER_BUDGET_SESSION_KEY",
    "KEEPER_CACHE_SESSION_KEY",
    "KEEPER_SILENT_COPY",
    "MAX_CALLS_PER_SESSION",
    "MAX_INPUT_TOKENS_PER_CALL",
    "MAX_INPUT_TOKENS_SESSION",
    "MAX_OUTPUT_TOKENS_PER_CALL",
    "MAX_OUTPUT_TOKENS_SESSION",
    "KeeperBudget",
    "KeeperCache",
    "KeeperResult",
    "budget_from_session",
    "build_cache_key",
    "build_threats_from_decay",
    "cache_from_session",
    "cloud_path_blocked",
    "concept_set_hash",
    "estimate_tokens",
    "local_circuit_open",
    "request_keeper",
    "route_fingerprint",
]

_DOMAIN_WRITE_MARKERS = (
    "user_state",
    "mastery_vector",
    "workbench",
    "gamification",
    "quiz_results",
    "decay_vector",
)


def _static_for_scenario(
    scenario: str,
    *,
    stops: list[dict[str, str]] | None = None,
    threats: list[dict[str, object]] | None = None,
    stop_count: int = 0,
    focus: str = "",
    done_count: int = 0,
) -> str:
    if scenario == prompts.SCENARIO_GUIDE:
        return prompts.static_guide_text(stops=list(stops or []))
    if scenario == prompts.SCENARIO_THREATS:
        return prompts.static_threats_text(threats=list(threats or []))
    if scenario == prompts.SCENARIO_QUEST:
        return prompts.static_quest_text(
            stop_count=stop_count, focus=focus, done_count=done_count
        )
    if scenario == prompts.SCENARIO_VOICES:
        return prompts.static_voices_text()
    if scenario == prompts.SCENARIO_CHRONICLE:
        # focus may encode "snap_count|date|concept_count" for degrade (compact).
        parts = str(focus or "").split("|")
        snap_n = 0
        latest = ""
        concepts_n = 0
        try:
            snap_n = int(parts[0]) if parts and parts[0].strip() else 0
        except ValueError:
            snap_n = 0
        if len(parts) > 1:
            latest = parts[1].strip()
        try:
            concepts_n = int(parts[2]) if len(parts) > 2 and parts[2].strip() else 0
        except ValueError:
            concepts_n = 0
        return prompts.static_chronicle_text(
            snapshot_count=snap_n, latest_date=latest, concept_count=concepts_n
        )
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
    done_count: int = 0,
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
        done_count=int(done_count or 0),
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

    system, user = _prompts_for_scenario(
        scenario,
        stops=stops,
        threats=threats,
        stop_count=stop_count,
        focus=focus,
        done_count=int(done_count or 0),
    )
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
    timeout_sec = _keeper_timeout_sec()
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
    # Wall-clock budget (vision §6.2): late responses degrade rather than trust slow prose.
    if elapsed > timeout_sec:
        logger.info(
            "mnemo_keeper_llm_timeout",
            extra={"scenario": scenario, "elapsed_ms": int(elapsed * 1000), "limit_s": timeout_sec},
        )
        cache.set(key, static_text)
        return KeeperResult(
            text=static_text,
            scenario=scenario,
            source="degrade",
            reason="timeout",
            cache_key=key,
            used_llm=False,
            budget_snapshot=budget.as_dict(),
        )
    out_tokens = estimate_tokens(text)
    # Hard output cap: truncate then count (prevents silent budget overshoot).
    max_out_chars = MAX_OUTPUT_TOKENS_PER_CALL * 4
    if len(text) > max_out_chars:
        text = text[: max_out_chars - 1].rstrip() + "…"
        out_tokens = estimate_tokens(text)
    if out_tokens > MAX_OUTPUT_TOKENS_PER_CALL:
        # Char estimate can still overshoot; re-trim aggressively.
        text = text[: max(40, MAX_OUTPUT_TOKENS_PER_CALL * 3)].rstrip() + "…"
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
    done_count: int = 0,
) -> tuple[str, str]:
    if scenario == prompts.SCENARIO_GUIDE:
        return prompts.GUIDE_SYSTEM, prompts.build_guide_user_prompt(stops=stops)
    if scenario == prompts.SCENARIO_THREATS:
        return prompts.THREATS_SYSTEM, prompts.build_threats_user_prompt(threats=threats)
    if scenario == prompts.SCENARIO_QUEST:
        user = (
            f"Остановок: {stop_count}. Пройдено (quiz/mastery): {int(done_count or 0)}. "
            f"Фокус: {focus or 'маршрут дня'}. "
            "Одна строка цели утра ≤160 символов, без XP/монет."
        )
        return prompts.QUEST_SYSTEM, user
    if scenario == prompts.SCENARIO_VOICES:
        return prompts.VOICES_SYSTEM, "Сгенерируй 3 реплики: Туман, Призрак, Разлом."
    if scenario == prompts.SCENARIO_CHRONICLE:
        user = (
            f"Снимки mastery_history (quiz-only): focus={focus or '—'}. "
            "1–2 фразы летописи, без стыда, без XP."
        )
        return prompts.CHRONICLE_SYSTEM, user
    return "You are silent.", ""


def _keeper_timeout_sec() -> float:
    """Module-level alias so tests can patch ``mnemo_keeper._keeper_timeout_sec``."""
    return keeper_timeout_sec()


def _default_llm_complete(system: str, user: str) -> str:
    """Provider-layer completion (used when allow_llm=True and no mock injected)."""
    # Guard: refuse if someone smuggled domain write markers into prompts.
    blob = f"{system}\n{user}".lower()
    for marker in _DOMAIN_WRITE_MARKERS:
        if f"write {marker}" in blob or f"mutate {marker}" in blob:
            raise RuntimeError("domain write instruction rejected")

    from app.provider import get_llm

    llm = get_llm()
    # Prefer short outputs when the client supports max_tokens / timeout kwargs.
    prompt = f"{system.strip()}\n\n{user.strip()}"
    timeout_sec = _keeper_timeout_sec()
    complete_kwargs: dict[str, Any] = {
        "max_tokens": MAX_OUTPUT_TOKENS_PER_CALL,
        "timeout": timeout_sec,
    }

    if hasattr(llm, "complete"):
        try:
            resp = llm.complete(prompt, **complete_kwargs)
        except TypeError:
            resp = llm.complete(prompt)
        return str(getattr(resp, "text", None) or resp)
    if hasattr(llm, "chat"):
        try:
            resp = llm.chat(prompt, **complete_kwargs)
        except TypeError:
            resp = llm.chat(prompt)
        return str(resp)
    raise TypeError("LLM client has no complete/chat")
