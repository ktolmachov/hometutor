# Техническая Спецификация `hometutor`

Актуализировано по коду на 2026-04-12.

## Назначение

`hometutor` — локальная Python-система для работы с учебной базой знаний из `data/`.
Система индексирует документы, отвечает на вопросы с источниками, поддерживает tutor-маршрут, quiz/review, темы, learning plan, прогресс обучения и локальный sync состояния.

## Entry Points

- `main.py` — FastAPI API
- `app/ui/main.py` — Streamlit UI
- `ask.py` — CLI-вопросы
- `ingest.py` — индексация
- `telegram_bot.py` — Telegram-бот
- `run_eval.py` — offline evaluation
- `run_eval_compare.py` — сравнение конфигураций eval

## Стек

- Python
- FastAPI
- Streamlit
- llama-index
- Chroma
- pydantic-settings
- aiogram
- OpenTelemetry optional
- pytest

## Поддерживаемые форматы

Для индексации:

- `.txt`
- `.md`
- `.html`
- `.docx`
- `.pdf`

Для `GET /explain/file` и `GET /content/file`:

- `.txt`
- `.md`
- `.html`
- `.pdf`
- `.docx` (извлечение текста через `python-docx`)

## Хранилища и артефакты

Каталоги:

- `data/` — документы и `user_state.db`
- `data/graph_generations/` — поколения PropertyGraph bundle (blue-green вместе с Chroma), см. `graph_generation_paths.py`
- `chroma_db/` — persistent Chroma
- `logs/` — logs, `metrics_store.jsonl`, `metrics_dashboard.db`
- `eval_data/` — eval datasets
- `eval_results/` — результаты eval

Файлы:

- `data/user_state.db` — SQLite состояния пользователя
- `faq_memory.jsonl` — FAQ-память
- `index_meta.json` — метаданные индекса
- `index_registry.json` — активное поколение индекса

## Конфигурация

### Через `app/config.py`

Основные runtime settings:

- `OPENAI_API_KEY`
- `OPENAI_API_BASE`
- `EMBED_API_BASE`
- `LLM_MODEL`
- `EMBED_MODEL`
- `EVAL_JUDGE_LLM`
- `QUIZ_LLM_MODEL`
- `ENABLE_ASYNC_QUALITY_JUDGE`
- `ENABLE_REWRITE`
- `ENABLE_CLASSIFIER`
- `ENABLE_SELF_CORRECTION`
- `ENABLE_FAQ_CACHE`
- `ENABLE_METADATA_ENRICHMENT`
- `ENABLE_DOCUMENT_SUMMARIES`
- `ENABLE_OTEL_TRACING`
- `OFFLINE_MODE`
- `UI_API_BASE_URL`
- `SHOW_TUTOR_DEV_TOOLS`
- `METRICS_STORE_PATH`
- `METRICS_DASHBOARD_DB_PATH`
- `LLM_COST_LOG_DIR`
- `FEEDBACK_PATH`
- `HISTORY_PATH`
- `FAQ_MEMORY_PATH`
- `INDEX_META_PATH`
- `INDEX_REGISTRY_PATH`
- `INDEX_REGISTRY_LOCK_PATH`
- `ACTIVE_INDEX_STATE_PATH`
- `HOME_RAG_MICRO_QUIZ_OFFLINE`
- `EVAL_MAX_WORKERS`
- `EVAL_BASELINE_JSON`
- `EVAL_OUTPUT_JSON`
- `EVAL_TUTOR_BASELINE_JSON`
- `EVAL_TUTOR_OUTPUT_JSON`

Retrieval settings:

- `RAG_PROFILE`
- `RETRIEVAL_MODE`
- `SIMILARITY_TOP_K`
- `ENABLE_RERANKER`
- `RERANK_TOP_N`
- `RERANK_MODEL`
- `DOC_TOP_K`
- `CHUNK_SIZE`
- `CHUNK_OVERLAP`
- `SPLIT_STRATEGY`
- `WINDOW_SIZE`

