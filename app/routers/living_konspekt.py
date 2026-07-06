from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app import workbench_service
from app.media_urls import normalize_video_url

router = APIRouter(prefix="/living-konspekt", tags=["living-konspekt"])


@router.get("/workbench/status")
def workbench_status() -> dict[str, int]:
    rows = workbench_service.load_rows()
    return {
        "sections": len(rows),
        "with_notes": sum(1 for row in rows if row.get("note")),
        "read": sum(1 for row in rows if row.get("read_at")),
    }


@router.get("/video-citation/open")
def open_video_citation(url: str, heading: str = "", source: str = "") -> RedirectResponse:
    """Track an Ask-the-Lecturer video citation click and redirect to the safe URL."""
    try:
        normalized = normalize_video_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target = normalized.with_timestamp() if normalized.is_youtube else normalized.canonical_url
    try:
        from app.event_tracking import track_event

        track_event(
            "ask_lecturer_video_citation_clicked",
            {
                "heading": heading[:160],
                "source": source[:160],
                "kind": normalized.kind,
            },
        )
    except Exception:  # noqa: BLE001 - analytics must not block the redirect
        pass
    return RedirectResponse(target, status_code=307)


__all__ = ["open_video_citation", "router", "workbench_status"]
