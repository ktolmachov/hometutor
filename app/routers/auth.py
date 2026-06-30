"""HTTP API регистрации/входа. Публичный роутер (без auth-гейта на /register, /login).

/me и /logout требуют действующий Bearer-токен через зависимость `auth_scope`
(см. app/api_auth.py). При AUTH_ENABLED=false весь модуль фактически не используется
UI (login-гейт выключен), но эндпойнты остаются доступны для прямых вызовов/тестов.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app import auth_db
from app.api_auth import auth_scope
from app.auth_models import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from app.auth_service import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate,
    issue_access_token,
    register,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def post_register(body: RegisterRequest) -> TokenResponse:
    try:
        user = register(body.email, body.password, body.display_name)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail="Email already registered") from exc
    token = issue_access_token(user.id)
    return TokenResponse(access_token=token, user=user)


@router.post("/login", response_model=TokenResponse)
def post_login(body: LoginRequest) -> TokenResponse:
    try:
        user = authenticate(body.email, body.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    token = issue_access_token(user.id)
    return TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=UserPublic)
def get_me(current_user: Annotated[dict | None, Depends(auth_scope)] = None) -> UserPublic:
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserPublic(
        id=current_user["id"],
        email=current_user["email"],
        display_name=current_user.get("display_name"),
    )


@router.post("/logout")
def post_logout(current_user: Annotated[dict | None, Depends(auth_scope)] = None) -> dict[str, str]:
    """Серверный отзыв: помечает текущую сессию (jti) revoked — auth_scope отклонит её повторно."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    jti = current_user.get("_jti")
    if jti:
        auth_db.revoke_session(jti)
        auth_db.log_event(current_user["id"], "logout", datetime.now(timezone.utc).isoformat())
    return {"status": "ok"}
