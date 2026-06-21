"""Retrieval-mode comparison metrics (defense eval / US-12.7 infrastructure).

Pure deterministic helpers + ``RetrievalComparisonEngine`` for aggregating
per-query retrieval outcomes across ``vector_only``, ``hybrid``, ``bm25_only``,
``doc_then_chunk``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

RETRIEVAL_COMPARISON_MODES: tuple[str, ...] = (
    "vector_only",
    "hybrid",
    "bm25_only",
    "doc_then_chunk",
)


def calculate_recall_at_k(
    relevant_ids: set[str],
    retrieved_ids: Sequence[str],
    k: int,
) -> float:
    """Macro recall@k: |rel ∩ top_k| / |rel| (0 if no relevant ids)."""
    if k <= 0:
        return 0.0
    if not relevant_ids:
        return 0.0
    top = list(retrieved_ids[:k])
    hits = sum(1 for doc_id in top if doc_id in relevant_ids)
    return hits / len(relevant_ids)


def calculate_precision_at_k(
    relevant_ids: set[str],
    retrieved_ids: Sequence[str],
    k: int,
) -> float:
    """Precision@k: |rel ∩ top_k| / k (0 if k<=0, empty rel, or empty retrieved)."""
    if k <= 0:
        return 0.0
    if not relevant_ids:
        return 0.0
    if not retrieved_ids:
        return 0.0
    top = set(retrieved_ids[:k])
    hits = len(relevant_ids & top)
    return hits / k


def calculate_mrr(relevant_ids: set[str], retrieved_ids: Sequence[str]) -> float:
    """Standard MRR: reciprocal rank of first relevant hit."""
    if not relevant_ids:
        return 0.0
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def calculate_hit_rate(hit_flags: Sequence[bool]) -> float:
    """Fraction of queries with at least one relevant doc in retrieved list."""
    if not hit_flags:
        return 0.0
    return sum(1 for h in hit_flags if h) / len(hit_flags)


def latency_percentiles_ms(latencies_ms: Sequence[float]) -> tuple[float, float, float]:
    """Linear-interpolation p50 / p95 / p99 on sorted latencies (milliseconds)."""
    if not latencies_ms:
        return (0.0, 0.0, 0.0)
    srt = sorted(float(x) for x in latencies_ms)
    n = len(srt)

    def pct(p: float) -> float:
        if n == 1:
            return srt[0]
        idx = (n - 1) * (p / 100.0)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        w = idx - lo
        return srt[lo] * (1.0 - w) + srt[hi] * w

    return (pct(50.0), pct(95.0), pct(99.0))


@dataclass
class RetrievalModeResult:
    mode: str
    recall_at_k: dict[int, float] = field(default_factory=dict)
    precision_at_k: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0
    hit_rate: float = 0.0
    latency_ms_p50: float = 0.0
    latency_ms_p95: float = 0.0
    latency_ms_p99: float = 0.0


@dataclass
class RetrievalComparisonReport:
    results_by_mode: dict[str, RetrievalModeResult]
    winner_by_metric: dict[str, str]


RetrieverFn = Callable[[str, str], tuple[list[str], float]]


class RetrievalComparisonEngine:
    """Runs comparison across modes using an injected per-(mode, query) retriever."""

    def __init__(self, *, k_values: Sequence[int] | None = None) -> None:
        ks = tuple(k_values) if k_values is not None else (1, 3, 5, 10)
        self._k_values = tuple(sorted(set(int(k) for k in ks if int(k) > 0)))

    @property
    def k_values(self) -> tuple[int, ...]:
        return self._k_values

    def compare_modes(
        self,
        queries: Sequence[str],
        relevant_by_query: Sequence[Iterable[str]],
        retrieve: RetrieverFn,
        *,
        modes: Sequence[str] | None = None,
    ) -> RetrievalComparisonReport:
        mode_list = tuple(modes) if modes is not None else RETRIEVAL_COMPARISON_MODES
        if len(queries) != len(relevant_by_query):
            raise ValueError("queries and relevant_by_query must have the same length")

        results_by_mode: dict[str, RetrievalModeResult] = {}

        for mode in mode_list:
            recall_k_lists: dict[int, list[float]] = {k: [] for k in self._k_values}
            precision_k_lists: dict[int, list[float]] = {k: [] for k in self._k_values}
            mrr_list: list[float] = []
            hit_flags: list[bool] = []
            latencies: list[float] = []

            for query, rel in zip(queries, relevant_by_query):
                rel_set = {str(x) for x in rel}
                retrieved, latency_ms = retrieve(mode, query)
                retrieved_ids = [str(x) for x in retrieved]
                latencies.append(float(latency_ms))

                for k in self._k_values:
                    recall_k_lists[k].append(calculate_recall_at_k(rel_set, retrieved_ids, k))
                    precision_k_lists[k].append(
                        calculate_precision_at_k(rel_set, retrieved_ids, k)
                    )
                mrr_list.append(calculate_mrr(rel_set, retrieved_ids))
                hit_flags.append(any(doc_id in rel_set for doc_id in retrieved_ids))

            p50, p95, p99 = latency_percentiles_ms(latencies)
            n_q = len(queries)
            avg_recall = {
                k: (sum(recall_k_lists[k]) / n_q if n_q else 0.0) for k in self._k_values
            }
            avg_precision = {
                k: (sum(precision_k_lists[k]) / n_q if n_q else 0.0) for k in self._k_values
            }
            results_by_mode[mode] = RetrievalModeResult(
                mode=mode,
                recall_at_k=avg_recall,
                precision_at_k=avg_precision,
                mrr=sum(mrr_list) / n_q if n_q else 0.0,
                hit_rate=calculate_hit_rate(hit_flags),
                latency_ms_p50=p50,
                latency_ms_p95=p95,
                latency_ms_p99=p99,
            )

        winner_by_metric = _winners_from_results(results_by_mode, self._k_values)
        return RetrievalComparisonReport(
            results_by_mode=results_by_mode,
            winner_by_metric=winner_by_metric,
        )


def _winners_from_results(
    results_by_mode: Mapping[str, RetrievalModeResult],
    k_values: Sequence[int],
) -> dict[str, str]:
    winners: dict[str, str] = {}

    for k in k_values:
        recall_key = f"recall@{k}"
        best_recall = max(
            results_by_mode.items(),
            key=lambda item: item[1].recall_at_k.get(k, 0.0),
        )[0]
        winners[recall_key] = best_recall

        precision_key = f"precision@{k}"
        best_precision = max(
            results_by_mode.items(),
            key=lambda item: item[1].precision_at_k.get(k, 0.0),
        )[0]
        winners[precision_key] = best_precision

    best_mrr = max(results_by_mode.items(), key=lambda item: item[1].mrr)[0]
    winners["mrr"] = best_mrr

    best_hit = max(results_by_mode.items(), key=lambda item: item[1].hit_rate)[0]
    winners["hit_rate"] = best_hit

    best_lat = min(results_by_mode.items(), key=lambda item: item[1].latency_ms_p50)[0]
    winners["latency_ms_p50"] = best_lat

    return winners
