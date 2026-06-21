"""Background pre-generation of SSR explanations.

Asynchronously generate explanations for known recommendations to populate the cache
before the user navigates to the home page. Reduces latency, increases cache hit rate.

Usage:
    from app.ssr_pregeneration import trigger_ssr_pregeneration_async
    # After quiz/flashcard session ends or on any context where next recommendation is known:
    trigger_ssr_pregeneration_async(rec, evidence_ledger=..., weak_concept=...)
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.smart_study_router import SmartStudyRecommendation

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ssr_pregen_")


def trigger_ssr_pregeneration_async(
    rec: "SmartStudyRecommendation",
    *,
    evidence_ledger: list[str] | None = None,
    tutor_topic: str | None = None,
    weak_concept: str | None = None,
    primary_topic_hint: str | None = None,
    timeout_sec: float = 8.0,
) -> None:
    """Queue an explanation for background generation (non-blocking).

    Submits to a single-threaded executor. If the task times out or fails,
    it's silently ignored (user experience unaffected; next load triggers a new attempt).

    Use this after quiz/flashcard sessions or whenever you know the next recommendation
    and want to pre-warm the explanation cache.
    """
    timed_out = threading.Event()

    def _gen():
        try:
            from app.ssr_context_builder import build_ssr_llm_learning_context
            from app.ssr_explain_service import stream_explanation_tokens

            ctx = build_ssr_llm_learning_context(
                rec,
                evidence_ledger=evidence_ledger,
                tutor_topic=tutor_topic,
                weak_concept=weak_concept,
                primary_topic_hint=primary_topic_hint,
            )
            "".join(
                stream_explanation_tokens(
                    ctx,
                    hint_kind=rec.hint_kind,
                    primary_label_ru=rec.primary_label_ru,
                    why_now_ru=rec.why_now_ru,
                    primary_nav=rec.primary_nav,
                    route_pedagogy_ru=rec.route_pedagogy_ru,
                    ml_audit_ru=rec.ml_audit_ru,
                    has_secondaries=bool(rec.secondaries),
                    evidence_ledger=evidence_ledger,
                )
            )
            if timed_out.is_set():
                return
            logger.debug("ssr_pregeneration_success", extra={"hint_kind": str(rec.hint_kind)})
            try:
                from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

                record_ssr_ai_auxiliary_event(
                    level="L2",
                    category="pregeneration",
                    detail={"status": "success", "hint_kind": str(rec.hint_kind)},
                )
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "ssr_pregeneration_failed",
                extra={"error": str(exc)[:100], "hint_kind": str(rec.hint_kind)},
            )
            try:
                from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

                record_ssr_ai_auxiliary_event(
                    level="L2",
                    category="pregeneration",
                    detail={"status": "failed", "hint_kind": str(rec.hint_kind), "error": str(exc)[:120]},
                )
            except Exception:  # noqa: BLE001
                pass

    try:
        _EXECUTOR.submit(_gen).result(timeout=timeout_sec)
    except TimeoutError:
        timed_out.set()
        logger.debug("ssr_pregeneration_timeout")
        try:
            from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

            record_ssr_ai_auxiliary_event(
                level="L2",
                category="pregeneration",
                detail={"status": "timeout", "hint_kind": str(rec.hint_kind)},
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass  # Never raise; pre-generation is opportunistic


def shutdown_pregeneration_executor() -> None:
    """Called on app shutdown to gracefully close the executor."""
    try:
        _EXECUTOR.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass
