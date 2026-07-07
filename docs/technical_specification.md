# Техническая спецификация hometutor

Актуализировано по runtime-коду: 2026-07-06.

## Назначение

`hometutor` — локальное Python-приложение для обучения по пользовательским материалам. Система индексирует документы, отвечает на вопросы с источниками, поддерживает tutor-route, quiz, flashcards, SM-2, adaptive plan, Smart Study Router, локальный прогресс и sync.

Этот репозиторий содержит runtime-продукт. Runtime-документы и локальная demo-витрина находятся в `docs/`; процессные документы, backlog, user stories, сценарные манифесты и генератор demo-документа находятся вне этого репозитория, в `hometutor-studio`.

## Entry points

| Entry point | Назначение |
|---|---|
| `main.py` | FastAPI API на `0.0.0.0:8000` |
| `app/ui/main.py` | Streamlit UI |
| `ingest.py` | индексация документов |
| `telegram_bot.py` | Telegram bot |
| `scripts/local_start.ps1` | one-command localhost launcher |
| `scripts/local_readiness.py` | readiness gate |
| `scripts/Warmup-HomeRagRag.ps1` | retrieval warmup через API |
| `scripts/check_chroma_health.py` | read-only health check Chroma SQLite |
| `scripts/rebuild_knowledge_graph.py` | пересборка active generation knowledge graph |
| `scripts/probe_graph_llm.py` | проверка graph LLM перед сменой модели |
| `scripts/delete_all_data.py` | guarded очистка локальных runtime-артефактов |
| `scripts/fresh_start.py` | guarded reset + optional re-ingest |
| `scripts/audit_knowledge_graph.py` | audit полноты graph bundle |
| `.github/workflows/ci.yml` | CI: `ruff check` + `pytest` на push/PR в `main` |
| `.github/workflows/deploy.yml` | автодеплой в HF Space после успешного CI |

В этом runtime-репозитории нет `ask.py`, `run_eval.py`, `run_eval_compare.py` как локальных entrypoints. `tests/` — рабочий каталог тестов (`pytest`), прогоняется локально и в CI; запуск: `.\.venv\Scripts\python.exe -m pytest tests\ -q`.

## Стек

- Python, FastAPI, Uvicorn
- Streamlit
- llama-index
- Chroma
- BM25 / hybrid retrieval
- pydantic-settings
- aiogram
- SQLite
- JWT (`PyJWT`) + `bcrypt` — опциональная аутентификация (`AUTH_ENABLED`)
- OpenTelemetry optional
- pytest + ruff — тесты и линт, используются локально и в `.github/workflows/ci.yml`

## Конфигурация

`app/config.py` загружает:

1. `config.env` — tracked defaults;
2. `.env` — локальные секреты и overrides.

Ключевые группы настроек:

| Группа | Переменные |
|---|---|
| API key | `HOME_RAG_API_KEY`, `API_KEY`, CORS/rate-limit settings |
| Аутентификация | `AUTH_ENABLED`, `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ACCESS_TTL_MIN`, `AUTH_DB`, `BCRYPT_ROUNDS` |
| Аналитика | `YANDEX_METRIKA_ID` |
| LLM | `OPENAI_API_KEY`, `OPENAI_API_BASE`, `LLM_API_BASE`, `LMSTUDIO_API_BASE`, `LLM_MODEL` |
| embeddings | `EMBED_API_BASE`, `EMBED_MODEL`, `EMBED_DIMENSIONS` |
| local/cloud profile | `HOME_RAG_LOCAL_PROFILE`, `HOME_RAG_DATA_MODE`, `HOME_RAG_LLM_FALLBACK_*` |
| SSR LLM | `SSR_LLM_API_BASE`, `SSR_LLM_MODEL`, `ENABLE_SSR_LLM_PROFILING`, `SSR_LLM_PROFILE_LOG_DIR` |
| retrieval | `RAG_PROFILE`, `RETRIEVAL_MODE`, `SIMILARITY_TOP_K`, `ENABLE_RERANKER`, `RERANK_TOP_N` |
| paths | `HOME_RAG_HOME`, `HOME_RAG_DATA_DIR`, `HOME_RAG_INDEX_DIR`, `HOME_RAG_LOG_DIR` |
| observability | `ENABLE_OTEL_TRACING`, metrics/cost/log paths |

Публичные RAG profiles: `fast`, `quality`, `graph_aware`. Retrieval modes: `vector_only`, `hybrid`, `bm25_only`, `doc_then_chunk`.

## Поддерживаемые форматы

Для индексации и preview/explain:

- `.txt`
- `.md`
- `.html`
- `.docx`
- `.pdf`

Для `.docx` используется `python-docx`/зависимости извлечения текста, для PDF — PDF extraction stack из зависимостей.

