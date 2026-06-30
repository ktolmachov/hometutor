# План доработки hometutor под требования проектной работы

> Документ-задание для исполнителя (другой LLM/разработчика). Цель — закрыть обязательные
> требования рубрики и перейти из статуса «Возвращено на доработку» в «Принято».
> Защита идёт по двум репозиториям вместе: **`hometutor`** (runtime, этот репо) и
> **`hometutor-studio`** (процесс, backlog, user stories, промпты).

## 0. Контекст и инвариантные ограничения

Стек (НЕ менять): Python 3.11, FastAPI (`app/api.py`, `main.py`), Streamlit UI (`app/ui/main.py`),
Chroma + BM25 retrieval, SQLite state. **PostgreSQL-миграция в этот объём НЕ входит** (согласовано).

Архитектурные правила репозитория (соблюдать, см. `docs/architecture.md`):
- UI тонкий → бизнес-логика в сервисах; роутеры тонкие (валидация/shape/вызов сервиса).
- Конфиг только через `get_settings()`.
- Доступ к state-таблицам только через `app/user_state*.py`, не ad-hoc SQL в UI/роутерах.

Ключевые факты кода (проверены):
- `app/user_state_db.py::_connect()` (стр. ~285) — **единственная** точка резолва пути к state-БД:
  `raw = (get_settings().user_state_db or "").strip() or <repo>/data/user_state.db`.
  Кэши `_DB_SCHEMA_APPLIED` / `_DB_PRAGMA_APPLIED` ключуются по пути → разные файлы получают
  схему автоматически. **Это точка внедрения per-user изоляции.**
- `app/api.py:274` — `_protected_dependencies = [Depends(require_api_key)]`, применяется ко всем
  роутерам кроме `core` и `ssr`.
- `app/ui_client.py::_auth_headers()` добавляет `X-API-Key`; сюда же добавим `Authorization: Bearer`.
- `app/ui/main.py`: `st.set_page_config(...)` (стр. 76) → `_init_state()` (стр. 81) → сайдбар → диспетч вью.
  Login-гейт ставится между `_init_state()` и сайдбаром через `st.stop()`.
- 50 тестов (`tests/`) зовут protected-эндпойнты **без** авторизации → весь auth под флагом
  `AUTH_ENABLED` (default `false`). При `false` поведение идентично текущему (single-user).

Порядок исполнения (зависимости): **A (auth) → E (метрика, независим) → B (CI) → C (деплой) → D (доки)**.
B без A даст зелёный pipeline; C требует A (логин на проде); D финализирует.

---

## Workstream A — Аутентификация (FastAPI + JWT + bcrypt, привязка state к user_id)

### A0. Зависимости
В `requirements.txt` добавить:
```
PyJWT==2.10.1
bcrypt==4.3.0
email-validator==2.2.0   # для pydantic EmailStr
```
(Не использовать passlib — он тянет конфликтующие версии; bcrypt напрямую достаточно.)

### A1. Настройки — `app/config.py` (класс `Settings`, рядом с `home_rag_api_key`)
Добавить поля:
```python
auth_enabled: bool = False
jwt_secret: str = Field(default="dev-insecure-change-me", validation_alias=AliasChoices("JWT_SECRET"))
jwt_algorithm: str = "HS256"
jwt_access_ttl_min: int = Field(default=60 * 24 * 7, ge=5, le=60 * 24 * 30)  # 7 дней
auth_db: str = str(DATA_DIR / "auth.db")            # ГЛОБАЛЬНАЯ таблица пользователей
bcrypt_rounds: int = Field(default=12, ge=4, le=15)
```
В `config.env` задокументировать дефолты; реальный `JWT_SECRET` — только в `.env` (не коммитить).

