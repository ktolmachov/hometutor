# Техническая спецификация hometutor

Актуализировано по runtime-коду: 2026-06-24.

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

В этом runtime-репозитории нет `ask.py`, `run_eval.py`, `run_eval_compare.py` и `tests/` как локальных entrypoints/каталогов.

## Стек

- Python, FastAPI, Uvicorn
- Streamlit
- llama-index
- Chroma
- BM25 / hybrid retrieval
- pydantic-settings
- aiogram
- SQLite
- OpenTelemetry optional
- pytest dependency в `requirements.txt` для test-capable окружений

## Конфигурация

`app/config.py` загружает:

1. `config.env` — tracked defaults;
2. `.env` — локальные секреты и overrides.

Ключевые группы настроек:

| Группа | Переменные |
|---|---|
| API/auth | `HOME_RAG_API_KEY`, `API_KEY`, CORS/rate-limit settings |
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

## Хранилища и артефакты

| Артефакт | Назначение |
|---|---|
| `data/` | исходные документы и `user_state.db` |
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

- Основной сценарий — локальный single-user runtime.
- Runtime-репозиторий не содержит полный процессный backlog, сценарные манифесты и генератор demo-документа.
- `OFFLINE_MODE` и offline banners не заменяют настройку локального LLM/embedding endpoint.
- При облачном LLM/embedding provider пользовательские данные могут уходить внешнему провайдеру.
- `HOME_RAG_API_KEY` защищает REST endpoints только если задан.
