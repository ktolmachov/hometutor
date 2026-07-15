# Диаграммы hometutor (генерируются из кода и roadmap)

> **НЕ РЕДАКТИРОВАТЬ РУКАМИ.** Файл целиком генерируется скриптом
> `scripts/generate_diagrams.py` из исходников и `docs/agent_roadmap.md`.
> Обновление:
> `python scripts/generate_diagrams.py`; проверка актуальности: `--check`.
> Концептуальные (рукописные) диаграммы живут в [architecture.md](architecture.md).

## 1. Карта HTTP API

Всего маршрутов: **99** в **17** роутерах (источник: `app/routers/*.py`).

```mermaid
flowchart LR
    API["FastAPI app<br/>app/api.py"]
    API --> flashcards["flashcards<br/>19 routes"]
    API --> admin["admin<br/>18 routes"]
    API --> metrics["metrics<br/>15 routes"]
    API --> knowledge["knowledge<br/>11 routes"]
    API --> core["core<br/>6 routes"]
    API --> dashboard["dashboard<br/>5 routes"]
    API --> auth["auth<br/>4 routes"]
    API --> sessions["sessions<br/>4 routes"]
    API --> learner["learner<br/>3 routes"]
    API --> quiz["quiz<br/>3 routes"]
    API --> sync["sync<br/>3 routes"]
    API --> files["files<br/>2 routes"]
    API --> living_konspekt["living_konspekt<br/>2 routes"]
    API --> feedback["feedback<br/>1 routes"]
    API --> query["query<br/>1 routes"]
    API --> review["review<br/>1 routes"]
    API --> ssr["ssr<br/>1 routes"]
```

### `admin` (18)

| Метод | Путь |
|---|---|
| GET | `/cache/stats` |
| GET | `/cache/benchmark` |
| POST | `/reindex` |
| GET | `/reindex/status` |
| GET | `/faq/similar` |
| GET | `/index/stats` |
| GET | `/index/version` |
| GET | `/index/diff` |
| GET | `/learner-state/diagnostics` |
| GET | `/learner-state/archive` |
| POST | `/learner-state/archive/restore` |
| POST | `/learner-state/archive/purge` |
| GET | `/cache/answer-flow-stats` |
| POST | `/cache/answer-flow-reset` |
| GET | `/cache/answer-benchmark` |
| GET | `/profile/query` |
| GET | `/profile/compare` |
| GET | `/profile/compare-eval` |

### `auth` (4)

| Метод | Путь |
|---|---|
| POST | `/auth/register` |
| POST | `/auth/login` |
| GET | `/auth/me` |
| POST | `/auth/logout` |

### `core` (6)

| Метод | Путь |
|---|---|
| GET | `/` |
| GET | `/health` |
| GET | `/learner/state/health` |
| GET | `/ui/bootstrap` |
| GET | `/tutor/example` |
| GET | `/health/deep` |

### `dashboard` (5)

| Метод | Путь |
|---|---|
| GET | `/dashboard/mastery` |
| GET | `/dashboard/coach_plan` |
| GET | `/dashboard/adaptive_daily_plan` |
| GET | `/dashboard/analytics` |
| GET | `/dashboard/offline_status` |

### `feedback` (1)

| Метод | Путь |
|---|---|
| POST | `/ssr/recommendation-feedback` |

### `files` (2)

| Метод | Путь |
|---|---|
| GET | `/explain/file` |
| GET | `/content/file` |

### `flashcards` (19)

| Метод | Путь |
|---|---|
| POST | `/flashcards/generate` |
| POST | `/flashcards/decks` |
| POST | `/flashcards/decks/import-quiz` |
| GET | `/flashcards/bootstrap` |
| GET | `/flashcards/decks` |
| GET | `/flashcards/decks/{deck_id}` |
| GET | `/flashcards/decks/{deck_id}/progress` |
| DELETE | `/flashcards/decks/{deck_id}` |
| GET | `/flashcards/due/count` |
| GET | `/flashcards/due` |
| POST | `/flashcards/due/recovery` |
| GET | `/flashcards/due/schedule` |
| POST | `/flashcards/due/recovery/undo` |
| POST | `/flashcards/review` |
| POST | `/flashcards/review/undo` |
| PUT | `/flashcards/cards/{card_id}` |
| POST | `/flashcards/cards` |
| DELETE | `/flashcards/cards/{card_id}` |
| GET | `/flashcards/decks/{deck_id}/export/anki` |

### `knowledge` (11)