### A2. Контекст текущего пользователя — НОВЫЙ `app/auth_context.py`
Без зависимостей на config/db (во избежание циклов):
```python
from __future__ import annotations
import contextvars
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)

def get_current_user_id() -> str | None:
    return _current_user_id.get()

def set_current_user_id(user_id: str | None):
    return _current_user_id.set(user_id)      # вернёт token для reset

def reset_current_user_id(token) -> None:
    _current_user_id.reset(token)
```

### A3. Per-user изоляция state — правка `app/user_state_db.py::_connect()`
Заменить тело резолва пути на:
```python
from app.auth_context import get_current_user_id

def _resolve_state_db_path() -> str:
    configured = (get_settings().user_state_db or "").strip()
    base = Path(configured) if configured else (Path(__file__).resolve().parent.parent / "data" / "user_state.db")
    uid = get_current_user_id()
    if uid:
        return str(base.parent / "users" / uid / base.name)
    return str(base)
```
`_connect()` использует `_resolve_state_db_path()` вместо текущего инлайна. Остальное (`mkdir parents`,
pragmas, schema-кэш) — без изменений; работает автоматически, т.к. ключуется по пути.
- При `uid=None` (auth выключен, фоновые warmups, тесты) → старый путь `data/user_state.db` (обратная совместимость).
- При `uid="<id>"` → `data/users/<id>/user_state.db`.
- `user_id` использовать **файлобезопасный** (uuid4 hex или sha256-срез email); не сырой email.

> Проверить, что `metrics_db.py`, `session_store.py`, `event_tracking.py`, `request_cache.py` —
> это глобальные/аналитические БД (НЕ per-user): их НЕ трогаем. Per-user только `user_state.db`.

### A4. Хранилище пользователей — НОВЫЙ `app/auth_db.py`
Отдельная глобальная БД `auth.db` (путь `get_settings().auth_db`). Схема (≥3 связанные таблицы —
закрывает заодно пункт «3+ связанные таблицы с FK»):
```sql
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,                  -- uuid4 hex
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS auth_sessions (           -- refresh/issued tokens (audit + revoke)
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    issued_at  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    user_agent TEXT
);
CREATE TABLE IF NOT EXISTS auth_audit_log (          -- login/register/fail события
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
    event      TEXT NOT NULL,                        -- register|login_ok|login_fail|logout
    ip         TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
```
Функции: `create_user(email, password_hash, display_name)`, `get_user_by_email(email)`,
`get_user_by_id(id)`, `touch_last_login(id)`, `record_session(...)`, `revoke_session(id)`,
`log_event(user_id, event, ip)`. Использовать паттерн соединения из `user_state_db.py`
(WAL, `check_same_thread=False`, `_DB_WRITE_LOCK`), но БД глобальная (contextvar НЕ влияет).

### A5. Сервис аутентификации — НОВЫЙ `app/auth_service.py`
```python
import bcrypt, jwt, uuid
from datetime import datetime, timedelta, timezone

def hash_password(raw: str) -> str: ...          # bcrypt.hashpw, rounds из settings
def verify_password(raw: str, hashed: str) -> bool: ...
def issue_access_token(user_id: str) -> str:     # jwt.encode {sub, exp, iat, jti}
def decode_access_token(token: str) -> dict:     # jwt.decode → raises на невалидном/просроченном
def register(email, password, display_name) -> User   # проверка уникальности, хэш, create_user, audit
def authenticate(email, password) -> User | None      # verify, touch_last_login, audit
```
Валидация: email через `pydantic.EmailStr`; пароль — min 8 символов (вернуть 422 при нарушении).
Гонки: при дубликате email → `409 Conflict`.

### A6. Pydantic-модели — НОВЫЙ `app/auth_models.py`
`RegisterRequest{email: EmailStr, password: str (min_length=8), display_name: str|None}`,
`LoginRequest{email, password}`, `TokenResponse{access_token, token_type="bearer", user: UserPublic}`,
`UserPublic{id, email, display_name}`. Поля с `Field(...)` и валидаторами — закрывает «валидация данных».

