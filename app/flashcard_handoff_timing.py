"""Timing events and session markers for Flashcard → Tutor handoff (P0 baseline)."""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping, MutableMapping

from app.logging_config import log_event

logger = logging.getLogger(__name__)

CLICK_MONO_KEY = "_fc_handoff_click_mono"
TUTOR_MOUNT_MONO_KEY = "_fc_handoff_tutor_mount_mono"
CARD_ID_KEY = "_fc_handoff_card_id"
TOPIC_KEY = "_fc_handoff_topic"
ANSWER_READY_KEY = "_fc_handoff_answer_ready_logged"


def record_handoff_click(
    state: MutableMapping[str, Any],
    *,
    card_id: int | str,
    topic: str,
) -> None:
    """Store monotonic click time; emit ``flashcard_tutor_handoff_started``."""
    now = time.perf_counter()
    state[CLICK_MONO_KEY] = now
    state.pop(TUTOR_MOUNT_MONO_KEY, None)
    state.pop(ANSWER_READY_KEY, None)
    state[CARD_ID_KEY] = card_id
    state[TOPIC_KEY] = topic
    log_event(
        logger,
        logging.INFO,
        "flashcard_tutor_handoff_started",
        card_id=card_id,
        topic=topic,
    )


def record_handoff_tutor_mount(state: MutableMapping[str, Any]) -> float | None:
    """First tutor-tab render after handoff; returns ``navigation_ms`` if click was recorded."""
    click_mono = state.get(CLICK_MONO_KEY)
    if click_mono is None or state.get(TUTOR_MOUNT_MONO_KEY) is not None:
        return None
    mount_mono = time.perf_counter()
    state[TUTOR_MOUNT_MONO_KEY] = mount_mono
    navigation_ms = round(max(0.0, (mount_mono - float(click_mono)) * 1000), 3)
    log_event(
        logger,
        logging.INFO,
        "flashcard_tutor_handoff_navigation",
        navigation_ms=navigation_ms,
        card_id=state.get(CARD_ID_KEY),
        topic=state.get(TOPIC_KEY),
    )
    return navigation_ms


def handoff_active(state: Mapping[str, Any]) -> bool:
    return state.get(CLICK_MONO_KEY) is not None and not state.get(ANSWER_READY_KEY)


def log_handoff_answer_ready(
    state: MutableMapping[str, Any],
    *,
    api_debug: Mapping[str, Any] | None = None,
) -> None:
    """Emit ``flashcard_tutor_handoff_answer_ready`` with UI + API latency envelope."""
    if not handoff_active(state):
        return
    click_mono = float(state.get(CLICK_MONO_KEY) or 0.0)
    mount_mono = state.get(TUTOR_MOUNT_MONO_KEY)
    now = time.perf_counter()
    navigation_ms = (
        round(max(0.0, (float(mount_mono) - click_mono) * 1000), 3)
        if mount_mono is not None
        else None
    )
    answer_ms = round(max(0.0, (now - click_mono) * 1000), 3)
    dbg = dict(api_debug or {})
    payload: dict[str, Any] = {
        "card_id": state.get(CARD_ID_KEY),
        "topic": state.get(TOPIC_KEY),
        "navigation_ms": navigation_ms,
        "answer_ready_ms": answer_ms,
        "engine_build_ms": dbg.get("engine_build_ms"),
        "retrieval_ms": dbg.get("retrieval_ms"),
        "llm_ms": dbg.get("llm_ms"),
        "rag_ms": dbg.get("rag_ms"),
        "post_processing_ms": dbg.get("post_processing_ms"),
        "auto_quiz_ms": dbg.get("auto_quiz_ms"),
        "inline_quiz_ms": dbg.get("inline_quiz_ms"),
        "total_ms": dbg.get("total_answer_ms") or dbg.get("total_ms"),
        "cache_hit": dbg.get("cache_hit"),
    }
    log_event(logger, logging.INFO, "flashcard_tutor_handoff_answer_ready", **payload)
    state[ANSWER_READY_KEY] = True


def clear_handoff_timing(state: MutableMapping[str, Any]) -> None:
    for key in (CLICK_MONO_KEY, TUTOR_MOUNT_MONO_KEY, CARD_ID_KEY, TOPIC_KEY, ANSWER_READY_KEY):
        state.pop(key, None)