| Метод | Путь |
|---|---|
| GET | `/topics` |
| POST | `/synthesize` |
| POST | `/learning-plan` |
| GET | `/kb/graph/prerequisites-health` |
| GET | `/kb/graph/next-best-actions` |
| GET | `/kb/learner/profile-history` |
| GET | `/kb/learning-plan/graph-bundle` |
| GET | `/kb/source-readiness` |
| GET | `/kb/overview` |
| GET | `/kb/search` |
| GET | `/kb/suggestions` |

### `learner` (3)

| Метод | Путь |
|---|---|
| GET | `/learner/goal-snapshot` |
| PUT | `/learner/goal-snapshot` |
| DELETE | `/learner/goal-snapshot` |

### `living_konspekt` (2)

| Метод | Путь |
|---|---|
| GET | `/living-konspekt/workbench/status` |
| GET | `/living-konspekt/video-citation/open` |

### `metrics` (15)

| Метод | Путь |
|---|---|
| GET | `/metrics` |
| GET | `/metrics/quality` |
| GET | `/metrics/cost` |
| GET | `/metrics/dashboard` |
| GET | `/metrics/learner` |
| GET | `/metrics/educational` |
| GET | `/metrics/mastery-validation` |
| GET | `/metrics/alerts` |
| POST | `/metrics/knowledge-workflow` |
| GET | `/metrics/knowledge-workflow` |
| POST | `/feedback` |
| GET | `/metrics/feedback` |
| GET | `/metrics/store` |
| GET | `/history` |
| GET | `/pipeline/trace` |

### `query` (1)

| Метод | Путь |
|---|---|
| POST | `/ask` |

### `quiz` (3)

| Метод | Путь |
|---|---|
| POST | `/quiz/generate` |
| POST | `/quiz/generate/scoped` |
| POST | `/quiz/evaluate` |

### `review` (1)

| Метод | Путь |
|---|---|
| GET | `/review/due` |

### `sessions` (4)

| Метод | Путь |
|---|---|
| GET | `/sessions` |
| GET | `/sessions/{session_id}` |
| PATCH | `/sessions/{session_id}/metadata` |
| DELETE | `/sessions/{session_id}` |

### `ssr` (1)

| Метод | Путь |
|---|---|
| POST | `/ssr/explain` |

### `sync` (3)

| Метод | Путь |
|---|---|
| GET | `/sync/export` |
| POST | `/sync/import` |
| GET | `/sync/telegram` |

## 2. Граф зависимостей слоёв

Агрегировано по module-level импортам `app/**` (AST). Число на ребре — количество импортов.
Инвариант гвардов: UI не импортируется backend'ом; провайдер и конфиг — стоки.

```mermaid
flowchart TD
    ui["UI (Streamlit)"]
    routers["HTTP routers"]
    apiapp["API app слой"]
    services["Сервисы (домены)"]
    prompts["Промпты"]
    retrieval["Retrieval / Index"]
    graph["Граф знаний"]
    state["State (SQLite)"]
    provider["Провайдер LLM"]
    config["Конфиг"]
    ui -->|115| services
    services -->|53| config
    retrieval -->|47| services
    routers -->|37| services
    services -->|25| retrieval
    routers -->|25| apiapp
    services -->|21| state
    apiapp -->|18| services
    services -->|18| prompts
    apiapp -->|17| routers
    services -->|16| graph
    ui -->|14| config
    services -->|13| provider
    retrieval -->|10| config
    graph -->|8| services
    state -->|8| services
    provider -->|7| services
    apiapp -->|6| retrieval
    ui -->|6| retrieval
    apiapp -->|5| config
    retrieval -->|5| graph
    ui -->|5| state
    routers -->|5| config
    retrieval -->|4| provider
    routers -->|4| state
    state -->|3| config
    ui -->|3| provider
    graph -->|2| config
    retrieval -->|2| prompts
    provider -->|2| config
    apiapp -->|1| graph
    apiapp -->|1| provider
    services -->|1| apiapp
    graph -->|1| prompts
    retrieval -->|1| state
    routers -->|1| provider
    ui -->|1| prompts
```

### Импорты UI из backend-слоёв (включая ленивые)

Нарушений нет ✅

## 3. Схемы хранилищ (SQLite)

Из `CREATE TABLE` DDL в `app/*.py`. Связи — по `REFERENCES`.

### `auth_db.py` — data/auth.db (3 табл.)