### A7. Зависимость авторизации — расширить `app/api_auth.py`
Добавить генераторную зависимость, которая ставит/сбрасывает contextvar:
```python
from typing import Annotated
from fastapi import Header, HTTPException
from app.auth_context import set_current_user_id, reset_current_user_id
from app.auth_service import decode_access_token
from app.auth_db import get_user_by_id

async def auth_scope(authorization: Annotated[str|None, Header()] = None):
    settings = get_settings()
    if not settings.auth_enabled:
        yield None                          # бэк-компат: без auth, contextvar=None
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = get_user_by_id(payload.get("sub", ""))
    if not user:
        raise HTTPException(401, "User not found")
    ctx = set_current_user_id(user["id"])
    try:
        yield user
    finally:
        reset_current_user_id(ctx)
```
Старый `require_api_key` оставить для admin/service-роутеров (опционально), либо объединить.

### A8. Подключение роутеров — `app/api.py`
1. Новый роутер `app/routers/auth.py` (публичный, БЕЗ auth-гейта): `POST /auth/register`,
   `POST /auth/login`, `GET /auth/me` (под `auth_scope`), `POST /auth/logout`.
   Подключить как `app.include_router(auth_router)` рядом с `core_router`.
2. Заменить `_protected_dependencies = [Depends(require_api_key)]` →
   `[Depends(auth_scope)]` (либо `[Depends(require_api_key), Depends(auth_scope)]`, если оставляем
   API-key для сервисов). При `auth_enabled=false` `auth_scope` пропускает всех → тесты зелёные.
3. CORS уже разрешает `Authorization` (`cors_headers` в config). Проверить.

### A9. Streamlit — логин-гейт и проброс токена
- НОВЫЙ `app/ui/auth_gate.py`:
  - `render_auth_gate()` — формы Вход/Регистрация (`st.tabs`), вызывают `POST /auth/login|register`
    через `app/ui_client.py`; при успехе кладут `access_token`, `user_id`, `user_email` в
    `st.session_state`; `st.rerun()`.
  - `is_authenticated() -> bool`, `current_user_id() -> str|None`, `logout()`.
- `app/ui/main.py`: сразу после `_init_state()` (стр. 81):
  ```python
  from app.ui.auth_gate import render_auth_gate, is_authenticated, apply_ui_auth_context
  if get_settings().auth_enabled and not is_authenticated():
      render_auth_gate()
      st.stop()
  apply_ui_auth_context()   # ставит contextvar в процессе Streamlit для прямого доступа к user_state
  ```
- `apply_ui_auth_context()` вызывает `set_current_user_id(st.session_state["user_id"])` в начале
  каждого rerun (Streamlit однопоточный per-run → безопасно).
- `app/ui_client.py::_auth_headers()`: если в `st.session_state` есть `access_token` — добавить
  `Authorization: Bearer <token>`.
- **Внимание (worker-thread):** tutor chat запускает `query_service` в отдельном потоке
  (см. комментарий в `app/ui/main.py`). contextvars НЕ наследуются новым потоком автоматически.
  В месте создания потока обернуть в `contextvars.copy_context().run(...)` ИЛИ явно
  `set_current_user_id(uid)` внутри потока. Найти спавн потока (`threading.Thread`/`ThreadPoolExecutor`)
  в tutor-пути и пробросить uid. Это единственное «скрытое» место — обязательно проверить.
- Сайдбар (`app/ui/sidebar.py`): добавить блок «Вы вошли как {email} · Выйти».

### A10. Тесты — `tests/test_auth.py` (новый)
- `register` → `login` → `/auth/me` happy-path (с `AUTH_ENABLED=true` через monkeypatch settings).
- Неверный пароль → 401; дубликат email → 409; слабый пароль/битый email → 422.
- Просроченный/битый JWT → 401.
- **Изоляция state:** под user A записать flashcard/quiz-результат → под user B список пуст
  (проверяет per-user путь БД). Использовать `tmp_path` для `user_state_db`/`auth_db` и
  `reset_schema_cache_for_tests()`.
