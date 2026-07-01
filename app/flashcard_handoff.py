"""Flashcard → Tutor fast-handoff contract (entrypoint, RAG overrides, quiz deferral)."""

from __future__ import annotations

from typing import Any

from app.flashcards_tag_display import source_path_from_card as _source_path_from_card
from app.models import PipelineOverrides, QueryOptions

FLASHCARD_HANDOFF_ENTRYPOINT = "flashcard_handoff"
# Plain-prose answer (key idea + example + check question). Russian tokenizes densely:
# a complete, well-formed answer measures ~150-170 qwen tokens (467 chars; cl100k 188 /
# o200k 118 on the live reference answer). The cap is a *ceiling*, not a target — the
# model emits EOS naturally at its own length, so a generous cap does NOT slow normal
# answers; it only catches runaway generation. Set it comfortably ABOVE the natural
# length so штатная проза never truncates mid-sentence (which would re-introduce the
# truncated-answer UX bug this package exists to fix — prose instead of raw JSON).
FLASHCARD_HANDOFF_MAX_OUTPUT_TOKENS = 220
FLASHCARD_HANDOFF_SESSION_KEYS = ("tutor_entrypoint",)
FLASHCARD_HANDOFF_SEED_ROUTE = "flashcard_seed"


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _build_seed_teaching_summary(*, front: str, back: str, topic: str, source_path: str) -> str:
    if not back:
        return (
            f"Разберем вопрос карточки: «{front or topic}».\n\n"
            "В карточке не найден сохраненный ответ, поэтому лучше открыть источник "
            "или задать уточняющий вопрос тьютору."
        )
    source_line = f"\n\nИсточник карточки: `{source_path}`." if source_path else ""
    return (
        f"Ключевая идея: {back}\n\n"
        f"Как связать с вопросом: карточка спрашивает «{front or topic}». "
        "Здесь важно не просто узнать формулировку, а понять, какую ошибку или риск "
        "она предотвращает.\n\n"
        "Короткий пример: представь, что ты применяешь эту идею в реальном сценарии. "
        "Если можешь объяснить, что изменится до/после применения понятия, значит смысл "
        f"уже схвачен.{source_line}"
    )


def is_flashcard_handoff(options: QueryOptions | None) -> bool:
    if options is None:
        return False
    return (getattr(options, "tutor_entrypoint", None) or "").strip() == FLASHCARD_HANDOFF_ENTRYPOINT


def flashcard_handoff_pipeline_overrides() -> PipelineOverrides:
    """Fast scoped retrieval for gap handoff; quality tutor chat unchanged."""
    return PipelineOverrides(
        rag_profile="fast",
        enable_reranker=False,
        similarity_top_k=2,
        retrieval_mode="vector_only",
    )


def flashcard_handoff_session_fields(card_topic: str | None = None) -> dict[str, object]:
    """Extra session-state keys applied on «Не знаю / Объясни» click."""
    out: dict[str, object] = {
        "tutor_entrypoint": FLASHCARD_HANDOFF_ENTRYPOINT,
    }
    topic = (card_topic or "").strip()
    if topic:
        out.setdefault("current_topic", topic)
    return out