Допустимые retrieval modes:

- `vector_only`
- `hybrid`
- `bm25_only`
- `doc_then_chunk`

### Path and eval settings

Пути observability, feedback/history, FAQ/index pointers и eval-artifacts читаются через `app/config.py` (`get_settings()`). Модули могут держать module-level `Path` snapshots для совместимости с тестами, но источник env остается `Settings`.

## Функциональные контуры

### Индексация

`app/ingestion.py`:

1. читает документы из `data/`
2. расширяет metadata и строит document summaries
3. режет документы на чанки
4. считает embeddings
5. пишет в staging collections
6. активирует новое поколение через `index_registry.json`

### Query pipeline

Основной путь ответа:

1. input validation
2. input guardrails
3. classify
4. condense истории, если есть `session_id`
5. rewrite, если включен
6. retrieval по выбранной стратегии
7. generation
8. output guardrails
9. history / metrics / FAQ save / async judge

Ключевые модули:

- `app/query_service.py`
- `app/pipeline_runner.py`
- `app/pipeline_steps.py`
- `app/condense_step.py`
- `app/retrieval.py`
- `app/retrieval_strategies.py`
- `app/hybrid_retrieval.py`
- `app/retrieval_cache.py`

### Tutor и multi-turn

- tutor не вынесен в отдельный endpoint; он идет через `POST /ask`
- persistent multi-turn работает через `session_id`
- chat sessions хранятся в `app/session_store.py`
- tutor payload и learner-profile поля нормализуются в `app/query_service.py`

### Knowledge workspace

Система поддерживает:

- topics catalog
- synthesis
- learning plan
- KB overview
- KB search
- KB suggestions

Ключевые модули:

- `app/knowledge_service.py`
- `app/learning_plan_service.py`
- `app/knowledge_graph.py`

### Quiz, review и прогресс

- scoped quiz generation и evaluation
- spaced repetition due reviews
- mastery dashboard
- personalized coach plan
- adaptive daily plan
- personalized learner model

Ключевые модули:

- `app/quiz_service.py`
- `app/quiz_adaptive.py`
- `app/spaced_repetition.py`
- `app/analytics_service.py`
- `app/learner_model_service.py`
- `app/learning_plan_service.py`

## HTTP API

Полный список маршрутов поддерживается в Swagger `/docs`.
Основные группы:

- core
- query
- sessions
- knowledge
- files
- quiz
- review
- dashboard
- sync
- metrics
- admin

Краткая карта — в `api_reference.md`.

## UI и клиенты

- Streamlit — основной пользовательский интерфейс; HTTP-клиент к локальному FastAPI (`app/ui_client.py`)
- CLI (`ask.py`) — прямой вызов `app.query_service.answer_question`, без HTTP (не через `app.api_services`)
- Telegram (`app.telegram_handlers`) — вызовы `app.api_services` (тот же фасад, что HTTP-роутеры), без HTTP

Текущие разделы UI:

- Быстрый ответ
- Чат с тьютором
- Интерактивный Quiz
- Knowledge Graph
- Прогресс обучения
- История
- Темы
- Метрики
- Найти материалы
- Объяснить файл
- Чистый вид

## Наблюдаемость

Система поддерживает:

- request logging
- history persistence
- feedback
- metrics / quality / cost dashboards
- pipeline trace
- SLO alerts
- OTEL tracing optional

## Ограничения

- основной сценарий — локальный single-user instance
- Streamlit и Telegram делят одно локальное состояние, а не облачный аккаунт
- для `.docx` в explain/content нужна зависимость `python-docx`; без неё endpoint вернёт понятную ошибку
- `OFFLINE_MODE` влияет на UX и probes, но не превращает систему в полностью локальный LLM-стек
- часть документов в `doc/` остается roadmap или historical и не должна читаться как runtime-истина