```mermaid
erDiagram
    users {
        TEXT id PK
        TEXT email
        TEXT password_hash
        TEXT display_name
        TEXT created_at
        TEXT last_login_at
    }
    auth_sessions {
        TEXT id PK
        TEXT user_id
        TEXT issued_at
        TEXT expires_at
        INTEGER revoked
        TEXT user_agent
    }
    auth_audit_log {
        INTEGER id PK
        TEXT user_id
        TEXT event
        TEXT ip
        TEXT created_at
    }
    users ||--o{ auth_sessions : "user_id"
    users ||--o{ auth_audit_log : "user_id"
```

### `event_tracking.py` — см. `app/event_tracking.py` (1 табл.)

```mermaid
erDiagram
    ui_events {
        INTEGER id PK
        TEXT event_name
        TEXT ts
        TEXT user_id
        TEXT payload_json
    }
```

### `metrics_db.py` — см. `app/metrics_db.py` (2 табл.)

```mermaid
erDiagram
    dashboard_bucket {
        TEXT granularity
        TEXT bucket_id
        TEXT payload
    }
    dashboard_meta {
        TEXT k PK
        TEXT v
    }
```

### `request_cache.py` — см. `app/request_cache.py` (1 табл.)

```mermaid
erDiagram
    llm_request_cache {
        TEXT request_hash PK
        TEXT response_json
        REAL created_at
    }
```

### `session_store.py` — см. `app/session_store.py` (1 табл.)

```mermaid
erDiagram
    sessions {
        TEXT session_id PK
        TEXT messages
        TEXT last_updated
        TEXT created_at
    }
```

### `user_state_db.py` — data/user_state.db (или data/users/<user_id>/…) (18 табл.)

```mermaid
erDiagram
    reading_status {
        INTEGER id PK
        TEXT resource_type
        TEXT resource_id
        INTEGER step_index
        TEXT step_label
        REAL progress
        TEXT display_title
        TEXT index_version
        TEXT updated_at
        RESOURCE_ID) UNIQUE(resource_type,
    }
    annotations {
        INTEGER id PK
        TEXT resource_type
        TEXT resource_id
        TEXT kind
        TEXT body
        TEXT created_at
    }
    research_sessions {
        INTEGER id PK
        TEXT name
        TEXT payload_json
        TEXT index_version
        TEXT created_at
        TEXT updated_at
    }
    quiz_results {
        INTEGER id PK
        TEXT concept
        TEXT level
        REAL score
        TEXT timestamp
        INTEGER attempt_number
        TEXT generation_id
        INTEGER index_version
    }
    spaced_repetition {
        TEXT concept PK
        REAL easiness
        INTEGER interval_days
        INTEGER repetitions
        TEXT next_review
        TEXT last_review
        TEXT generation_id
        INTEGER index_version
    }
    quiz_mastery {
        TEXT concept PK
        TEXT current_level
        INTEGER success_streak
        TEXT last_updated
        TEXT generation_id
        INTEGER index_version
    }
    spaced_repetition_archive {
        INTEGER id PK
        TEXT concept
        REAL easiness
        INTEGER interval_days
        INTEGER repetitions
        TEXT next_review
        TEXT last_review
        TEXT source_generation_id
        INTEGER source_index_version
        TEXT target_generation_id
        INTEGER target_index_version
        TEXT archived_at
        TEXT archived_reason
    }
    quiz_mastery_archive {
        INTEGER id PK
        TEXT concept
        TEXT current_level
        INTEGER success_streak
        TEXT last_updated
        TEXT source_generation_id
        INTEGER source_index_version
        TEXT target_generation_id
        INTEGER target_index_version
        TEXT archived_at
        TEXT archived_reason
    }
    learner_profile_migration_log {
        INTEGER id PK
        TEXT event_type
        TEXT source_generation_id
        INTEGER source_index_version
        TEXT target_generation_id
        INTEGER target_index_version
        TEXT migrated_at
        TEXT archived_counts_json
        TEXT stamped_counts_json
        TEXT live_counts_json
        TEXT diagnostics_json
    }
    micro_quiz_events {
        INTEGER id PK
        TEXT topic
        TEXT feedback_json
        TEXT next_step_json
        TEXT created_at
    }
    tutor_learning_resume {
        INTEGER id PK
        TEXT session_id
        TEXT topic
        TEXT mastery_level
        TEXT last_action_kind
        TEXT last_action_label
        TEXT quiz_feedback_json
        TEXT recommended_next_json
        INTEGER due_reviews_count
        TEXT updated_at
        TEXT index_version
    }
    learner_goal_snapshot {
        INTEGER id PK
        INTEGER schema_version
        TEXT topic
        TEXT subtopic
        TEXT target_level
        TEXT desired_outcome
        INTEGER time_budget_min
        TEXT preferred_style
        TEXT learning_goal
        TEXT updated_at
    }
    flashcard_decks {
        INTEGER id PK
        TEXT name
        TEXT source_type
        TEXT source_id
        INTEGER card_count
        TEXT created_at
        TEXT updated_at
    }
    flashcards {
        INTEGER id PK
        INTEGER deck_id
        TEXT front
        TEXT back
        TEXT tags
        REAL easiness
        INTEGER interval_days
        INTEGER repetitions
        TEXT next_review
        TEXT last_review
        TEXT created_at
        TEXT updated_at
    }
    flashcard_review_log {
        INTEGER id PK
        INTEGER card_id
        INTEGER deck_id
        INTEGER quality
        REAL easiness_before
        REAL easiness_after
        INTEGER interval_before
        INTEGER interval_after
        INTEGER repetitions
        TEXT reviewed_at
    }
    app_kv {
        TEXT key PK
        TEXT value
        TEXT updated_at
    }
    ssr_recommendation_feedback {
        INTEGER id PK
        TEXT action
        TEXT hint_kind
        TEXT primary_nav
        TEXT weak_concept_sha256
        INTEGER why_now_len
        TEXT explanation_outcome
        REAL latency_ms
        TEXT session_key_prefix
        TEXT created_at
    }
    ssr_route_impressions {
        INTEGER id PK
        TEXT hint_kind
        TEXT primary_nav
        TEXT session_key_prefix
        TEXT created_at
    }
    flashcard_decks ||--o{ flashcards : "deck_id"
```