def build_flashcard_handoff_seed(card: dict[str, Any]) -> dict[str, Any]:
    """Build an instant Tutor turn from the selected flashcard itself.

    The clicked card is the strongest available evidence for this UX path: it is the
    exact item the learner failed. Using it avoids a slow RAG round-trip whose top-k
    may be semantically adjacent but not the actual answer to the card.
    """
    front = _compact_text(card.get("front"), limit=420)
    back = _compact_text(card.get("back") or card.get("answer"), limit=1400)
    deck = _compact_text(card.get("deck_name"), limit=140)
    topic = _compact_text(card.get("topic") or deck or front or "карточка", limit=160)
    card_id = card.get("id")
    source_path = _source_path_from_card(card)

    user_content = f"Не знаю: {front}" if front else "Не знаю: объясни эту карточку"
    teaching_summary = _build_seed_teaching_summary(
        front=front,
        back=back,
        topic=topic,
        source_path=source_path,
    )

    what_understood = back[:220] if back else f"Нужно восстановить смысл карточки: {front or topic}."
    payload: dict[str, Any] = {
        "contract_version": 1,
        "answer_kind": "tutor_teaching_step",
        "teaching_summary": teaching_summary,
        "understanding_state": {
            "what_you_understood": what_understood,
            "risk_gaps": "Риск в том, что формулировка узнается пассивно, но не проговаривается своими словами.",
            "what_to_do_now": "Скажи ответ своими словами или сразу нажми «Проверить себя».",
        },
        "next_action": "Проверь меня",
        "next_action_reason": "Ты отметил карточку как непонятную; короткая проверка быстро покажет, закрепилась ли идея.",
        "check_question": f"Как бы ты объяснил своими словами: «{front or topic}»?",
        "suggested_ctas": [
            "Объясни проще",
            "Дай пример",
            "Проверь меня",
            "Углубить по источникам",
        ],
        "depth_level": "short",
        "trust_signals": {
            "sources_used": 1 if back else 0,
            "confidence": "high" if back else "low",
            "coverage_warning": None if back else "У карточки нет сохраненного ответа для мгновенного объяснения.",
        },
    }

    source_text = f"Вопрос: {front}\n\nОтвет: {back}".strip()
    sources = []
    if source_text:
        sources.append(
            {
                "file_name": source_path.rsplit("/", 1)[-1] if source_path else (
                    f"Карточка #{card_id}" if card_id is not None else "Карточка"
                ),
                "relative_path": source_path or None,
                "page": "flashcard",
                "score": 1.0 if back else None,
                "text": source_text,
                "route": FLASHCARD_HANDOFF_SEED_ROUTE,
                "rank_reason": "прямой ответ выбранной карточки",
                "cite_index": 1,
            }
        )

    tutor_meta = {
        "teaching": payload,
        "decision": {
            "route": "targeted_reinforcement",
            "focus_topic": topic,
            "action": {
                "next_action": payload["next_action"],
                "next_action_reason": payload["next_action_reason"],
            },
        },
        "tutor_pipeline": [
            {"step": "flashcard_seed", "status": "ok", "detail": "front/back instant handoff"}
        ],
        "suppress_smart_study_overlay": True,
    }
    assistant_metadata = {
        "tutor": tutor_meta,
        "tutor_answer": payload,
        "sources": sources,
        "debug": {
            "flashcard_handoff_seed": True,
            "card_id": card_id,
            "source": "flashcard_front_back",
        },
    }

    return {
        "user_content": user_content,
        "assistant_content": teaching_summary,
        "assistant_metadata": assistant_metadata,
        "topic": topic,
        "sources": sources,
    }


def clear_flashcard_handoff_session_fields(state: Any) -> None:
    """Clear one-shot handoff keys without touching normal tutor preferences."""
    for key in FLASHCARD_HANDOFF_SESSION_KEYS:
        state.pop(key, None)


def handoff_llm_with_output_cap(llm: Any) -> Any:
    """Ограничить max_tokens синтеза RAG для handoff (быстрее локальный LLM)."""
    cap = FLASHCARD_HANDOFF_MAX_OUTPUT_TOKENS
    existing = getattr(llm, "max_tokens", None)
    if existing is not None and existing <= cap:
        return llm
    try:
        if hasattr(llm, "model_copy"):
            return llm.model_copy(update={"max_tokens": cap})
    except Exception:  # noqa: BLE001 - best-effort cap; fallback to base llm
        pass
    try:
        cls = type(llm)
        kwargs: dict[str, Any] = {}
        for name in ("model", "api_key", "api_base", "temperature", "max_retries", "http_client"):
            val = getattr(llm, name, None)
            if val is not None:
                kwargs[name] = val
        kwargs["max_tokens"] = cap
        return cls(**kwargs)
    except Exception:  # noqa: BLE001 - unknown LLM wrapper; keep original
        return llm
