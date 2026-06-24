"""Offline misroute policy learning — tie-break primary_nav only (L5, US-20.1 extension).

Pure functions; no Streamlit; not invoked from feedback write path.
Weights: ``app/ssr_misroute_policy_weights.json`` (git-tracked empty ``{}``; runtime snapshot).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings
from app.smart_study_recommendation import (
    SmartStudyPrimaryNav,
    SmartStudyRecommendation,
    SmartStudyRouterHintKind,
)
from app.smart_study_scoring import _stable_secondaries
from app.smart_study_ssr_ml import _SSR_ML_NO_RULE_OVERRIDE

_WEIGHTS_PATH = Path(__file__).resolve().parent / "ssr_misroute_policy_weights.json"
_LOCK = threading.Lock()

_RETENTION_OUTCOMES = frozenset({"helpful", "completed", "retained"})
_ALTERNATE_ACCEPT_WINDOW = timedelta(hours=48)
_MIN_WEIGHTED_REJECTS = 3.0

_POLICY_TIEBREAK_ALTERNATES: dict[SmartStudyRouterHintKind, tuple[SmartStudyPrimaryNav, ...]] = {
    "mastery_stale": ("qa_continue",),
    "answer_ready": ("safe_tutor_5min",),
    "safe_default": ("qa_continue",),
}


@dataclass(frozen=True)
class MisroutePolicyAdjustment:
    """Tie-break nav swap when offline gate passes for a bucket."""

    hint_kind: SmartStudyRouterHintKind
    original_primary_nav: SmartStudyPrimaryNav
    adjusted_primary_nav: SmartStudyPrimaryNav
    bucket_key: str
    decay_factor: float
    nav_penalty: float


def misroute_bucket_key(
    *,
    hint_kind: str,
    primary_nav: str,
    weak_concept_sha256: str | None = None,
) -> str:
    wc = str(weak_concept_sha256 or "").strip()
    return f"{str(hint_kind or '').strip()}|{str(primary_nav or '').strip()}|{wc}"


def reject_decay_weight(*, age_days: float, decay_days: int) -> float:
    if decay_days <= 0:
        return 0.0
    return max(0.0, 1.0 - float(age_days) / float(decay_days))


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _age_days(*, created_at: str, now: datetime) -> float:
    created = _parse_iso(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    delta = ref - created.astimezone(timezone.utc)
    return max(0.0, delta.total_seconds() / 86400.0)


def _rows_in_decay_window(
    rows: list[dict[str, Any]],
    *,
    decay_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        age = _age_days(created_at=str(row.get("created_at") or ""), now=now)
        if age <= float(decay_days):
            out.append({**row, "_age_days": age})
    return out


def _weighted_reject_sum(rows: list[dict[str, Any]], *, decay_days: int) -> float:
    total = 0.0
    for row in rows:
        if str(row.get("action") or "").strip().lower() != "reject":
            continue
        age = float(row.get("_age_days", 0.0))
        total += reject_decay_weight(age_days=age, decay_days=decay_days)
    return total


def _has_accept_in_bucket(rows: list[dict[str, Any]]) -> bool:
    return any(str(r.get("action") or "").strip().lower() == "accept" for r in rows)


def _has_retention_alignment(
    *,
    bucket_rows: list[dict[str, Any]],
    hint_kind: str,
    all_rows: list[dict[str, Any]],
) -> bool:
    for row in bucket_rows:
        eo = str(row.get("explanation_outcome") or "").strip().lower()
        if eo in _RETENTION_OUTCOMES:
            return True

    reject_ts: list[datetime] = []
    for row in bucket_rows:
        if str(row.get("action") or "").strip().lower() != "reject":
            continue
        reject_ts.append(_parse_iso(str(row["created_at"])))

    if not reject_ts:
        return False
    last_reject = max(reject_ts)
    if last_reject.tzinfo is None:
        last_reject = last_reject.replace(tzinfo=timezone.utc)
    window_end = last_reject + _ALTERNATE_ACCEPT_WINDOW

    hk = str(hint_kind or "").strip()
    bucket_nav = str(bucket_rows[0].get("primary_nav") or "").strip()
    for row in all_rows:
        if str(row.get("action") or "").strip().lower() != "accept":
            continue
        if str(row.get("hint_kind") or "").strip() != hk:
            continue
        alt_nav = str(row.get("primary_nav") or "").strip()
        if not alt_nav or alt_nav == bucket_nav:
            continue
        ts = _parse_iso(str(row["created_at"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if last_reject <= ts <= window_end:
            return True
    return False


def bucket_passes_misroute_gate(
    *,
    bucket: dict[str, Any],
    all_rows: list[dict[str, Any]],
    decay_days: int,
    now_iso: str | None = None,
) -> tuple[bool, float, str]:
    """Return (passes, avg_decay_factor, skip_reason). Defer-only buckets never pass."""
    now = _parse_iso(now_iso) if now_iso else datetime.now(timezone.utc)
    raw_rows = list(bucket.get("rows") or [])
    window_rows = _rows_in_decay_window(raw_rows, decay_days=decay_days, now=now)
    if not window_rows:
        return False, 0.0, "empty_window"

    reject_rows = [r for r in window_rows if str(r.get("action") or "").strip().lower() == "reject"]
    defer_only = bool(window_rows) and not reject_rows and all(
        str(r.get("action") or "").strip().lower() == "defer" for r in window_rows
    )
    if defer_only:
        return False, 0.0, "defer_only"

    weighted = _weighted_reject_sum(window_rows, decay_days=decay_days)
    if weighted < _MIN_WEIGHTED_REJECTS:
        return False, 0.0, "sparse_rejects"

    if _has_accept_in_bucket(window_rows):
        return False, 0.0, "contradictory_accept"

    hk = str(bucket.get("hint_kind") or "").strip()
    if not _has_retention_alignment(bucket_rows=window_rows, hint_kind=hk, all_rows=all_rows):
        return False, 0.0, "no_retention"

    reject_weights = [
        reject_decay_weight(age_days=float(r.get("_age_days", 0.0)), decay_days=decay_days)
        for r in reject_rows
    ]
    avg_decay = sum(reject_weights) / len(reject_weights) if reject_weights else 0.0
    return True, avg_decay, "gated"


def load_misroute_policy_weights(*, path: Path | None = None) -> dict[str, Any]:
    p = path or _WEIGHTS_PATH
    with _LOCK:
        if not p.is_file():
            return {}
        raw = json.loads(p.read_text(encoding="utf-8"))
        return dict(raw) if isinstance(raw, dict) else {}


def save_misroute_policy_weights(weights: dict[str, Any], *, path: Path | None = None) -> None:
    p = path or _WEIGHTS_PATH
    with _LOCK:
        p.write_text(json.dumps(weights, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _first_tiebreak_alternate(
    *,
    hint_kind: str,
    current_nav: str,
) -> SmartStudyPrimaryNav | None:
    hk = str(hint_kind or "").strip()
    alts = _POLICY_TIEBREAK_ALTERNATES.get(hk)  # type: ignore[arg-type]
    if not alts:
        return None
    cur = str(current_nav or "").strip()
    for alt in alts:
        if alt != cur:
            return alt
    return None


def _update_weight_entry(
    *,
    weights: dict[str, Any],
    bucket_key: str,
    passes: bool,
    weighted_rejects: float,
    avg_decay: float,
    now_iso: str,
    had_accept: bool,
) -> None:
    if had_accept:
        entry = weights.get(bucket_key)
        if isinstance(entry, dict):
            penalty = float(entry.get("nav_penalty") or 0.0)
            new_penalty = penalty * 0.5
            if new_penalty < 0.05:
                weights.pop(bucket_key, None)
            else:
                entry = dict(entry)
                entry["nav_penalty"] = new_penalty
                entry["updated_at"] = now_iso
                weights[bucket_key] = entry
        return

    if not passes:
        return

    penalty = min(1.0, weighted_rejects / _MIN_WEIGHTED_REJECTS) * max(avg_decay, 0.1)
    weights[bucket_key] = {
        "nav_penalty": round(penalty, 4),
        "reject_count": int(round(weighted_rejects)),
        "decay_factor": round(avg_decay, 4),
        "updated_at": now_iso,
    }


def refresh_misroute_policy_weights_from_buckets(
    *,
    buckets: list[dict[str, Any]],
    decay_days: int = 7,
    now_iso: str | None = None,
    weights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge offline learning snapshot from aggregated feedback buckets."""
    now = _parse_iso(now_iso) if now_iso else datetime.now(timezone.utc)
    ts = now.isoformat()
    merged = dict(weights or load_misroute_policy_weights())
    all_rows: list[dict[str, Any]] = []
    for bucket in buckets:
        all_rows.extend(list(bucket.get("rows") or []))

    for bucket in buckets:
        bkey = str(bucket.get("bucket_key") or "")
        if not bkey:
            continue
        window_rows = _rows_in_decay_window(
            list(bucket.get("rows") or []),
            decay_days=decay_days,
            now=now,
        )
        had_accept = _has_accept_in_bucket(window_rows)
        weighted = _weighted_reject_sum(window_rows, decay_days=decay_days)
        passes, avg_decay, _ = bucket_passes_misroute_gate(
            bucket=bucket,
            all_rows=all_rows,
            decay_days=decay_days,
            now_iso=ts,
        )
        _update_weight_entry(
            weights=merged,
            bucket_key=bkey,
            passes=passes,
            weighted_rejects=weighted,
            avg_decay=avg_decay,
            now_iso=ts,
            had_accept=had_accept,
        )
    return merged


