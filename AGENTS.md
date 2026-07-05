# hometutor — Agent Instructions

Этот файл читается агентами Codex CLI и совместимыми инструментами
автоматически при запуске в корне проекта.

Полные соглашения: `docs/conventions.md` (TL;DR + навигация).
Детали архитектуры: `docs/conventions_architecture.md`, `docs/conventions_reference.md`.
Навигация по всей документации: `docs/index.md`. При конфликте — приоритет
у `docs/conventions*.md` и кода.

Это runtime-репозиторий (код приложения, `app/`, `tests/`, `scripts/`, `docs/`).
Backlog, user stories и командный workflow-пайплайн (PO → Analyst → Architect →
Dev → Tester) ведутся в отдельном репозитории `hometutor-studio` — этот файл
их не описывает и не требует для работы с кодом.

---

## Что это за проект

Локальный учебный ассистент над папкой `data/`: FastAPI (порт 8000) +
Streamlit UI (порт 8501) + CLI (`ask` → `app/ask_cli.py`) + Telegram-бот
(`app/telegram_handlers.py`, `app/telegram_notifications.py`).
Индекс — Chroma + llama-index (гибридный retrieval, BM25 + vector).
LLM/embeddings — через provider-layer (`app/provider.py` +
`app/provider_openai.py`): OpenAI-совместимый API
(локальная модель через LM Studio, облако через OpenRouter/OpenAI), профили
`LOCAL_STRICT` / `BALANCED` / `CLOUD_FAST` с circuit-breaker fallback.
Опциональная аутентификация — JWT + bcrypt (`app/auth_*.py`,
`app/routers/auth.py`), per-user изоляция `data/users/<user_id>/user_state.db`.
CI/CD — `.github/workflows/ci.yml` (тесты), `.github/workflows/deploy.yml`.

Инварианты: **local-first**, ответы с привязкой к источникам,
цикл «ответ → tutor → quiz → spaced repetition → план».

---

## Жёсткие правила (нарушение = blocker)

- **Конфиг:** runtime/app-код читает настройки только через
  `get_settings()` / `get_retrieval_settings()` из `app/config.py`.
  Прямой доступ к env разрешён в `app/config.py` и диагностике
  `app/ingestion_env_diag.py`; служебные скрипты могут работать с env явно.

- **LLM / embeddings:** только provider-layer: публичные фабрики в
  `app/provider.py`, внутренний OpenAI-compatible adapter в `app/provider_openai.py`.
  Нельзя создавать клиенты LLM/embeddings напрямую вне этого слоя.

- **Промпты:** source-of-truth текстов — пакет `app/prompts/`
  (тяжёлая реализация — `app/prompts/_impl.py`). Legacy-bridge модули
  вроде `app/tutor_prompts.py` и builders вроде `app/deep_study_prompt.py`
  должны импортировать/собирать из `app/prompts`, а не дублировать тексты.
  Нельзя хардкодить промпты в роутерах, сервисах или UI.

- **HTTP роутеры:** endpoint-логика только в `app/routers/*`
  (+ shared contracts/helpers в `app/api_requests.py`, `app/api_models*.py`).
  Нельзя добавлять endpoint-логику в `app/api.py` напрямую.
  Регистрация нового роутера — через `app.include_router(...)` в `app/api.py`
  (защищённые эндпоинты добавлять с `dependencies=_protected_dependencies`).

- **Pipeline шаги:** контракт `process(QueryContext) -> QueryContext`
  (`app/pipeline_steps.py`, `app/pipeline_runner.py`, `app/pipeline_factory.py`).
  Нельзя нарушать сигнатуру.

- **DB / persistence:** user-state таблицы — только через хелперы из
  `app/user_state*.py`. Auth — через `app/auth_service.py` / `data/auth.db`.
  Нельзя открывать ad hoc SQLite-соединения в сервисах, роутерах или UI.

- **Guardrails:** все точки входа (API, CLI, UI, Telegram) должны проходить
  через `app/guardrails.py` / `app/input_validation.py`.

- **Bare except:** новый код не добавляет `except:`. Широкие `except Exception`
  в новом или изменяемом коде — только с `# noqa: BLE001` и явным
  обоснованием в комментарии; при касании старого блока приводить его к этому
  правилу в рамках write-set.

- **Write-set:** изменять только файлы из заявленного write-set задачи.
  Попутный рефакторинг соседних модулей — запрещён.