Мультимодальный M0a/M0.3 не добавляет видео как индексируемый формат. Он добавляет
metadata-контракт sidecar v1 и section media panel в `Живом конспекте` для связывания
конспекта с локальным видео, external video URL, таймкодами разделов и изображениями.

## Хранилища и артефакты

| Артефакт | Назначение |
|---|---|
| `data/` | исходные документы и `user_state.db` |
| `data/**/*.media.json` | multimodal sidecar v1 для runtime-конспекта; схема: `docs/schemas/media_sidecar_v1.schema.json` |
| `data/user_state.db` | learner state, quiz, flashcards, SRS, sync |
| `chroma_db/` | persistent Chroma и retrieval cache data |
| `data/graph_generations/` | graph bundles по поколениям индекса |
| `index_registry.json` | active index generation pointer |
| `faq_memory.jsonl` | FAQ memory |
| `logs/` | runtime logs, metrics, cost logs, SSR profiles |
| `app/ui/assets/d3.v7.min.js` | bundled D3 runtime asset for Knowledge Graph UI |

## Функциональные контуры

### Индексация

`ingest.py` вызывает `app.ingestion.build_index()`, который делегирует в ingestion loader и фазы full/partial index.

Основные модули:

- `app/ingestion.py`
- `app/ingestion_loader.py`
- `app/ingestion_index_full.py`
- `app/ingestion_index_partial.py`
- `app/ingestion_index_nodes.py`
- `app/ingestion_metadata.py`
- `app/index_registry.py`
- `app/chroma_vector_backend.py`

### Query/RAG

Путь `/ask`:

```text
input validation
  -> guardrails
  -> classify/condense/rewrite
  -> retrieval routing/profile
  -> retrieval execution
  -> generation
  -> grounded answer assembly
  -> postprocessing
  -> session/history/metrics persistence
```

Основные модули: `query_service`, `pipeline_runner`, `pipeline_steps`, `retrieval`, `retrieval_router`, `query_rag_execution`, `query_rag_assembly`.

Postprocessing включает opt-in `app/retrieval_context_budget.py` (`RAG_CONTEXT_TOKEN_BUDGET`,
`0` = выключено по умолчанию) — жёсткий бюджет токенов retrieved-контекста перед synthesis,
применяется до lost-in-middle reorder.

### Tutor

Tutor не имеет отдельного endpoint: он идёт через `/ask` с `query_mode="tutor"`. Контракты и orchestration:

- `app/tutor_orchestrator.py`
- `app/tutor_pipeline_contract.py`
- `app/tutor_learner_contract.py`
- `app/tutor_personalization_policy.py`
- `app/ask_goal_snapshot_merge.py`

### Quiz, flashcards, progress

- Quiz: `app/quiz_service.py`, `app/quiz_adaptive.py`, `app/routers/quiz.py`
- Flashcards: `app/flashcard_service.py`, `app/user_state_flashcards.py`, `app/routers/flashcards.py`
- SM-2 concept review: `app/spaced_repetition.py`, `app/routers/review.py`
- Progress/adaptive plan: `app/learning_plan_service.py`, `app/learning_plan_adaptive.py`, `app/routers/dashboard.py`

### Smart Study Router

SSR строит next-step recommendation из локальных сигналов.

Основные модули:

- `app/smart_study_router.py`
- `app/smart_study_recommendation.py`
- `app/smart_study_evidence.py`
- `app/ssr_explain_service.py`
- `app/ssr_feedback_collection.py`
- `app/user_state_ssr_feedback.py`

### Multimodal sidecar v1

M0a/M0.3 реализуют проверяемый media metadata contract и UI-render без ASR и LLM.

Основные модули:

- `app/media_sidecar.py` — dataclasses/parser/loader, чтение `media_sidecar` из
  frontmatter, stale detection, строгая lightweight validation;
- `app/media_urls.py` — нормализация YouTube URL (`watch`, `youtu.be`, `embed`) и
  timestamp parsing; unknown `http(s)` URL остаётся external link;
- `app/path_safety.py` — запрет persisted absolute, drive-relative и traversal paths.
- `app/ui/living_konspekt_view.py` — рабочая поверхность «Живого конспекта»:
  корзина разделов, reorder, сохранение и media panel внутри собранного раздела;
- `app/ui/living_konspekt_add_panel.py`, `app/ui/living_konspekt_reader.py`,
  `app/ui/living_konspekt_next_steps.py` — локальное добавление разделов из
  markdown-конспектов, режим чтения и панели актуализации/deep-study prompt.

Sidecar хранится внутри `data/` как `<konspekt_stem>.media.json`; frontmatter конспекта
содержит только data-relative pointer. Persisted local media/image paths также
data-relative. Абсолютный внешний путь может быть только import input будущего ASR-flow,
но не persisted metadata. `media.video` остаётся основным видео для обратной совместимости,
а `media.videos[]` опционально задаёт полный список роликов, которые UI покажет в карточке
раздела.