## 4. Фичи UI по уровням опыта

Всего фич: **24** (источник: `app/ui/feature_registry.py::FEATURES`).

```mermaid
flowchart TB
    subgraph T1["Уровень 1"]
        view_mission_control["Главная - Mission Control<br/><i>nav</i>"]
        view_quick_answer["Быстрый ответ с источниками<br/><i>nav</i>"]
        view_search["Поиск по материалам<br/><i>nav</i>"]
        view_explain_file["Объяснить файл<br/><i>nav</i>"]
    end
    subgraph T2["Уровень 2"]
        view_tutor["Чат с тьютором<br/><i>nav</i>"]
        view_quiz["Интерактивный Quiz<br/><i>nav</i>"]
        view_flashcards["Flashcards и повторения<br/><i>nav</i>"]
        view_progress["Прогресс обучения<br/><i>nav</i>"]
        view_topics["Темы и каталог<br/><i>nav</i>"]
    end
    subgraph T3["Уровень 3"]
        view_course["Курс и Course Cockpit<br/><i>nav</i>"]
        view_adaptive_plan["Адаптивный план<br/><i>nav</i>"]
        view_knowledge_graph["Граф знаний<br/><i>nav</i>"]
        view_living_konspekt["Живой конспект<br/><i>nav</i>"]
        view_history["История запросов<br/><i>nav</i>"]
        sidebar_research_sessions["Research-сессии<br/><i>sidebar</i>"]
    end
    subgraph T4["Уровень 4"]
        view_metrics["Метрики качества и стоимости<br/><i>nav</i>"]
        view_print["Чистый вид (печать)<br/><i>nav</i>"]
        page_analytics["Страница «Аналитика»<br/><i>page</i>"]
        sidebar_sync_backup["Backup, QR-перенос и восстановление<br/><i>sidebar</i>"]
        sidebar_expert_filters["Фильтры области поиска Q&A<br/><i>sidebar</i>"]
        panel_voice["Голосовой ввод и озвучка<br/><i>panel</i>"]
    end
    subgraph T5["Уровень 5"]
        panel_expert_controls["Экспертные панели в учебных режимах<br/><i>panel</i>"]
        panel_debug_summary["Debug: маршрутизация, trace, стоимость<br/><i>panel</i>"]
        panel_index_freshness["Версия и поколение индекса<br/><i>panel</i>"]
    end
    T1 --> T2
    T2 --> T3
    T3 --> T4
    T4 --> T5
```

Тиры 1-5 в `feature_registry.py` не изменились, но control-panel пресеты (`app/ui_preferences.py`)
с 2026-07 схлопнуты в три: **Учёба** = тиры 1-2, **Полный** = тир 3, **Диагностика** = тиры 4-5
(старые значения `"1".."5"`/`"all"` мигрируют на чтении). См. `docs/user_guide.md#панель-управления-и-уровни-интерфейса`.