- **Python для всех агентов:** для Codex, Cursor, Claude Code, Kilo Code и других
  совместимых агентов для всех Python-команд в этом проекте сначала
  использовать интерпретатор `.\.venv\Scripts\python.exe` из корня репозитория.
  Если `.venv` недоступен, только тогда разрешён fallback
  на `python` или `py` из `PATH`.

---

## Стиль кода

- PEP 8; говорящие имена; комментарии только для неочевидной логики.
- KISS: маленькие модули, явные зависимости, без лишних абстракций.
- Без feature flags, без backwards-compatibility shims без явной нужды.
- Новые зависимости — только при явной необходимости (см. `docs/conventions_reference.md` § Dependency policy).

---

## Тесты

После изменений запускать **только затронутые тесты**. Префикс везде — `.\.venv\Scripts\python.exe -m pytest` (fallback: `python` / `py`). Полный список файлов — `tests/*.py`; имена тестов не всегда совпадают 1:1 с именами модулей в `app/`, при неясности — искать по ключевому слову (`Get-ChildItem tests -Filter test_<keyword>*.py`).

Примерные bundles по зонам изменений (по факту репозитория):

| Зона | Файлы |
|------|-------|
| Auth | `tests/test_auth.py tests/test_auth_integration.py` |
| Flashcards | `tests/test_flashcards_*.py` (interactive_card, memory_signals, scheduling, tag_display, review_undo, review_keyboard, review_section_links_smoke, generate_view) |
| Guardrails / pipeline | `tests/test_guardrails_invariants.py tests/test_pipeline_invariants.py tests/test_logging_invariants.py` |
| Query / retrieval | `tests/test_query_response_postprocessing.py tests/test_retrieval_context_budget.py tests/test_hybrid_retrieval_bm25.py tests/test_provider_embeddings.py` |
| Ingestion / индекс | `tests/test_ingestion_support.py tests/test_empty_reset_index.py tests/test_reindex_poll.py tests/test_section_index.py tests/test_first_run_preflight_seed.py` |
| UI / navigation | `tests/test_navigation_visibility.py tests/test_ui_preferences.py tests/test_ui_preferences_sync.py tests/test_feature_registry.py tests/test_mission_control_*.py` |
| Living Konspekt / graph UI | `tests/test_living_konspekt_*.py tests/test_dashboards_graph_workbench.py tests/test_knowledge_graph_d3_section.py` |
| Term cards | `tests/test_term_cards.py` |

Если в env заданы `PYTHONHOME` / `PYTHONPATH` — снять их или добавить `-E` к интерпретатору. Reranker по умолчанию включён через `ENABLE_RERANKER=true`; отключайте его только в тех targeted-тестах/командах, где это явно требуется.

Полный suite (`pytest` без узкого пути) — только при явном запросе пользователя.

---

## Документация (doc-sync)

Актуальная runtime-документация репозитория — в `docs/` (не в `doc/`).
В `doc/archive/` могут оставаться legacy/archive-артефакты; это не рабочий
docs-root и не источник текущего backlog/workflow. Навигация: `docs/index.md`.

Обновлять, если изменились:
- Публичный API-контракт → `docs/api_reference.md`
- UI-поведение → `docs/user_guide.md`, `docs/quickstart.md`
- Архитектура / config / persistence → `docs/architecture.md`,
  `docs/technical_specification.md`, `docs/conventions_architecture.md`
- Инженерные правила → `docs/conventions.md`, `docs/conventions_reference.md`
- Настройки → `.env.example`, `config.env`

Правило из `docs/conventions.md`: runtime-документы не должны ссылаться на
локальные файлы, которых нет в этом репозитории; если материал принадлежит
`hometutor-studio` — писать это явно.

---

## Источники истины

| Что | Где |
|-----|-----|
| Навигация по документации | `docs/index.md` |
| HTTP API / реальные маршруты | `app/api.py`, `app/routers/*`, `/docs` (OpenAPI) |
| Конфигурация | `app/config.py`, `config.env` (tracked defaults), `.env` (local override) |
| LLM / embeddings | provider-layer: `app/provider.py`, `app/provider_openai.py` |
| Соглашения | `docs/conventions.md` |
| Kilo Code rules | `kilo.jsonc`, `.kilo/rules/` (+ auto `AGENTS.md`) |
| Cursor rules | `.cursor/rules/*.mdc` (+ section-only `AGENTS.md`) |
| Backlog / процесс / team workflow | репозиторий `hometutor-studio` (не в этом репо) |

При конфликте: код важнее производных markdown-файлов.
