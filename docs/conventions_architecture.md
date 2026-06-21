# Соглашения: архитектура и дерево проекта

Роль: детальный слой к [conventions.md](conventions.md). Для агентов — не подтягивать целиком без задачи на соответствующий контур.

## Архитектурные соглашения

### Контракт доступа к конфигурации

- Параметры из окружения (`.env` / env vars) читаются **только** через `get_settings()` и `get_retrieval_settings()` из `app/config.py` (модели `Settings`, `RetrievalSettings`). Не импортировать «текущие значения» как глобальные снимки, кроме тестов и самого `config.py`.
- Infrastructure toggles (например log rotation / OTel / local profiling) тоже объявляются в `Settings`; `app/logging_config.py` и observability-модули не читают raw env как источник конфигурации.
- **Исключение:** диагностические функции, читающие raw `os.environ` для сравнения (например с `dotenv_values` из файла), должны быть явно задокументированы как diagnostic-only и не использоваться как источник настроек в бизнес-логике.
- Пути артефактов observability: `metrics_store_path`, `metrics_dashboard_db_path`, `llm_cost_log_dir` в `Settings` (env `METRICS_STORE_PATH`, `METRICS_DASHBOARD_DB_PATH`, `LLM_COST_LOG_DIR`); `app/metrics.py` использует снимок при импорте (`METRICS_STORE_PATH` / `METRICS_DASHBOARD_DB_PATH` из `get_settings()`), тесты могут патчить атрибуты модуля.
- Константы путей: `BASE_DIR`, `DATA_DIR`, `LOG_DIR`, `CHROMA_DIR` в `app/config.py` — допустимые инфраструктурные пути (без семантики env как бизнес-настройки). Например `logging_config.setup_logging()` использует `LOG_DIR`.
- Прямой доступ `app.config.<поле>` вне `config.py` и `tests/test_config.py` — не использовать; в коде приложения — только getters.
- Новый параметр: поле в `Settings`/`RetrievalSettings` + `Field`/валидаторы при необходимости → чтение через `get_settings()` / `get_retrieval_settings()`.

### Контракт SQLite / локальных хранилищ

- Таблицы пользовательского состояния, learning state, flashcards, SRS, goal snapshots и sync bundle живут в `app/user_state.py` и должны проходить через `_with_db()` / CRUD-хелперы этого модуля. Сервисам, роутерам и UI нельзя открывать SQLite-соединения к этим таблицам напрямую.
- Отдельные локальные SQLite-хранилища допустимы, когда это не user-state БД, а самостоятельный store wrapper или артефакт со своей ответственностью:
  - `app/session_store.py` — `SessionStore` для истории chat/tutor сессий (`sessions.db`) и LRU-кэша; внешние модули используют `session_store`, а не прямой `sqlite3`.
  - `app/event_tracking.py` — backend-safe event hooks (`ui_events.db`) для аналитических событий сервисного слоя без зависимости от Streamlit/UI.
  - `app/metrics.py` — observability cache/store: JSONL `metrics_store_path` и SQLite dashboard cache `metrics_dashboard_db_path` из `Settings`; тесты могут патчить модульные path-атрибуты.
  - `app/knowledge_graph_bundle.py` — per-generation/staging artifact `kg.sqlite` рядом с `property_graph_store.json`; это часть index bundle lifecycle, а не user-state БД.
- `app/knowledge_graph.py` не является владельцем SQLite: чтение/запись `kg.sqlite` должны проходить через wrapper-функции `app/knowledge_graph_bundle.py`.
- Новый SQLite store вне `user_state.py` допускается только если он задокументирован здесь: указаны владелец модуля, файл/путь, кто имеет право вызывать wrapper, участвует ли store в backup/sync, и какие focused tests покрывают деградацию/миграцию. Роутеры, UI и сервисы не должны встраивать ad hoc SQL вместо обращения к владельцу store.

### Прочее