- Регресс: при `AUTH_ENABLED=false` существующие 50 тестов проходят без изменений.

### A11. Acceptance (Workstream A)
- [ ] `AUTH_ENABLED=false`: поведение и все 50 тестов без изменений.
- [ ] `AUTH_ENABLED=true`: без токена protected-эндпойнты → 401; UI требует логин.
- [ ] Регистрация/логин работают, пароли — bcrypt (в БД нет plaintext).
- [ ] State двух пользователей физически изолирован (`data/users/<id>/user_state.db`).
- [ ] `auth.db` содержит 3 связанные таблицы с FK (`users`←`auth_sessions`,`auth_audit_log`).

---

## Workstream B — CI/CD (`.github/workflows`)

### B1. `.github/workflows/ci.yml` — линт + тесты (на push/PR)
```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: "pip" }
      - run: pip install -r requirements.txt
      - run: pip install ruff
      - run: ruff check app tests           # линт
      - run: pytest -q                       # 50+ тестов
    env:
      AUTH_ENABLED: "false"                  # тестовый прогон без auth-гейта
```
> Если полный `requirements.txt` ставится долго/тяжело на CI (docling, FlagEmbedding, torch) —
> вынести dev-зависимости в `requirements-dev.txt` (fastapi, httpx, pytest, ruff, pydantic, jwt,
> bcrypt) и ставить их + мокать тяжёлые импорты. Сначала попробовать полный; при таймаутах — split.
> Добавить `ruff` в dev-зависимости; при шуме линта — стартовая конфигурация `[tool.ruff]` в
> `pyproject.toml` с разумным `select`/`ignore`, чтобы CI был зелёным.

### B2. `.github/workflows/deploy.yml` — автодеплой (на push в main, после CI)
Цель — HF Spaces (Docker SDK, см. Workstream C). Деплой = `git push` в remote Space:
```yaml
name: Deploy
on:
  push: { branches: [main] }
jobs:
  deploy:
    runs-on: ubuntu-latest
    needs: []          # либо workflow_run от CI
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Push to Hugging Face Space
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
          HF_USERNAME: ${{ secrets.HF_USERNAME }}
          HF_SPACE: hometutor
        run: |
          git config user.email "ci@hometutor"
          git config user.name "CI"
          git remote add space https://${HF_USERNAME}:${HF_TOKEN}@huggingface.co/spaces/${HF_USERNAME}/${HF_SPACE}
          git push --force space HEAD:main
```
Секреты GitHub: `HF_TOKEN` (write), `HF_USERNAME`. JWT_SECRET/OPENAI_API_KEY задаются в HF Space Secrets.

### B3. Acceptance (B)
- [ ] PR/коммит запускает CI; линт+тесты зелёные.
- [ ] Бейдж статуса CI в README.
- [ ] Push в main триггерит deploy → Space пересобирается.

---

## Workstream C — Деплой онлайн (HF Spaces, Docker SDK)

> Почему Docker SDK, а не Streamlit SDK: Streamlit-SDK Space НЕ запускает FastAPI
> (`deploy/hf-spaces/README.md`), а UI зависит от API. Docker-Space поднимает оба процесса
> существующим `deploy/docker/docker_entrypoint.sh`. Публичным делаем Streamlit; FastAPI — внутренний
> `127.0.0.1:8000` (UI и так туда ходит через `ui_api_base_url`).

### C1. Метаданные Space
HF Docker-Space читает YAML-заголовок корневого `README.md`. Добавить в начало `README.md`:
```yaml
---
title: hometutor — ИИ-тьютор с RAG
emoji: 🎓
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8501
pinned: false
---
```
(HF проксирует публично один порт = `app_port`. Streamlit на 8501 публичный, uvicorn на 8000 внутренний.)

