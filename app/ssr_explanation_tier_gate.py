"""Tiered explanation gate for SSR: template-only vs LLM enrichment.

Decides whether the SSR card's "why now" explanation needs LLM enrichment
(tier = ``llm_enriched``) or can use the static template string directly
(tier = ``template_only``).

The tier decision is a pure function: no state, no IO, no LLM calls. It
counts influencing signals in the evidence ledger and checks for contrastive
or steering-conflict flags that indicate complex evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExplanationTier = Literal["template_only", "llm_enriched"]


@dataclass(frozen=True)
class TierDecision:
    """Result of the tier gate decision for SSR explanation.

    Attributes:
        tier: One of ``template_only`` (no LLM needed) or
            ``llm_enriched`` (LLM may improve the explanation).
        reason: Human-readable summary for profiling / traces.
        signal_count: Number of influencing signals counted in the
            evidence ledger (0 if no ledger available).
    """

    tier: ExplanationTier
    reason: str
    signal_count: int


def decide_explanation_tier(
    evidence_ledger_lines: list[str] | None,
    *,
    hint_kind: str | None = None,
    primary_nav: str | None = None,
    has_contrastive: bool = False,
    has_steering_conflict: bool = False,
    has_debt_label: bool = False,
) -> TierDecision:
    """Decide whether to use template-only or LLM enrichment for SSR explanation.

    Rules
    -----
    **Simple evidence** → ``template_only``:
        - ≤2 influencing ledger signals **AND**
        - no contrastive block (``has_contrastive`` is False) **AND**
        - no debt + steering conflict.

    **Complex evidence** → ``llm_enriched``:
        - ≥3 influencing ledger signals, **OR**
        - contrastive "why not others" required, **OR**
        - learning-debt label with steering conflict.

    Parameters
    ----------
    evidence_ledger_lines:
        Human-readable lines from ``finalize_smart_study_confidence_ledger_lines``.
        Each line is a separate signal. Lines whose prefix contains "не влияет",
        "не задействован", "нет срочных" or similar negatives are excluded
        from the influencing count.
    hint_kind:
        SSR hint_kind from the recommendation (used only for debug logging).
    primary_nav:
        SSR primary_nav from the recommendation (used only for debug logging).
    has_contrastive:
        Whether contrastive "why not others" label is required.
    has_steering_conflict:
        Whether steering preference conflicts with a learning-debt label.
    has_debt_label:
        Whether the current recommendation carries a learning-debt label
        (e.g. hint_kind is ``quiz_failed``, ``mastery_stale``, or the
        primary_nav is ``tutor_weak_gap``, ``quiz_recovery_tutor``).

    Returns
    -------
    TierDecision
        Frozen dataclass with ``tier``, ``reason``, and ``signal_count``.
    """
    count = _count_influencing_signals(evidence_ledger_lines)

    # Complex: ≥3 signals
    if count >= 3:
        return TierDecision(
            tier="llm_enriched",
            reason=f"{count} influencing ledger signals (≥3) → LLM enrichment",
            signal_count=count,
        )

    # Complex: contrastive required
    if has_contrastive:
        return TierDecision(
            tier="llm_enriched",
            reason="contrastive 'why not others' required → LLM enrichment",
            signal_count=count,
        )

    # Complex: debt + steering conflict
    if has_debt_label and has_steering_conflict:
        return TierDecision(
            tier="llm_enriched",
            reason="debt label + steering conflict → LLM enrichment",
            signal_count=count,
        )

    # Simple: ≤2 signals, no contrastive, no debt+steering conflict
    return TierDecision(
        tier="template_only",
        reason=f"{count} influencing signals, no contrastive, no debt-steering conflict → template only",
        signal_count=count,
    )


def _count_influencing_signals(lines: list[str] | None) -> int:
    """Count signals that actively influenced the SSR recommendation.

    A signal is considered *non-influencing* when it contains a Russian
    clause indicating irrelevance: "не влияет", "не задействован",
    "нет срочных", "нет сохранённого", or similar.
    """
    if not lines:
        return 0
    count = 0
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if _is_non_influencing(text):
            continue
        count += 1
    return count


def _is_non_influencing(text: str) -> bool:
    """Check if a ledger line indicates a non-influencing signal."""
    low = text.lower()
    non_influencing_markers = (
        "не влияет",
        "не задействован",
        "нет срочных",
        "нет сохранённого",
        "нет дополнительных",
        "0 к повтору",
        "не влияет на маршрут",
        # General "нет" or "0" signals at end of line (after ":") are non-influencing
        ": 0",
        "): нет",
    )
    for marker in non_influencing_markers:
        if marker in low:
            return True
    return False