- Конфигурация читается из `.env` через `app/config.py` (pydantic-settings: `Settings`, `RetrievalSettings`).
- Доступ к настройкам — через `get_settings()` / `get_retrieval_settings()`.
- `resolve_query_execution_plan` и `_faq_cache_policy` в `app/retrieval.py` читают `enable_faq_cache` через `get_settings`, импортированный в **этом** модуле. В тестах при проверке FAQ-ветки нужно патчить `app.retrieval.get_settings` (и при необходимости `app.query_service.get_settings`), иначе подмена только в `query_service` не меняет политику в `retrieval`.
- LLM и embedding-клиенты создаются через `app/provider.py` (`get_llm()`, `get_embed_model()`).
- Общая pipeline-логика живет в `app/pipeline_factory.py`.
- Оркестрация query pipeline живет в `app/pipeline_runner.py` и `app/pipeline_steps.py`; новые шаги должны использовать контракт `process(QueryContext) -> QueryContext`.
- `app/retrieval.py` и `app/pipeline_profiler.py` должны использовать один и тот же источник pipeline-конфигурации.
- Retrieval-стратегии (`vector_only`, `hybrid`, `bm25_only`, `doc_then_chunk`) регистрируются в `app/retrieval_strategies.py` (`STRATEGY_REGISTRY`); `build_query_engine` в `app/retrieval.py` вызывает `build_query_engine_for_retrieval_mode`. Новый режим: добавить билдер в реестр, значение в `KNOWN_RETRIEVAL_MODES` в `config.py`, проводку через `QueryContext` / `PipelineOverrides` — без ad hoc во вьюхах.
- **RAG profiles (ADR-021):** user-facing labels (`fast`, `quality`, `graph_aware`) не являются retrieval mode constants и не добавляются в `KNOWN_RETRIEVAL_MODES`. Они должны резолвиться через profile registry / `RagProfile` contract в зарегистрированный retrieval mode плюс bounded параметры (`top_k`, reranker, `graph_augmented`). Public API принимает profile name и валидирует его против `KNOWN_PROFILES`; raw `retrieval_mode` остаётся config/debug/admin surface. `graph_aware` — это профиль с bounded graph expansion поверх зарегистрированного retrieval mode, а не новый mode name. **ADR-021a:** dispositions дополнительных audit lifts (split router/profile resolver, strategy decorators, внешние profile assets, opt-in `/debug/route`, `/ask` dry-run, graph shadow-mode, политика устойчивости retrieval-router) см. [`doc/adr_021a_smart_router_architecture_lifts.md`](adr_021a_smart_router_architecture_lifts.md); текст ADR-021a не меняет код по умолчанию — реализуется отдельными execution-пакетами.
- **Graph-augmented retrieval (итерация 17 Core, E4 multi-hop + observability):** опционально через `Settings.enable_graph_augmented_retrieval` / `graph_augment_max_extra_docs` / `graph_expand_max_hops`; расширение чанков для `query_type` `synthesis` и `learning_plan` — `app/graph_retrieval.py` (postprocessor после rerank; `expand_doc_ids_via_graph` — волны обхода prerequisites/related_concepts). **ADR-021 Phase 2:** композитный gating включается на контуре `/ask`/pipeline с `QueryContext`: `confidence ≥ graph_augment_min_confidence`, `routing.effective_graph_augmented`, и (`thin baseline` по числу узлов после dedupe **или** явный профиль `graph_aware`). Дочерние чанки несут `metadata.retrieval_source="graph_expansion"` и сериализуемые `metadata.graph_evidence` (`GraphEvidence` в `app/models.py`: relation_id, direction, evidence_doc_id, confidence, weak/inferred rendering). Trace: `QueryContext.trace["graph_expansion"]` — в т. ч. опционально `graph_evidence` (сводка рёбер) и `weak_graph_evidence_count`. Отдельные агрегаты latency: `app/metrics.py`, `summarize_metrics_store` включает `graph_expansion` и `route_demotion` (`app/metrics_slo.record_route_demotion_event` для offline uplift/demotion scaffolding). Компактный `graph_expansion` в JSONL request-событиях усиливает `weak_graph_evidence_count` / `graph_evidence_items`. В Streamlit см. блок в `app/ui/debug_panel.py`. CLI-отчёт: `scripts/graph_expansion_benchmark.py`. Не путать с `enable_self_correction` (tutor/orchestrator).
- **Retrieval self-correction:** `enable_retrieval_self_correction`, `retrieval_self_correction_min_score`, `retrieval_weak_context_disclaimer` в `Settings`; один retry с альтернативной формулировкой (`rewritten_query` или первый subquestion) в `answer_question`, только если не `query_mode=tutor`. Trace: `ctx.trace["retrieval_self_correction"]`.
- **Индекс / blue-green:** канонический указатель активной generation — `app/index_registry.py` → файл `index_registry.json` (или `INDEX_REGISTRY_PATH`), с `FileLock` и миграцией с `chroma_db/active_index.json`. Активация staging и `reset=True` обновляют registry и инкрементируют `index_version`. Chroma: `app/chroma_vector_backend.py` (`get_default_chroma_backend(persist_dir)`), тот же путь, что `ingestion.CHROMA_DIR` / `retrieval_cache._chroma_dir()`. Резервное копирование артефактов индекса — `app/index_backup.py` и `scripts/backup_index.py`; политика reindex/reset и производных файлов — [doc/index_lifecycle.md](index_lifecycle.md).
- **Сессии чата / tutor:** при сохранении ответа с `session_id` в `Message.metadata` допускаются поля `tutor`, `tutor_answer`, компактный список `sources` (для UI и списка источников в trust-панели). Не класть в metadata полные тексты чанков без лимита — см. `_compact_sources_for_session` в `app/query_service.py`.
- **Tutor orchestration (E6.0–E6.1):** при `query_mode=tutor` до retrieval выполняется `build_tutor_pipeline()` (`orchestrate_pedagogical_action_step` → `execute_specialized_agent_step` → `self_correction_and_compose_step`). Контракт для UI/debug: `QueryContext.metadata["tutor_orchestration_pipeline"]` (`schema_version`, `phase`: `orchestrate` → `rag_prepare` → `pre_generate`, `selected_agent`, `should_trigger_microquiz`, `decision_source`: `llm` \| `rule_fallback` \| `disabled` \| `skipped_no_learner_profile`, опционально `policy_clamped` / `policy_clamp_reasons` после E6.1). Порядок и итог шагов: `QueryContext.trace["tutor_pipeline"]` (список `{step, status[, detail]}`); `trace["orchestrator_policy_clamp"]` — итог policy-clamp. Сбой JSON/LLM или исключение в шаге оркестрации → `make_rule_fallback_orchestrator_decision` (ConceptExplainer, без micro-quiz). **E6.1 (core):** `app/tutor_personalization_policy.py` — `personalization_hints`, `attach_personalization_policy_to_learner_profile`, `apply_orchestrator_policy_clamp` (due review / quiz emphasis). **E6.2 (surfaces):** ответ `/ask` с `query_mode=tutor` включает в `tutor` поля `tutor_orchestration_pipeline`, `tutor_pipeline` (при наличии); typed `orchestration_state` в KV может дополняться снимком pipeline. Typed снимок для API (`tutor.orchestration_state`) по-прежнему в `app/tutor_learner_contract.py` (не путать с pipeline-контрактом). `app/orchestrator_router.PedagogicalRouter` — альтернативный entrypoint; источник истины для HTTP tutor — пайплайн в `pipeline_steps`.
- **Streamlit UI:** опционально `show_tutor_dev_tools` в `Settings` / env `SHOW_TUTOR_DEV_TOOLS` — показ сырого шаблона квиза на вкладке чата тьютора (по умолчанию выключено). Базовый URL API: `ui_api_base_url`.
- Общие утилиты (safe_preview и т.п.) — в `app/utils.py`, не дублировать по модулям.
- Guardrails (input/output) вынесены в `app/guardrails.py`, используются из API, CLI и UI.
- Knowledge-oriented сценарии инкапсулируются в `app/knowledge_service.py`; UI и API не должны дублировать бизнес-логику topic catalog, synthesis и KB search.
- **Knowledge Encapsulation:** роутеры (`app/routers/*.py`) не должны импортировать `app.knowledge_graph` или `app.user_state_core` напрямую; доступ только через `*_service.py` фасады.
- Работа с файлами из `data/` должна проходить через безопасную проверку пути.
- Просмотр содержимого как plain text разрешен только для поддерживаемых текстовых форматов.
- **Flashcards (E12, US-15.x):** HTTP-контракт — `app/routers/flashcards.py` (генерация, CRUD колод/карт, due, review, экспорт Anki). Бизнес-логика и LLM-генерация — `app/flashcard_service.py`. Таблицы `flashcard_decks` / `flashcards` в SQLite — `app/user_state.py` (`_ensure_schema`, CRUD-хелперы). Общий билдер `.apkg` без зависимости от UI — `app/export_utils.py` (вызов из `flashcard_service.export_deck_to_anki`).