def compute_offline_misroute_adjustments(
    *,
    hint_kind: str,
    primary_nav: str,
    weak_concept_sha256: str | None = None,
    buckets: list[dict[str, Any]] | None = None,
    decay_days: int = 7,
    now_iso: str | None = None,
    weights: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], MisroutePolicyAdjustment | None]:
    """Refresh weights from buckets (when provided) and return optional tie-break adjustment."""
    now = _parse_iso(now_iso) if now_iso else datetime.now(timezone.utc)
    ts = now.isoformat()
    current_weights = dict(weights) if weights is not None else load_misroute_policy_weights()
    if buckets is not None:
        current_weights = refresh_misroute_policy_weights_from_buckets(
            buckets=buckets,
            decay_days=decay_days,
            now_iso=ts,
            weights=current_weights,
        )

    bkey = misroute_bucket_key(
        hint_kind=hint_kind,
        primary_nav=primary_nav,
        weak_concept_sha256=weak_concept_sha256,
    )
    bucket = next((b for b in (buckets or []) if str(b.get("bucket_key") or "") == bkey), None)
    if bucket is None:
        return current_weights, None

    all_rows: list[dict[str, Any]] = []
    for b in buckets or []:
        all_rows.extend(list(b.get("rows") or []))

    passes, avg_decay, _ = bucket_passes_misroute_gate(
        bucket=bucket,
        all_rows=all_rows,
        decay_days=decay_days,
        now_iso=ts,
    )
    if not passes:
        return current_weights, None

    alt = _first_tiebreak_alternate(hint_kind=hint_kind, current_nav=primary_nav)
    if alt is None:
        return current_weights, None

    entry = current_weights.get(bkey) or {}
    nav_penalty = float(entry.get("nav_penalty") or 0.5)
    return current_weights, MisroutePolicyAdjustment(
        hint_kind=hint_kind,  # type: ignore[arg-type]
        original_primary_nav=primary_nav,  # type: ignore[arg-type]
        adjusted_primary_nav=alt,
        bucket_key=bkey,
        decay_factor=avg_decay,
        nav_penalty=nav_penalty,
    )