### C2. Правки под одно-портовый прод
- `deploy/docker/docker_entrypoint.sh`: uvicorn оставить на `127.0.0.1:8000` (внутренний),
  streamlit на `0.0.0.0:8501` (как сейчас). HF сам пробросит 8501.
- На HF контейнерный FS эфемерный → данные не персистятся между рестартами. Для демо это ок:
  - индекс — заранее собранный `demo_chroma_db/` (как в текущем HF README, шаг 1–2);
  - `auth.db` и per-user `user_state.db` живут в эфемерном `/app/data` (демо-аккаунты пересоздаются).
    Если нужна персистентность — подключить HF Persistent Storage или внешний том (вне объёма; задокументировать как ограничение демо).
- HF Space Secrets: `OPENAI_API_KEY`, `OPENAI_API_BASE`, `LLM_MODEL`, `EMBED_MODEL`,
  `EMBED_DIMENSIONS`, `AUTH_ENABLED=true`, `JWT_SECRET=<сильный>`, `CORS_ORIGINS` (добавить домен Space).

### C3. Smoke-проверка прода
- [ ] Публичный URL открывается (HTTPS).
- [ ] Логин/регистрация работают.
- [ ] `/ask`, tutor, quiz, flashcards отвечают на демо-корпусе.
- [ ] Внести живой URL в README (раздел «Демо»).

### C4. Acceptance (C)
- [ ] Приложение доступно по постоянному HTTPS-URL 24/7.
- [ ] Прод работает с `AUTH_ENABLED=true`.

---

## Workstream D — Документация (P1, в этом репозитории)

### D1. `README.md` — переписать под рубрику (сохранить HF YAML-заголовок из C1)
Разделы:
1. **Идея и функциональность** — что это, ценность, ключевые фичи (RAG-ответы с источниками,
   tutor, quiz, flashcards+SRS, knowledge graph, Smart Study Router, прогресс/аналитика).
2. **Демо** — живой URL (из C3) + тестовый аккаунт.
3. **Скриншоты** — встроить из `docs/screenshots/final/scenario_*/` (Markdown `![]()`),
   минимум 5–6 ключевых экранов (главная, ответ с источниками, tutor, quiz, flashcards, прогресс).
4. **Технологии** — FastAPI, Streamlit, Chroma, BM25, SQLite, JWT/bcrypt, Docker, GitHub Actions, Я.Метрика.
5. **Установка и запуск** — локально (venv) и Docker (есть, актуализировать; добавить `AUTH_ENABLED`).
6. **Бейдж CI**, ссылка на `docs/AI_DEVELOPMENT.md` и на репозиторий `hometutor-studio`.

### D2. `docs/AI_DEVELOPMENT.md` — НОВЫЙ (обязательное требование рубрики)
Демонстрация использования AI на КАЖДОМ этапе. Структура:
- **Планирование**: генерация идеи, анализ конкурентов, user stories, ТЗ (со ссылками в `hometutor-studio`).
- **Дизайн/архитектура**: проектирование БД и API с AI, UI-концепции.
- **Разработка**: генерация компонентов, рефакторинг, тесты (привести 3–5 реальных пар «промпт → результат»).
- **Backend/инфра**: схемы/миграции, эндпойнты, Docker, CI/CD — с AI.
- **Отладка/оптимизация**: анализ ошибок, производительность, аудит безопасности — с AI.
- **Проблемы и решения**: 5–7 кейсов (проблема → как AI помог → итог).
- **Выводы и рекомендации**.
> Контент промптов/историй взять/синхронизировать из `hometutor-studio`; здесь — кросс-ссылки +
> 8–12 конкретных примеров промптов с результатами (рубрика требует «примеры промптов и результатов»).

### D3. Кросс-линк репозиториев
В обоих README — раздел «Состав проекта»: `hometutor` (runtime/код) + `hometutor-studio`
(процесс/доки/промпты). Чтобы проверяющий видел полноту по любому из репо.

