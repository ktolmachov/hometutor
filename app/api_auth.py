from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException

from app.config import get_settings


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Require X-API-Key only when HOME_RAG_API_KEY/API_KEY is configured."""

    expected = (get_settings().home_rag_api_key or "").strip()
    if not expected:
        return
    if (x_api_key or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