## 5. AI-агент: целевой flow и gates

Overlay по `docs/agent_roadmap.md`. `app/agent/*` и compact `agent_runs` /
`agent_steps` уже есть в runtime-коде; agent-router, recovery-resume и HITL
остаются будущими волнами.

### Runtime-встраивание

Компактная схема намеренно избегает широких subgraph-контейнеров: детали контрактов и DoD вынесены в gates ниже, чтобы Mermaid не обрезался в preview.

```mermaid
flowchart TB
    ask["/ask"]
    prep["prepare ctx"]
    budget["budget"]
    branch{"agent?"}
    main["current RAG"]
    runner["runner FSM"]
    decision["decision"]
    scenarios["W1A-C scenarios"]
    tools["read tools"]
    stop["stop controller"]
    state["W2 compact state"]
    obs["W2 debug run_id"]
    hitl["W5 HITL"]
    write["W5 write tools"]
    ask --> prep --> budget --> branch
    branch -- no --> main
    branch -- yes --> runner
    runner --> decision --> scenarios --> tools
    runner --> stop
    runner -. Wave 2 .-> state
    runner -. Wave 2 .-> obs
    runner -. Wave 5 .-> hitl --> write
```

### Зависимости волн

```mermaid
flowchart TB
    W0["W0<br/>provider"]
    W1["W1<br/>read-only"]
    W1A["W1A<br/>study"]
    W1B["W1B<br/>graph gaps"]
    W1C["W1C<br/>konspekt"]
    W2["W2<br/>state + obs"]
    W3["W3<br/>context"]
    W4["W4<br/>eval gate"]
    W5["W5<br/>writes + HITL"]
    W6["W6<br/>plan + memory"]
    W0 --> W1 --> W1A --> W1B --> W1C --> W2 --> W3 --> W4 --> W5 --> W6
    W4 -. blocks writes .-> W5
    W4 -. proves ceiling .-> W6
```

### Release gates

| Волна | Блокирующий gate | Почему это критично |
|---|---|---|
| Wave 0 | Mock-тест доказывает, что `tools`/`tool_choice`/`response_format` доходят до OpenAI payload; structured/tool kwargs обходят cache; схемы инструментов учтены в input-token estimate. | Без этого agent-loop может зависнуть на cache-hit или пробить guard ещё до первого tool-вызова. |
| Wave 1 | Только read-only tools; `rag.answer` принудительно non-agent; каждый stop reason покрыт тестом runner'а. | Это удерживает MVP от рекурсии, записей в state и бесконтрольного ReAct-цикла. |
| Wave 1A | `study_session` собирает объяснение, mini-quiz и flashcard-кандидаты как draft без записи в базы. | Это первый полезный пользовательский сценарий поверх read-only агента. |
| Wave 1B | `graph_gap_finder` находит пробелы и prerequisite-chain по графу знаний + mastery без изменения graph bundle. | Граф становится учебной навигацией, а не только визуализацией. |
| Wave 1C | `living_konspekt_coach` предлагает, что добавить/повторить/проверить в Живом конспекте, но не меняет workbench. | Конспект становится активной учебной поверхностью без ранних writes. |
| Wave 2 | Текущий slice сохраняет compact `agent_runs`/`agent_steps` и отдаёт `run_id` в `/ask` debug; полный gate добавит span/log/Langfuse/cost, recovery-resume и read-only introspection router. | Без наблюдаемой траектории agent невозможно отлаживать и превращать prod-fail в eval. |
| Wave 3 | Стабильный static prefix; ToolResult offload; 10+ шагов не пробивают hard token limit. | Native tools и длинные runs безопасны только при дисциплине контекста. |
| Wave 4 | `scripts/agent_gate_v1.py` зелёный: trajectory checks, injection cases, pass^k, baseline без деградации. | Это обязательный предохранитель перед write-инструментами. |
| Wave 5 | Нулевая запись без approve; idempotency-key UNIQUE; approve/reject/double-resume/timeout покрыты eval и тестами. | Write tools должны быть обратимы по смыслу, наблюдаемы и защищены от retry-дублей. |
| Wave 6 | Планировщик и memory проходят A/B через eval_baseline; supervisor разрешён только при доказанном потолке single-agent. | Иначе plan-execute/memory/supervisor добавят сложность без измеримой пользы. |
