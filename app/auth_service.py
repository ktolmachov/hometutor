"""Бизнес-логика аутентификации: хэширование паролей (bcrypt), JWT access-токены,
регистрация и вход. Хранилище — app/auth_db.py (глобальная БД пользователей).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app import auth_db
from app.auth_models import UserPublic
from app.config import get_settings

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Базовая ошибка домена аутентификации (см. подклассы ниже)."""


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(raw: str) -> str:
    rounds = get_settings().bcrypt_rounds
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(raw.encode("utf-8"), salt).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def issue_access_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_access_ttl_min)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    auth_db.record_session(
        session_id=payload["jti"],
        user_id=user_id,
        issued_at=now.isoformat(),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat(),
    )
    return token


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc


def _to_public(user_row: dict) -> UserPublic:
    return UserPublic(id=user_row["id"], email=user_row["email"], display_name=user_row.get("display_name"))


def register(email: str, password: str, display_name: str | None) -> UserPublic:
    if auth_db.get_user_by_email(email):
        raise EmailAlreadyRegisteredError(f"email already registered: {email}")
    user_id = uuid.uuid4().hex
    now = _utc_now_iso()
    auth_db.create_user(
        user_id=user_id,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        created_at=now,
    )
    auth_db.log_event(user_id, "register", now)
    logger.info("auth_register user_id=%s", user_id)
    return _to_public(auth_db.get_user_by_id(user_id))


def authenticate(email: str, password: str) -> UserPublic:
    user = auth_db.get_user_by_email(email)
    now = _utc_now_iso()
    if not user or not verify_password(password, user["password_hash"]):
        auth_db.log_event(user["id"] if user else None, "login_fail", now)
        raise InvalidCredentialsError("invalid email or password")
    auth_db.touch_last_login(user["id"], now)
    auth_db.log_event(user["id"], "login_ok", now)
    return _to_public(user)


def get_public_user(user_id: str) -> UserPublic | None:
    user = auth_db.get_user_by_id(user_id)
    return _to_public(user) if user else None