Invalidation считается по `schema_version`, `konspekt_sha256`, `media_sha256`,
ASR model и alignment version. `section_slug` предназначен для UI/deep-link, а стабильным
ключом раздела остаётся `section_id`. `konspekt_sha256` игнорирует служебный frontmatter
pointer `media_sidecar`, потому что это wiring metadata, а не содержательный дрейф конспекта.

UI показывает уверенный timestamp action только если sidecar не stale и confidence section
timestamp не ниже порога. Stale, low-confidence, missing local media и unsafe path отображаются
как degraded state без падения страницы.

### Аутентификация

Опционально (`AUTH_ENABLED`, default `false`); подробное описание — [architecture.md](architecture.md#аутентификация).

- `app/auth_context.py` — contextvar текущего `user_id`.
- `app/auth_db.py` — глобальная `data/auth.db` (`users`, `auth_sessions`, `auth_audit_log`).
- `app/auth_service.py` — bcrypt, JWT issue/decode.
- `app/auth_models.py`, `app/routers/auth.py` — HTTP-слой (`/auth/*`).
- `app/api_auth.py::auth_scope` — FastAPI dependency на protected-роутерах.
- `app/ui/auth_gate.py` — Streamlit login-гейт.
- `app/user_state_db.py::_resolve_state_db_path` — per-user изоляция `user_state.db`.

## UI

Основной entrypoint: `app/ui/main.py`.

Основные разделы:

- `Главная — Mission Control`
- `Быстрый ответ`
- `Чат с тьютором`
- `Интерактивный Quiz`
- `Flashcards`
- `Курс`
- `Knowledge Graph`
- `Прогресс обучения`
- `История`
- `Темы`
- `Метрики`
- `Найти материалы`
- `Объяснить файл`
- `Чистый вид`

## Наблюдаемость

Система поддерживает:

- request logging;
- metrics store;
- cost logs;
- quality/educational/mastery metrics;
- pipeline trace;
- optional OpenTelemetry;
- SSR LLM profiling в `logs/ssr_llm_profiles/`.

## Ограничения

- Основной сценарий — локальный single-user runtime; multi-user доступен опционально через
  `AUTH_ENABLED=true` (JWT + bcrypt, per-user изоляция `user_state.db`).
- Runtime-репозиторий не содержит полный процессный backlog, сценарные манифесты и генератор demo-документа.
- `OFFLINE_MODE` и offline banners не заменяют настройку локального LLM/embedding endpoint.
- По умолчанию `config.env` направляет embeddings на локальный loopback endpoint; облачный embedding provider должен быть явным `.env` override.
- `HOME_RAG_API_KEY` защищает REST endpoints только если задан; `AUTH_ENABLED=true` требует
  реального `JWT_SECRET` (fail-fast guard — дефолтный dev-секрет отклоняется на старте).
- HF Spaces demo-деплой работает на эфемерном FS контейнера: аккаунты и прогресс не персистентны
  между перезапусками Space.
- Multimodal M0a/M0.3 — это metadata plumbing и media panel. M1 (ASR + автоматическое
  создание sidecar) существует как offline maintainer-конвейер
  (`scripts/transcribe_media.py`, `scripts/build_media_sidecar.py`, `app/media_alignment.py`,
  пакетно `scripts/Run-MediaKonspektBatch.ps1`); приложение его не вызывает — статус
  «offline-generated sidecar, читается runtime'ом». VLM captions и `media_progress` не
  являются runtime-возможностями.
- Выравнивание разделов ↔ таймкоды — `anchor-lis-v3.1` (`app/media_alignment.py`),
  детерминированное, без LLM: (1) транскрипт режется на **смысловые блоки**
  (TextTiling-подобная сегментация по провалам лексической связности — настоящие
  границы темы и ключевые слова, пишутся в sidecar `semantic_blocks`); (2) канонизация
  токенов (RU-стемминг + транслитерация латиницы конспекта в кириллицу ASR);
  (3) локальная L1-синонимия для учебных паттернов («практическое задание» ↔
  «домашка/упражнение») расширяет только scoring-токены и не использует LLM;
  (4) **per-pass хронология** — LIS-отбор и монотонность внутри «прохода» конспекта
  (H2-группа), а не единой глобальной цепочкой на весь документ (реальный конспект
  несколько раз проходит одну лекцию: слайды → ключевые темы → примеры);
  (5) `t_end` = начало следующего раздела прохода, у хвоста — конец смыслового блока.
  Метрика «плейлист-готово» считает объединение интервалов confident-фрагментов
  (проходы легитимно указывают на одни минуты — двойной счёт исключён).
