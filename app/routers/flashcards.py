"""HTTP API: flashcard decks, generation and SM-2 review (E12)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from app.api_helpers import record_api_error
from app.api_models import FlashcardDeckProgressResponse
from app.config import get_settings
from app.flashcard_service import (
    QUALITY_MAP,
    add_flashcard,
    count_due_flashcards,
    defer_overdue_flashcards_for_recovery,
    delete_flashcard,
    delete_flashcard_deck,
    export_deck_to_anki,
    generate_course_flashcards,
    generate_flashcards,
    get_due_flashcards,
    get_flashcard_deck,
    get_flashcard_deck_progress,
    get_flashcard_recovery_schedule,
    list_flashcard_decks,
    review_flashcard,
    save_deck,
    update_flashcard,
    undo_overdue_flashcards_recovery,
)
from app.guardrails import InputGuardrailError
from app.input_validation import build_error_detail, validate_llm_input_list, validate_llm_input_text
from app.path_safety import validate_data_relative_path

router = APIRouter(tags=["flashcards"])


def _load_e2e_payload(name: str) -> dict[str, Any]:
    pkg = Path(__file__).resolve().parents[1] / "offline_payloads" / name
    if not pkg.exists():
        pkg = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures" / "offline_payloads" / name
    return json.loads(pkg.read_text(encoding="utf-8"))


def _offline_flashcards_payload() -> dict[str, Any]:
    return _load_e2e_payload("scenario_06.json")


# ─────────────────────────────────────────────────────────────
# Request / Response models
# ─────────────────────────────────────────────────────────────


class FlashcardGenerateRequest(BaseModel):
    scope: str = Field(..., description="document | upload | course")
    identifier: str | None = Field(default=None, description="relative_path for scope=document")
    content: str | None = Field(default=None, description="pre-extracted text for scope=upload")
    source_paths: list[str] | None = Field(default=None, description="relative_paths for scope=course")
    course_id: str | None = None
    course_title: str | None = None
    folder_rel: str | None = None
    num_cards: int = Field(default=12, ge=5, le=20)


class FlashcardCardIn(BaseModel):
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    tags: str | None = None


class FlashcardSaveDeckRequest(BaseModel):
    name: str = Field(..., min_length=1)
    source_type: str = Field(default="document")
    source_identifier: str | None = None
    cards: list[FlashcardCardIn] = Field(
        ...,
        min_length=5,
        description="Минимум 5 карточек (E16 / US-15.1)",
    )


class FlashcardImportQuizDeckRequest(BaseModel):
    """Импорт колоды из завершённого scoped quiz (US-15.6); допускает 1+ карточек."""

    name: str = Field(..., min_length=1)
    source_identifier: str | None = Field(
        default=None,
        description="Идентификатор документа/сессии квиза для source_id в БД",
    )
    cards: list[FlashcardCardIn] = Field(..., min_length=1, max_length=40)


class FlashcardReviewRequest(BaseModel):
    card_id: int
    quality: int = Field(
        default=4,
        ge=0,
        le=5,
        description="SM-2 quality 0..5; при quality_label переопределяется",
    )
    quality_label: str | None = Field(
        default=None,
        description="again | hard | good | easy (переопределяет quality)",
    )


class FlashcardUpdateRequest(BaseModel):
    front: str | None = None
    back: str | None = None
    tags: str | None = None


class FlashcardAddRequest(BaseModel):
    deck_id: int
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    tags: str | None = None


class FlashcardRecoveryRequest(BaseModel):
    """Defer tail of due queue (E26-A / US-7.2 parity for flashcards)."""

    keep_limit: int = Field(default=7, ge=1, le=50)
    stagger_days: int = Field(default=5, ge=1, le=14)
    deck_id: int | None = None
    tags: str | None = None


# ─────────────────────────────────────────────────────────────
# Generation
# ─────────────────────────────────────────────────────────────


@router.post("/flashcards/generate")
def flashcards_generate(body: FlashcardGenerateRequest) -> dict[str, Any]:
    """Generate flashcard preview (not persisted). Returns cards for user to review/edit."""
    scope = (body.scope or "").strip().lower()
    if scope not in ("document", "upload", "course"):
        raise HTTPException(status_code=400, detail="scope must be 'document', 'upload' or 'course'")
    if scope == "document" and not body.identifier:
        raise HTTPException(status_code=400, detail="identifier (relative_path) required for scope=document")
    if scope == "upload" and not body.content:
        raise HTTPException(status_code=400, detail="content required for scope=upload")
    if scope == "course" and not body.source_paths:
        raise HTTPException(status_code=400, detail="source_paths required for scope=course")
    try:
        identifier = validate_llm_input_text(
            body.identifier,
            field_name="identifier",
            required=(scope == "document"),
            max_chars=512,
        )
        if scope == "document" and identifier is not None:
            identifier = validate_data_relative_path(identifier)
        content = validate_llm_input_text(
            body.content,
            field_name="content",
            required=(scope == "upload"),
            max_chars=200_000,
        )
        source_paths = validate_llm_input_list(
            body.source_paths,
            field_name="source_paths",
            max_items=50,
            max_chars=512,
        )
        if scope == "course":
            source_paths = [validate_data_relative_path(path) for path in (source_paths or [])]
        course_id = validate_llm_input_text(body.course_id, field_name="course_id", required=False, max_chars=128)
        course_title = validate_llm_input_text(
            body.course_title,
            field_name="course_title",
            required=False,
            max_chars=256,
        )
        folder_rel = validate_llm_input_text(body.folder_rel, field_name="folder_rel", required=False, max_chars=512)
    except InputGuardrailError as exc:
        raise HTTPException(status_code=400, detail=build_error_detail(exc.code, str(exc)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        if scope == "course":
            out = generate_course_flashcards(
                source_paths=source_paths or [],
                course_title=course_title or "Курс",
                course_id=course_id,
                folder_rel=folder_rel,
                num_cards_per_document=body.num_cards,
            )
            out["source_identifier"] = json.dumps(
                {"course_id": course_id, "folder_rel": folder_rel},
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            out = generate_flashcards(
                scope=scope,
                identifier=identifier,
                content=content,
                num_cards=body.num_cards,
            )
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/generate", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Flashcard generation failed")
    if not out.get("success"):
        raise HTTPException(status_code=400, detail=out.get("error") or "Generation failed")
    return out


# ─────────────────────────────────────────────────────────────
# Decks CRUD
# ─────────────────────────────────────────────────────────────


@router.post("/flashcards/decks", status_code=201)
def flashcards_save_deck(body: FlashcardSaveDeckRequest) -> dict[str, Any]:
    """Persist a new deck with its cards."""
    cards = [c.model_dump() for c in body.cards]
    try:
        result = save_deck(body.name, body.source_type, body.source_identifier, cards)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/decks", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to save deck")
    return result


@router.post("/flashcards/decks/import-quiz", status_code=201)
def flashcards_import_deck_from_quiz(body: FlashcardImportQuizDeckRequest) -> dict[str, Any]:
    """Сохранить колоду из вопросов квиза с source_type=quiz (US-15.6)."""
    cards = [c.model_dump() for c in body.cards]
    try:
        result = save_deck(body.name, "quiz", body.source_identifier, cards)
    except Exception as exc:  # noqa: BLE001
        record_api_error(endpoint="/flashcards/decks/import-quiz", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to import quiz deck")
    return result


@router.get("/flashcards/bootstrap")
def flashcards_bootstrap_endpoint() -> dict[str, Any]:
    """Return due_count + decks in one request — reduces Streamlit HTTP round-trips on rerun."""
    if get_settings().home_rag_e2e_offline:
        payload = _offline_flashcards_payload()
        return {"due_count": payload["deck"]["due_count"], "decks": [payload["deck"]]}
    try:
        decks = list_flashcard_decks()
        due = count_due_flashcards()
    except Exception as exc:  # noqa: BLE001
        record_api_error(endpoint="/flashcards/bootstrap", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to load bootstrap data")
    return {"due_count": due, "decks": decks}


@router.get("/flashcards/decks")
def flashcards_list_decks() -> dict[str, Any]:
    """List all decks with live due_count."""
    if get_settings().home_rag_e2e_offline:
        payload = _offline_flashcards_payload()
        return {"decks": [payload["deck"]]}
    try:
        decks = list_flashcard_decks()
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/decks", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to list decks")
    return {"decks": decks}


@router.get("/flashcards/decks/{deck_id}")
def flashcards_get_deck(deck_id: int) -> dict[str, Any]:
    """Return deck with all cards."""
    if get_settings().home_rag_e2e_offline:
        payload = _offline_flashcards_payload()
        deck = dict(payload["deck"])
        deck["cards"] = payload["cards"]
        return deck
    try:
        deck = get_flashcard_deck(deck_id)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint=f"/flashcards/decks/{deck_id}", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to get deck")
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck


@router.get(
    "/flashcards/decks/{deck_id}/progress",
    response_model=FlashcardDeckProgressResponse,
)
def flashcards_get_deck_progress(deck_id: int) -> dict[str, Any]:
    """Return mastered/total/percent progress for a deck."""
    if get_settings().home_rag_e2e_offline:
        return {"deck_id": deck_id, "mastered": 3, "total": 12, "percent": 25.0}
    try:
        if not get_flashcard_deck(deck_id):
            raise HTTPException(status_code=404, detail="Deck not found")
        return get_flashcard_deck_progress(deck_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint=f"/flashcards/decks/{deck_id}/progress", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to get deck progress")


@router.delete("/flashcards/decks/{deck_id}")
def flashcards_delete_deck(deck_id: int) -> dict[str, Any]:
    try:
        ok = delete_flashcard_deck(deck_id)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint=f"/flashcards/decks/{deck_id}", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to delete deck")
    if not ok:
        raise HTTPException(status_code=404, detail="Deck not found")
    return {"success": True}


# ─────────────────────────────────────────────────────────────
# Due / Review
# ─────────────────────────────────────────────────────────────


@router.get("/flashcards/due/count")
def flashcards_due_count(
    deck_id: int | None = Query(default=None),
    tags: str | None = Query(default=None),
) -> dict[str, Any]:
    """Lightweight endpoint for home-page badge."""
    if get_settings().home_rag_e2e_offline:
        return {"count": _offline_flashcards_payload()["deck"]["due_count"]}
    return {"count": count_due_flashcards(deck_id=deck_id, tags=tags)}


@router.get("/flashcards/due")
def flashcards_due(
    limit: int = 50,
    deck_id: int | None = Query(default=None),
    tags: str | None = Query(default=None),
) -> dict[str, Any]:
    """Cards with next_review <= now, ordered by next_review ASC."""
    limit = max(1, min(1000, limit))
    if get_settings().home_rag_e2e_offline:
        cards = _offline_flashcards_payload()["cards"][:limit]
        return {"cards": cards, "count": len(cards)}
    try:
        cards = get_due_flashcards(limit, deck_id=deck_id, tags=tags)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/due", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to fetch due cards")
    return {"cards": cards, "count": len(cards)}


@router.post("/flashcards/due/recovery")
def flashcards_due_recovery(
    body: FlashcardRecoveryRequest | None = Body(default=None),
) -> dict[str, Any]:
    """Move tail of due cards beyond ``keep_limit`` to staggered future ``next_review`` dates."""
    b = body or FlashcardRecoveryRequest()
    try:
        moved = defer_overdue_flashcards_for_recovery(
            keep_limit=b.keep_limit,
            stagger_days=b.stagger_days,
            deck_id=b.deck_id,
            tags=b.tags,
        )
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/due/recovery", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to defer due flashcards")
    return {"moved": moved}


@router.get("/flashcards/due/schedule")
def flashcards_due_schedule(
    deck_id: int | None = Query(default=None),
    tags: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return nearest scheduled reviews and whether recovery can be undone safely."""
    return get_flashcard_recovery_schedule(deck_id=deck_id, tags=tags)