### D4. Acceptance (D)
- [ ] README: идея, демо-URL, ≥5 скриншотов, технологии, рабочие инструкции запуска, бейдж CI.
- [ ] `docs/AI_DEVELOPMENT.md` покрывает все этапы + ≥8 примеров промптов/результатов + проблемы/решения + выводы.
- [ ] Кросс-ссылки между `hometutor` и `hometutor-studio`.

---

## Workstream E — Яндекс.Метрика (P2)

> Streamlit не даёт штатно вставить тег в `<head>`, а `components.html` изолирует iframe
> (parent-просмотры не считаются корректно). Надёжно — пропатчить served `index.html` Streamlit
> при старте процесса.

### E1. Настройка — `app/config.py`
```python
yandex_metrika_id: str | None = Field(default=None, validation_alias=AliasChoices("YANDEX_METRIKA_ID"))
```

### E2. Инъекция счётчика — НОВЫЙ `app/ui/analytics.py`
`inject_yandex_metrika()`:
- если `settings.yandex_metrika_id` пуст → no-op;
- найти `index.html` Streamlit: `Path(streamlit.__file__).parent/"static"/"index.html"`;
- идемпотентно (по маркеру-комменту) вставить стандартный сниппет Я.Метрики с `{id}` перед `</head>`;
- обернуть в try/except + лог (на проде FS может быть read-only — тогда fallback на `components.html`).
Вызвать один раз в `app/ui/main.py` сразу после `st.set_page_config(...)`.
> Альтернатива/доп.: `<noscript><img .../></noscript>` через `st.markdown(unsafe_allow_html=True)`
> для счёта без JS. ID счётчика — в HF Secrets (`YANDEX_METRIKA_ID`).

### E3. Acceptance (E)
- [ ] На проде в `<head>` присутствует тег Я.Метрики; в кабинете Метрики идут визиты.
- [ ] Без `YANDEX_METRIKA_ID` — ничего не инжектится (локалка чистая).

---

## Итоговый чек-лист соответствия рубрике (после выполнения)

| Требование | Закрывает |
|---|---|
| Аутентификация пользователей | A |
| Валидация данных (доп. усиление) | A6 |
| 3+ связанные таблицы с FK | A4 (`auth.db`) |
| CI/CD: линт + тесты + автодеплой | B |
| Развёрнуто и доступно онлайн | C |
| Доп. функция: аналитика (Я.Метрика) | E |
| README (идея/демо/скрины/технологии/инструкции) | D1 |
| Документация AI-процесса + промпты | D2 |
| Понятная история коммитов | следовать Conventional Commits во всех PR этого плана |

## Замечания по коммитам
Все изменения плана делать осмысленными коммитами в стиле Conventional Commits
(`feat(auth): ...`, `ci: ...`, `docs: ...`, `feat(analytics): ...`) — это закрывает критерий
«понятная история коммитов». Не продолжать нумерацию `1..29`.

## Карта изменений (быстрый индекс для исполнителя)
- Новые файлы: `app/auth_context.py`, `app/auth_db.py`, `app/auth_service.py`, `app/auth_models.py`,
  `app/routers/auth.py`, `app/ui/auth_gate.py`, `app/ui/analytics.py`, `tests/test_auth.py`,
  `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, `docs/AI_DEVELOPMENT.md`,
  `requirements-dev.txt` (опц.).
- Правки: `requirements.txt`, `app/config.py`, `app/user_state_db.py` (`_connect`),
  `app/api_auth.py` (`auth_scope`), `app/api.py` (роутер auth + смена protected-deps),
  `app/ui_client.py` (`_auth_headers`), `app/ui/main.py` (гейт + контекст + метрика),
  `app/ui/sidebar.py` (статус входа/выход), `README.md` (YAML + контент),
  `config.env` (дефолты auth/metrika), `pyproject.toml` (ruff, опц.).
</content>
</invoke>
