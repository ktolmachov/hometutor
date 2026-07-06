from __future__ import annotations

from fastapi import APIRouter

from app import workbench_service

router = APIRouter(prefix="/living-konspekt", tags=["living-konspekt"])


@router.get("/workbench/status")
def workbench_status() -> dict[str, int]:
    rows = workbench_service.load_rows()
    return {
        "sections": len(rows),
        "with_notes": sum(1 for row in rows if row.get("note")),
        "read": sum(1 for row in rows if row.get("read_at")),
    }


__all__ = ["router", "workbench_status"]
