"""Collect accept / reject / defer feedback for SSR recommendations (local, no policy changes)."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal, get_args

from app.smart_study_recommendation import SmartStudyPrimaryNav, SmartStudyRouterHintKind
from app.user_state_ssr_feedback import record_ssr_recommendation_feedback

if TYPE_CHECKING:
    from app.smart_study_router import SmartStudyRecommendation

SsrMisrouteAction = Literal["accept", "reject", "defer"]

_HINT_SET = frozenset(get_args(SmartStudyRouterHintKind))
_NAV_SET = frozenset(get_args(SmartStudyPrimaryNav))


def _validate_router_fields(hint_kind: str, primary_nav: str) -> None:
    hk = str(hint_kind or "").strip()
    pn = str(primary_nav or "").strip()
    if hk not in _HINT_SET:
        raise ValueError(f"invalid hint_kind: {hint_kind!r}")
    if pn not in _NAV_SET:
        raise ValueError(f"invalid primary_nav: {primary_nav!r}")


def weak_concept_sha256(weak_concept: str | None) -> str | None:
    """Hash optional weak concept — never store raw concept text."""
    wc = str(weak_concept or "").strip()
    if not wc:
        return None
    return hashlib.sha256(wc.encode("utf-8")).hexdigest()


def record_ssr_misroute_feedback_api(
    *,
    action: SsrMisrouteAction,
    hint_kind: str,
    primary_nav: str,
    weak_concept_sha256_val: str | None = None,
    why_now_len: int = 0,
    explanation_outcome: str | None = None,
    latency_ms: float | None = None,
    session_key_prefix: str | None = None,
) -> int:
    """HTTP entry: persist row after validating enum fields."""
    _validate_router_fields(hint_kind, primary_nav)
    wcd = str(weak_concept_sha256_val or "").strip() or None
    if wcd is not None and len(wcd) != 64:
        raise ValueError("weak_concept_sha256 must be 64 hex chars or empty")
    return record_ssr_recommendation_feedback(
        action=action,
        hint_kind=str(hint_kind or "").strip(),
        primary_nav=str(primary_nav or "").strip(),
        weak_concept_sha256=wcd,
        why_now_len=int(why_now_len or 0),
        explanation_outcome=str(explanation_outcome or "").strip() or None,
        latency_ms=latency_ms,
        session_key_prefix=str(session_key_prefix or "").strip() or None,
    )


def record_ssr_misroute_feedback(
    *,
    action: SsrMisrouteAction,
    rec: "SmartStudyRecommendation",
    weak_concept: str | None = None,
    why_now_text: str = "",
    session_key: str = "",
    explanation_outcome: str | None = None,
    latency_ms: float | None = None,
) -> int:
    """Persist one feedback event (SQLite via ``user_state``). No PII / no free-text payloads."""
    from app.ssr_explanation_cache import peek_ssr_explanation_feedback_meta

    meta = peek_ssr_explanation_feedback_meta()
    eo = explanation_outcome
    if eo is None:
        eo2 = meta.get("explanation_outcome")
        eo = str(eo2).strip() if eo2 is not None else None
    lat = latency_ms
    if lat is None:
        lm = meta.get("latency_ms")
        if lm is not None:
            try:
                lat = float(lm)
            except (TypeError, ValueError):
                lat = None

    return record_ssr_recommendation_feedback(
        action=action,
        hint_kind=str(rec.hint_kind),
        primary_nav=str(rec.primary_nav),
        weak_concept_sha256=weak_concept_sha256(weak_concept),
        why_now_len=len(str(why_now_text or "")),
        explanation_outcome=eo,
        latency_ms=lat,
        session_key_prefix=str(session_key or "").strip(),
    )


__all__ = [
    "record_ssr_misroute_feedback",
    "record_ssr_misroute_feedback_api",
    "weak_concept_sha256",
]
