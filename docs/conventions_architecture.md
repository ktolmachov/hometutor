# Соглашения: архитектура и слои

Актуализировано: 2026-07-14.

## Конфигурация

- Все runtime-настройки читаются через `app/config.py`.
- В приложении использовать `get_settings()` и `get_retrieval_settings()`.
- `config.env` содержит tracked defaults; `.env` содержит локальные secrets/overrides.
- Новый env-параметр добавляется как поле `Settings` или `RetrievalSettings`, затем используется через settings object.
- Raw `os.getenv` / `os.environ` в `app/*.py` запрещены вне `app/config.py` и diagnostic-only кода; guard:
  `scripts/check_config_access.py` (AR-2026-06-25-001, AR-2026-06-25-002).

## LLM и embeddings

- LLM/embedding клиенты создаются только через `app/provider.py`.
- Нельзя создавать OpenAI/llama-index clients напрямую в роутерах, UI или сервисах.
- Локальный/облачный fallback должен проходить через существующую resilience/config логику.
- SSR LLM использует `get_ssr_llm_resolved()` и профильные настройки `SSR_LLM_*`.

## HTTP и сервисы

- `app/api.py` — единственная точка сборки FastAPI app и подключения middleware/routers.
- Роутеры в `app/routers/*` должны оставаться тонкими: request parsing, status codes, вызов сервиса.
- Бизнес-логика живёт в `*_service.py` или доменных модулях.
- Новые endpoints документируются в [api_reference.md](api_reference.md).

## Streamlit UI

- UI entrypoint: `app/ui/main.py`.
- Feature UI lives under `app/ui/*`.
- UI не должен владеть доменной логикой, SQL или provider clients.
- Для API-вызовов из UI использовать `app/ui_client.py` и локальные UI helpers.
- Runtime UI должен деградировать без падения главной страницы: optional cards/panels ловят исключения локально и показывают понятный fallback.

## SQLite и локальные stores

- User-state таблицы принадлежат `app/user_state*.py`.
- UI, routers и services не должны открывать `data/user_state.db` напрямую.
- Отдельный SQLite store допустим только через owner-wrapper module, например:
  - `app/session_store.py`
  - `app/event_tracking.py`
  - metrics dashboard cache modules
  - graph bundle modules
- Новый store должен иметь явного владельца, путь, backup/sync политику и tests/smoke coverage.

## Retrieval

- Public RAG profiles: `fast`, `quality`, `graph_aware`.
- Retrieval modes: `vector_only`, `hybrid`, `bm25_only`, `doc_then_chunk`.
- User-facing profile не равен raw retrieval mode.
- Новый retrieval mode добавляется через registry в `app/retrieval_strategies.py`, config constants и pipeline contracts.
- Graph augmentation должен оставаться bounded: max docs/hops, trace payload, fallback/demotion reason.

## Index lifecycle

- Active generation pointer: `app/index_registry.py` и `index_registry.json`.
- Chroma backend access: `app/chroma_vector_backend.py`.
- Full/partial reindex orchestration: `app/ingestion_loader.py`.
- Index backup/restore logic belongs to `app/index_backup.py` and related scripts, not UI handlers.

## Tutor и learner loop

- Tutor path идёт через `/ask` и `query_mode="tutor"`.
- Tutor contracts live in `app/tutor_*` modules.
- Learner goal snapshot lives behind learner/user_state helpers.
- Quiz, flashcards, SM-2 and progress signals should write through user-state/service APIs.

## Smart Study Router

- SSR deterministic recommendation remains the baseline.
- LLM/ML layers are enrichment/reranking/fallback-aware additions.
- Feedback collection saves structured local signals; it must not silently change route policy in the same request.
- SSR explainability must remain inspectable through evidence/reason fields, not only natural language.

## Архитектурные стражи и бюджеты

- Четыре guard'а кодируют жёсткие границы: `scripts/check_config_access.py`, `check_dead_modules.py`, `check_requirements_imports.py`, `check_size_budget.py`.
- Стражи запускаются на каждом CI (push/PR) через явный шаг «Architecture regression guards» в `.github/workflows/ci.yml` (в дополнение к общему `pytest tests/`). Также доступны в любом локальном запуске `pytest` (через `tests/test_architecture_guards.py`, параметризованный; `main()` должен вернуть 0). Нет запланированного ежедневного (cron/schedule) задания.
- Агрегатор: `scripts/arch_regression_guards.py` (можно запускать standalone).
- Бюджеты size (файлы/функции/линии) — no-growth; синхронизированы с HEAD (33/155/1942/361). Waiver'ы только явные (см. `app/prompts/_impl.py`).
- Если guard красный — фиксим структуру, не поднимаем потолок.

## Темы и шрифты (local-first)

- Тело UI — системные стеки (`--font-sans` = `system-ui`…, `--font-mono` = `ui-monospace`… в `ui_theme.css`). Отдельные webfonts (Manrope / IBM Plex Mono) не подключаются; внешних запросов для текста нет.
- Material Symbols (иконки) — единственный оставшийся внешний шрифт (минимальный, только иконки). Задокументировано как tradeoff (см. план #9).
- В строгом оффлайне всё рендерится через системные шрифты.
- Iframe-виджеты (например interactive flashcard) не наследуют host CSS vars и дублируют mono-стек явно, без ссылок на webfonts.
