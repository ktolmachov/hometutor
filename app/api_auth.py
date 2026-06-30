from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException

from app.auth_context import reset_current_user_id, set_current_user_id
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


async def auth_scope(
    authorization: Annotated[str | None, Header()] = None,
):
    """Per-request user identity: ставит app.auth_context contextvar для длительности запроса.

    AUTH_ENABLED=false (default) → no-op, поведение идентично текущему single-user режиму
    (contextvar остаётся None → user_state_db резолвит старый путь data/user_state.db).
    AUTH_ENABLED=true → требует валидный Bearer JWT (см. app/auth_service.py).
    """
    from app import auth_db
    from app.auth_service import InvalidTokenError, decode_access_token

    settings = get_settings()
    if not settings.auth_enabled:
        yield None
        return

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user = auth_db.get_user_by_id(payload.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    jti = payload.get("jti", "")
    if jti and auth_db.is_session_revoked(jti):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user = dict(user)
    user["_jti"] = jti

    token_ref = set_current_user_id(user["id"])
    try:
        yield user
    finally:
        reset_current_user_id(token_ref)