@router.post("/flashcards/due/recovery/undo")
def flashcards_due_recovery_undo(
    body: FlashcardRecoveryRequest | None = Body(default=None),
) -> dict[str, Any]:
    """Return never-reviewed cards deferred by recovery back to the due queue."""
    b = body or FlashcardRecoveryRequest()
    try:
        restored = undo_overdue_flashcards_recovery(deck_id=b.deck_id, tags=b.tags)
    except Exception as exc:  # noqa: BLE001 - API boundary records controlled store failures.
        record_api_error(endpoint="/flashcards/due/recovery/undo", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to undo deferred flashcards")
    return {"restored": restored}


@router.post("/flashcards/review")
def flashcards_review(body: FlashcardReviewRequest) -> dict[str, Any]:
    """Apply SM-2 to a card. Returns updated state."""
    quality = body.quality
    if body.quality_label:
        label = body.quality_label.strip().lower()
        if label not in QUALITY_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"quality_label must be one of: {list(QUALITY_MAP)}",
            )
        quality = QUALITY_MAP[label]
    if get_settings().home_rag_e2e_offline:
        return {
            "success": True,
            "card_id": body.card_id,
            "quality": quality,
            "next_review": "2026-04-29T00:00:00+00:00",
            "interval_days": 4,
            "repetitions": 1,
            "ease_factor": 2.5,
        }
    try:
        result = review_flashcard(body.card_id, quality)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/review", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to process review")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ─────────────────────────────────────────────────────────────
