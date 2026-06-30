"""Интеграционные тесты против РЕАЛЬНОГО app.api.app (не mini-app из test_auth.py).

Закрывают P2-находку аудита: test_state_isolation_between_users в test_auth.py дёргает
set_current_user_id напрямую в одном потоке и не проверяет реальный продакшн-путь —
auth_scope (async dependency) ставит contextvar, а sync `def`-роуты FastAPI исполняются
в отдельном threadpool-потоке (anyio.to_thread.run_sync). Эти тесты гоняют именно этот путь.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth_db, config, user_state_db


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
def real_client(auth_env):
    """TestClient на реальном app.api.app (со всеми protected-роутерами и _protected_dependencies)."""
    from app.api import app as real_app

    return TestClient(real_app)


def _register(client: TestClient, email: str) -> str:
    r = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_protected_route_401_without_token_200_with_token_on_real_app(real_client):
    """Реальный protected-роутер (/sessions) отдаёт 401 без токена и 200 с валидным токеном."""
    r_no_token = real_client.get("/sessions")
    assert r_no_token.status_code == 401

    r_bad_token = real_client.get("/sessions", headers={"Authorization": "Bearer not-a-jwt"})
    assert r_bad_token.status_code == 401

    token = _register(real_client, "isolation-401@example.com")
    r_ok = real_client.get("/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r_ok.status_code == 200


def test_state_isolation_via_real_app_threadpool(real_client):
    """Per-user state изолирован на реальном пути: async auth_scope -> threadpool sync-роут.

    /learner/goal-snapshot (app/routers/learner.py) — обычный `def` (sync) эндпойнт,
    защищён `_protected_dependencies`, читает/пишет per-user user_state.db.
    Если contextvar, выставленный async-зависимостью auth_scope, не долетал бы до
    threadpool-потока, в котором FastAPI исполняет sync-роут, оба пользователя писали бы
    в один и тот же файл/контекст (либо в общий fallback-путь без user_id).
    """
    token_a = _register(real_client, "alice-iso@example.com")
    token_b = _register(real_client, "bob-iso@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    r = real_client.put("/learner/goal-snapshot", json={"topic": "alpha"}, headers=headers_a)
    assert r.status_code == 200, r.text

    r = real_client.put("/learner/goal-snapshot", json={"topic": "beta"}, headers=headers_b)
    assert r.status_code == 200, r.text

    r_a = real_client.get("/learner/goal-snapshot", headers=headers_a)
    assert r_a.status_code == 200
    assert r_a.json()["goal_context"]["topic"] == "alpha"

    r_b = real_client.get("/learner/goal-snapshot", headers=headers_b)
    assert r_b.status_code == 200
    assert r_b.json()["goal_context"]["topic"] == "beta"


def test_logout_revokes_session_then_token_is_rejected(real_client):
    """P2.3: logout помечает сессию revoked в auth_db, auth_scope отклоняет дальнейшие запросы."""
    token = _register(real_client, "logout-revoke@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    assert real_client.get("/auth/me", headers=headers).status_code == 200

    r_logout = real_client.post("/auth/logout", headers=headers)
    assert r_logout.status_code == 200

    r_after = real_client.get("/auth/me", headers=headers)
    assert r_after.status_code == 401

    r_protected_after = real_client.get("/sessions", headers=headers)
    assert r_protected_after.status_code == 401


def test_is_session_revoked_unknown_session_is_fail_open(auth_env):
    """Документирует поведение auth_db.is_session_revoked для неизвестного jti (см. docstring там)."""
    assert auth_db.is_session_revoked("never-issued-jti") is False
    assert auth_db.is_session_revoked("") is False
