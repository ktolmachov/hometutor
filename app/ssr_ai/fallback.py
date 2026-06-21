"""Canonical SSR ML rerank fallback reason strings (L1 hybrid layer).

Consumers should use these constants so telemetry and audits stay aligned
across modules.
"""

from __future__ import annotations

from typing import Final

INFERENCE_EXCEPTION: Final[str] = "inference_exception"
LATENCY_BUDGET: Final[str] = "latency_budget"
EMPTY_PROBABILITIES: Final[str] = "empty_probabilities"
NO_ALLOWED_PROBABILITIES: Final[str] = "no_allowed_probabilities"
LOW_CONFIDENCE: Final[str] = "low_confidence"
APPLIED: Final[str] = "applied"
RULE_MATCH: Final[str] = "rule_match"