## Структура проекта

Актуальные ключевые директории и файлы:

```text
`PROJECT_ROOT_PATH`/
├── main.py
├── ask.py
├── ingest.py
├── run_eval.py
├── run_eval_compare.py
├── .streamlit/                  # config.toml (тема UI и др.)
├── app/
│   ├── api.py                   # FastAPI: lifespan, middleware, include_router
│   ├── api_services.py          # Фасад сервисов для роутеров
│   ├── api_requests.py
│   ├── api_models.py
│   ├── api_helpers.py
│   ├── middleware.py
│   ├── routers/                 # Доменные HTTP-роутеры (итерация 15+)
│   │   ├── core.py, query.py, admin.py, knowledge.py, metrics.py, files.py
│   │   ├── sessions.py, quiz.py, review.py, flashcards.py, sync.py, dashboard.py
│   ├── config.py
│   ├── provider.py
│   ├── logging_config.py
│   ├── ingestion.py
│   ├── index_registry.py       # index_registry.json, активация generation
│   ├── chroma_vector_backend.py # обёртка PersistentClient для ingestion/retrieval/stats
│   ├── retrieval_cache.py
│   ├── pipeline_factory.py
│   ├── pipeline_steps.py        # classify, condense (multi-turn), rewrite, tutor/orchestrator steps, run_step_safe
│   ├── condense_step.py         # логика шага condense (история сессии)
│   ├── pipeline_runner.py       # Оркестрация, resolve_retrieval_strategy
│   ├── query_routing.py
│   ├── hybrid_retrieval.py
│   ├── retrieval_strategies.py   # реестр режимов retrieval (vector_only, hybrid, bm25_only, doc_then_chunk)
│   ├── retrieval.py
│   ├── query_service.py
│   ├── knowledge_service.py
│   ├── flashcard_service.py     # E12: генерация колод, SM-2 по карточке, Anki export
│   ├── guardrails.py
│   ├── input_validation.py
│   ├── utils.py
│   ├── prompts.py
│   ├── pipeline_profiler.py
│   ├── eval_service.py
│   ├── async_quality_judge.py
│   ├── compare_eval.py
│   ├── explain_service.py
│   ├── faq_memory.py
│   ├── index_diff.py
│   ├── metrics.py               # runtime-метрики, metrics_store, SLO/alerts
│   ├── export_utils.py          # общий экспорт (Anki APKG), без зависимости от app/ui
│   ├── event_tracking.py        # backend-safe хуки событий для сервисного слоя (SQLite, без Streamlit/UI)
│   ├── otel_tracing.py          # опциональный OTLP (ENABLE_OTEL_TRACING)
│   ├── history_service.py
│   ├── feedback_service.py
│   ├── knowledge_graph.py
│   ├── learner_model_service.py # Personalized Learner Model 19.5 (профиль оркестратора, KV app_kv)
│   ├── ui/                      # main.py, pages/, constants, styles, helpers, widgets, hero, session_state, …
│   └── models.py                # QueryOptions, PipelineOverrides, QueryContext
├── data/
│   └── graph_analytics/         # Global analytics artifacts (design-time — ADR-021 Phase 4)
│       └── jobs/<job_id>/       # metadata.json, result.json, ceiling_violation.json
├── doc/
├── eval_data/
├── tests/
└── requirements.txt
```
