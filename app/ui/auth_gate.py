"""Streamlit login-гейт: формы Вход/Регистрация, статус сессии, проброс user_id в contextvar.

Активен только при `Settings.auth_enabled=True` (вызывается из app/ui/main.py). При выключенном
флаге UI работает как раньше — без логина, без contextvar (старый single-user путь state-БД).
"""
from __future__ import annotations

import logging

import requests
import streamlit as st

from app.auth_context import set_current_user_id
from app.config import get_settings
from app.ui_client import post_json_no_raise

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_KEY = "access_token"
_USER_ID_KEY = "user_id"
_USER_EMAIL_KEY = "user_email"


def is_authenticated() -> bool:
    return bool(st.session_state.get(_ACCESS_TOKEN_KEY) and st.session_state.get(_USER_ID_KEY))


def current_user_id() -> str | None:
    return st.session_state.get(_USER_ID_KEY)


def logout() -> None:
    for key in (_ACCESS_TOKEN_KEY, _USER_ID_KEY, _USER_EMAIL_KEY):
        st.session_state.pop(key, None)


def apply_ui_auth_context() -> None:
    """Ставит contextvar user_id для текущего Streamlit rerun (однопоточный per-run, безопасно)."""
    set_current_user_id(current_user_id())


def ensure_streamlit_auth_context() -> None:
    """Проброс user_id в contextvar перед операциями с user_state из UI-слоя.

    Без этого при ``AUTH_ENABLED=true`` запись может уйти в глобальный ``user_state.db``,
    а чтение после перезапуска — из per-user БД (настройки «сбрасываются»).
    """
    try:
        _ = st.session_state
    except Exception:  # noqa: BLE001 - вне Streamlit runtime (тесты/CLI) — no-op
        return
    apply_ui_auth_context()


def require_ui_auth_or_stop() -> None:
    """Гейт для каждого Streamlit-entrypoint (главная + страницы в app/ui/pages/).

    При AUTH_ENABLED=false — no-op (старое single-user поведение). При true — без логина
    рисует форму входа и останавливает скрипт; иначе ставит contextvar user_id на этот rerun.
    """
    if get_settings().auth_enabled and not is_authenticated():
        render_auth_gate()
        st.stop()
    apply_ui_auth_context()


def _call_auth_endpoint(path: str, email: str, password: str, display_name: str | None = None) -> dict | None:
    payload: dict[str, str] = {"email": email, "password": password}
    if display_name:
        payload["display_name"] = display_name
    try:
        resp = post_json_no_raise(path, payload, timeout=15)
    except requests.RequestException as exc:
        st.error(f"Не удалось связаться с сервером: {exc}")
        return None
    if resp.status_code == 409:
        st.error("Этот email уже зарегистрирован.")
        return None
    if resp.status_code == 401:
        st.error("Неверный email или пароль.")
        return None
    if resp.status_code == 422:
        st.error("Проверьте email и пароль (минимум 8 символов).")
        return None
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        st.error(f"Ошибка сервера: {exc}")
        return None
    return resp.json()


def _apply_token_response(data: dict) -> None:
    st.session_state[_ACCESS_TOKEN_KEY] = data["access_token"]
    st.session_state[_USER_ID_KEY] = data["user"]["id"]
    st.session_state[_USER_EMAIL_KEY] = data["user"]["email"]


def render_auth_gate() -> None:
    """Полноэкранная форма входа/регистрации. Вызывающий код должен сделать st.stop() после."""
    st.title("🎓 Home RAG Tutor")
    st.caption("Войдите или зарегистрируйтесь, чтобы продолжить.")
    tab_login, tab_register = st.tabs(["Вход", "Регистрация"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Пароль", type="password", key="login_password")
            submitted = st.form_submit_button("Войти", width="stretch")
        if submitted:
            data = _call_auth_endpoint("/auth/login", email.strip(), password)
            if data:
                _apply_token_response(data)
                st.rerun()

    with tab_register:
        with st.form("register_form"):
            email_r = st.text_input("Email", key="register_email")
            name_r = st.text_input("Имя (опционально)", key="register_name")
            password_r = st.text_input("Пароль (минимум 8 символов)", type="password", key="register_password")
            submitted_r = st.form_submit_button("Зарегистрироваться", width="stretch")
        if submitted_r:
            data = _call_auth_endpoint("/auth/register", email_r.strip(), password_r, name_r.strip() or None)
            if data:
                _apply_token_response(data)
                st.success("Регистрация успешна!")
                st.rerun()


def render_account_status_sidebar() -> None:
    """Краткий блок «Вы вошли как …» + кнопка выхода для боковой панели."""
    email = st.session_state.get(_USER_EMAIL_KEY)
    if not email:
        return
    st.caption(f"Вы вошли как **{email}**")
    if st.button("Выйти", key="auth_logout_btn", width="stretch"):
        logout()
        st.rerun()
