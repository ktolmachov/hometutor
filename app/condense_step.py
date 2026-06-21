"""
Condense step: сжатие истории для multi-turn перед rewrite.

Совместим с ``QueryContext`` и ``run_step_safe`` из ``pipeline_steps``.
Результат: ``ctx.condensed_question`` и ``ctx.metadata[\"condensed_text\"]`` (без перезаписи
``rewritten_query``). ``rewrite_step`` читает ``condensed_text`` / ``condensed_question``.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.logging_config import log_event, setup_logging
from app.models import Message, QueryContext
from app.pipeline_steps import run_step_safe
from app.prompts import CONDENSE_PROMPT
from app.llm_resilience import complete_with_resilience
from app.provider import get_llm
from app.usage_cost import estimate_cost_usd, extract_token_usage

logger = setup_logging()


def _condense_window_for_ctx(ctx: QueryContext) -> int:
    """Окно истории для condense: шире в tutor mode (Socratic + quiz)."""
    s = get_settings()
    qm = (ctx.query_options.query_mode or "").strip().lower()
    if qm == "tutor":
        return s.condense_history_window_tutor
    return s.condense_history_window


def _condense_fallback(ctx: QueryContext) -> QueryContext:
    ctx.trace["condense"] = "fallback_original"
    log_event(
        logger,
        logging.WARNING,
        "condense_fallback",
        session_id=(ctx.session_id or "")[:8],
    )
    return ctx


def condense(ctx: QueryContext) -> QueryContext:
    """LLM: сжать последние сообщения; при ошибке — исключение (ловит run_step_safe)."""
    history: list[Message] = ctx.conversation_history
    window = _condense_window_for_ctx(ctx)
    ctx.trace["condense_history_window"] = window
    recent = history[-window:] if len(history) > window else history
    history_str = "\n".join(f"{msg.role}: {msg.content}" for msg in recent)
    prompt = CONDENSE_PROMPT.format(
        history=history_str,
        current_question=ctx.original_question,
    )
    settings = get_settings()
    llm = get_llm()
    response = complete_with_resilience(llm, prompt, stage="condense", temperature=0.0)
    condensed = response.text.strip()
    usage = extract_token_usage(response)

    if not condensed or len(condensed) < 10:
        raise ValueError("condensed text too short or empty")

    ctx.metadata["condensed_text"] = condensed
    ctx.condensed_question = condensed
    ctx.trace["condense"] = "success"
    preview = condensed[:200]
    ctx.trace["condensed_preview"] = preview + ("..." if len(condensed) > 200 else "")

    if usage:
        ctx.trace["condense_usage"] = usage
        ctx.trace["condense_estimated_cost_usd"] = estimate_cost_usd(
            settings.llm_model,
            usage,
        )

    log_event(
        logger,
        logging.INFO,
        "condense_ok",
        session_id=(ctx.session_id or "")[:8],
        preview_len=len(condensed),
    )
    return ctx


def condense_step(ctx: QueryContext) -> QueryContext:
    """Сжатие истории при активной сессии и достаточной длине диалога."""
    if not get_settings().enable_condense:
        ctx.trace["condense"] = "skipped_disabled"
        return ctx
    if not ctx.session_id:
        ctx.trace["condense"] = "skipped_no_session"
        return ctx
    if len(ctx.conversation_history) < 3:
        ctx.trace["condense"] = "skipped_too_short"
        return ctx

    return run_step_safe(condense, ctx, _condense_fallback)


__all__ = ["condense_step"]