MisrouteAuditStatus = Literal["applied", "skipped"]


_NAV_SWAP_COPY: dict[tuple[str, str], tuple[str, str]] = {
    ("mastery_stale", "qa_continue"): (
        "Сначала свериться с источниками",
        " Локальная коррекция tie-break: сначала опора на выдержки из базы.",
    ),
    ("answer_ready", "safe_tutor_5min"): (
        "Короткая сессия с тьютором",
        " Локальная коррекция tie-break: спокойный пятиминутный вход в чат.",
    ),
    ("safe_default", "qa_continue"): (
        "Свериться с базой",
        " Локальная коррекция tie-break: короткая сверка перед длинным чатом.",
    ),
}


def _merge_ml_audit_ru(existing: str, tail: str) -> str:
    base = str(existing or "").strip()
    add = str(tail or "").strip()
    if not add:
        return base
    if not base:
        return add
    return f"{base}\n{add}"


def _nav_swap_presentation(*, hint_kind: str, new_nav: SmartStudyPrimaryNav, rule: SmartStudyRecommendation) -> tuple[str, str]:
    hk = str(hint_kind or "").strip()
    nav = str(new_nav or "").strip()
    pair = _NAV_SWAP_COPY.get((hk, nav))
    if pair:
        label, extra = pair
        why = rule.why_now_ru + extra if extra not in rule.why_now_ru else rule.why_now_ru
        return label, why
    return rule.primary_label_ru, rule.why_now_ru


def apply_ssr_misroute_policy_if_enabled(
    rule: SmartStudyRecommendation,
    *,
    weak_concept_sha256: str | None = None,
    first_weak_concept: str | None = None,
) -> SmartStudyRecommendation:
    """Runtime tie-break hook (sp2): after rules, before ML hybrid; never changes hint_kind."""
    settings = get_settings()
    if not getattr(settings, "ssr_misroute_policy_learning_enabled", False):
        return rule

    hk = str(rule.hint_kind or "").strip()
    if hk in _SSR_ML_NO_RULE_OVERRIDE:
        audit = build_misroute_policy_audit_ru(status="skipped", reason="hard_queue")
        return replace(rule, ml_audit_ru=_merge_ml_audit_ru(rule.ml_audit_ru, audit))

    from app.ssr_feedback_collection import weak_concept_sha256 as _weak_sha
    from app.user_state_ssr_feedback import aggregate_ssr_misroute_feedback_buckets

    wcd = str(weak_concept_sha256 or "").strip() or _weak_sha(first_weak_concept)
    decay_days = int(getattr(settings, "ssr_misroute_policy_decay_days", 7))

    try:
        since_days = max(decay_days, 1)
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        buckets = aggregate_ssr_misroute_feedback_buckets(since_iso=since)
        weights, adj = compute_offline_misroute_adjustments(
            hint_kind=hk,
            primary_nav=str(rule.primary_nav),
            weak_concept_sha256=wcd,
            buckets=buckets,
            decay_days=decay_days,
        )
        save_misroute_policy_weights(weights)
    except Exception:  # noqa: BLE001
        # Non-blocking: rule baseline preserved (Designer error state).
        return rule

    bkey = misroute_bucket_key(
        hint_kind=hk,
        primary_nav=str(rule.primary_nav),
        weak_concept_sha256=wcd,
    )
    if adj is None:
        bucket = next((b for b in buckets if str(b.get("bucket_key") or "") == bkey), None)
        reason = "sparse_rejects"
        if bucket is not None:
            _, _, reason = bucket_passes_misroute_gate(
                bucket=bucket,
                all_rows=[r for b in buckets for r in list(b.get("rows") or [])],
                decay_days=decay_days,
            )
        audit = build_misroute_policy_audit_ru(status="skipped", reason=reason, bucket=bkey)
        return replace(rule, ml_audit_ru=_merge_ml_audit_ru(rule.ml_audit_ru, audit))

    label, why = _nav_swap_presentation(hint_kind=hk, new_nav=adj.adjusted_primary_nav, rule=rule)
    audit = build_misroute_policy_audit_ru(
        status="applied",
        reason="gated",
        decay=adj.decay_factor,
        bucket=adj.bucket_key,
    )
    return replace(
        rule,
        primary_nav=adj.adjusted_primary_nav,
        primary_label_ru=label,
        why_now_ru=why,
        secondaries=_stable_secondaries(primary_nav=adj.adjusted_primary_nav),
        ml_audit_ru=_merge_ml_audit_ru(rule.ml_audit_ru, audit),
    )


def build_misroute_policy_audit_ru(
    *,
    status: MisrouteAuditStatus,
    reason: str,
    decay: float | None = None,
    bucket: str | None = None,
) -> str:
    """Russian concise ledger tail for sp2 hook (merged into ``ml_audit_ru``)."""
    parts = [f"misroute_policy={status}", f"reason={reason}"]
    if decay is not None:
        parts.append(f"decay={decay:.2f}")
    if bucket:
        parts.append(f"bucket={bucket}")
    if status == "applied":
        return "Коррекция по локальным отказам: смещение tie-break (" + "; ".join(parts) + ")."
    if reason == "hard_queue":
        return "Политика обучения: не меняет приоритет карточек, повторений и ошибок quiz."
    if reason in {"sparse_rejects", "no_retention", "empty_window"}:
        return "Политика обучения: rule-only — недостаточно согласованных отказов."
    if reason == "contradictory_accept":
        return "Политика обучения: rule-only — противоречивый accept в bucket."
    if reason == "defer_only":
        return "Политика обучения: rule-only — только defer без reject."
    return "Политика обучения: rule-only (" + "; ".join(parts) + ")."


__all__ = [
    "MisroutePolicyAdjustment",
    "MisrouteAuditStatus",
    "apply_ssr_misroute_policy_if_enabled",
    "bucket_passes_misroute_gate",
    "build_misroute_policy_audit_ru",
    "compute_offline_misroute_adjustments",
    "load_misroute_policy_weights",
    "misroute_bucket_key",
    "refresh_misroute_policy_weights_from_buckets",
    "reject_decay_weight",
    "save_misroute_policy_weights",
]