# Card CRUD
# ─────────────────────────────────────────────────────────────


@router.put("/flashcards/cards/{card_id}")
def flashcards_update_card(card_id: int, body: FlashcardUpdateRequest) -> dict[str, Any]:
    try:
        ok = update_flashcard(card_id, body.front, body.back, body.tags)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint=f"/flashcards/cards/{card_id}", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to update card")
    if not ok:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"success": True}


@router.post("/flashcards/cards", status_code=201)
def flashcards_add_card(body: FlashcardAddRequest) -> dict[str, Any]:
    try:
        card_id = add_flashcard(body.deck_id, body.front, body.back, body.tags)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint="/flashcards/cards", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to add card")
    return {"card_id": card_id}


@router.delete("/flashcards/cards/{card_id}")
def flashcards_delete_card(card_id: int) -> dict[str, Any]:
    try:
        ok = delete_flashcard(card_id)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint=f"/flashcards/cards/{card_id}", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Failed to delete card")
    if not ok:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"success": True}


# ─────────────────────────────────────────────────────────────
# Anki export
# ─────────────────────────────────────────────────────────────


@router.get("/flashcards/decks/{deck_id}/export/anki")
def flashcards_export_anki(deck_id: int):
    """Download deck as Anki .apkg file."""
    from fastapi.responses import Response

    try:
        apkg_bytes, error = export_deck_to_anki(deck_id)
    except Exception as exc:  # noqa: BLE001 - flashcards API boundary records service/store failures as controlled HTTP errors.
        record_api_error(endpoint=f"/flashcards/decks/{deck_id}/export/anki", exc=exc, status_code=500)
        raise HTTPException(status_code=500, detail="Export failed")
    if error or not apkg_bytes:
        raise HTTPException(status_code=400, detail=error or "Export failed")
    return Response(
        content=apkg_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=deck_{deck_id}.apkg"},
    )


__all__ = ["router"]
