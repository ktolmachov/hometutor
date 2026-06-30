"""Workstream A: регистрация/вход (JWT+bcrypt), 401/409/422, per-user изоляция state.

AUTH_ENABLED=false — поведение по умолчанию: contextvar остаётся None, существующие
(не auth-aware) тесты и роутеры не затрагиваются. Эти тесты явно включают AUTH_ENABLED=true
через env + reset_settings_cache(), чтобы не зависеть от глобального состояния процесса.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth_db, config, user_state, user_state_db
from app.auth_context import reset_current_user_id, set_current_user_id


@pytest.fixture()
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-prod")
    monkeypatch.setenv("AUTH_DB", str(tmp_path / "auth.db"))
    monkeypatch.setenv("USER_STATE_DB", str(tmp_path / "user_state.db"))
    config.reset_settings_cache()
    auth_db.reset_schema_cache_for_tests()
    user_state_db.reset_schema_cache_for_tests()
    yield
    config.reset_settings_cache()


@pytest.fixture()
def client(auth_env):
    from app.routers.auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


def test_register_login_me_happy_path(client):
    r = client.post("/auth/register", json={"email": "alice@example.com", "password": "password123"})
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["email"] == "alice@example.com"
    token = data["access_token"]

    r2 = client.post("/auth/login", json={"email": "alice@example.com", "password": "password123"})
    assert r2.status_code == 200

    r3 = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200
    assert r3.json()["email"] == "alice@example.com"


def test_login_wrong_password_returns_401(client):
    client.post("/auth/register", json={"email": "bob@example.com", "password": "password123"})
    r = client.post("/auth/login", json={"email": "bob@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_register_duplicate_email_returns_409(client):
    client.post("/auth/register", json={"email": "carl@example.com", "password": "password123"})
    r = client.post("/auth/register", json={"email": "carl@example.com", "password": "password123"})
    assert r.status_code == 409


def test_register_weak_password_returns_422(client):
    r = client.post("/auth/register", json={"email": "dana@example.com", "password": "short"})
    assert r.status_code == 422


def test_register_invalid_email_returns_422(client):
    r = client.post("/auth/register", json={"email": "not-an-email", "password": "password123"})
    assert r.status_code == 422


def test_me_without_token_requires_auth(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_with_garbage_token_returns_401(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert r.status_code == 401


def test_me_with_expired_token_returns_401(client):
    settings = config.get_settings()
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": "some-user-id",
        "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),
        "jti": "expired-jti",
    }
    token = jwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_state_isolation_between_users(auth_env):
    """Запись под user A не видна под user B; per-user путь user_state.db (app/user_state_db.py)."""
    token_a = set_current_user_id("user-a")
    try:
        user_state.set_kv("topic", "alpha")
    finally:
        reset_current_user_id(token_a)

    token_b = set_current_user_id("user-b")
    try:
        assert user_state.get_kv("topic") is None
        user_state.set_kv("topic", "beta")
        assert user_state.get_kv("topic") == "beta"
    finally:
        reset_current_user_id(token_b)

    token_a2 = set_current_user_id("user-a")
    try:
        assert user_state.get_kv("topic") == "alpha"
    finally:
        reset_current_user_id(token_a2)


def test_state_path_falls_back_to_base_without_user_context(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_STATE_DB", str(tmp_path / "user_state.db"))
    config.reset_settings_cache()
    assert user_state_db._resolve_state_db_path() == str(tmp_path / "user_state.db")


def test_auth_scope_is_noop_when_auth_disabled(monkeypatch):
    """Регресс: AUTH_ENABLED=false (default) — auth_scope не требует токен, contextvar не меняется."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    config.reset_settings_cache()
    from app.api_auth import auth_scope

    async def _run():
        agen = auth_scope(authorization=None)
        return await agen.__anext__()

    assert asyncio.run(_run()) is None
