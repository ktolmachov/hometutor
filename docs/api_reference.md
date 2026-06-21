# HTTP API

Актуализировано по коду на **2026-05-20** (опциональный `HOME_RAG_API_KEY` / `X-API-Key` на защищённых REST-маршрутах).

Живая схема API: `GET /docs` и `GET /redoc`.

## Общие замечания

- Базовый локальный URL по умолчанию: `http://127.0.0.1:8000`
- **Опциональная auth:** если в `.env` задан `HOME_RAG_API_KEY` (алиас `API_KEY`), защищённые endpoints требуют заголовок `X-API-Key: <значение>`. Без переменной — dev/demo, REST без ключа. Публично без ключа: `GET /health`, `GET /health/deep`, `GET /ui/bootstrap`.
- Middleware ставит `X-Request-ID`; `POST /ask` дополнительно прокидывает его в `debug.request_id`
- Типовые ошибки:
  - `400` — input validation / input guardrails
  - `401` — неверный или отсутствующий `X-API-Key` при настроенном `HOME_RAG_API_KEY`
  - `404` — файл не найден
  - `409` — reindex уже идет
  - `422` — output guardrails
  - `503` — пустой индекс или reindex in progress

## Роутеры

| Тег | Модуль | Основные пути |
|---|---|---|
| `core` | `app/routers/core.py` | `/`, `/health`, `/health/deep`, `/ui/bootstrap`, `/tutor/example` |
| `query` | `app/routers/query.py` | `/ask` |
| `sessions` | `app/routers/sessions.py` | `/sessions`, `/sessions/{session_id}` |
| `knowledge` | `app/routers/knowledge.py` | `/topics`, `/synthesize`, `/learning-plan`, `/kb/*` |
| `learner` | `app/routers/learner.py` | `/learner/goal-snapshot` |
| `ssr-feedback` | `app/routers/feedback.py` | `/ssr/recommendation-feedback` |
| `quiz` | `app/routers/quiz.py` | `/quiz/generate`, `/quiz/evaluate` |
| `review` | `app/routers/review.py` | `/review/due` |
| `flashcards` | `app/routers/flashcards.py` | `/flashcards/*` |
| `dashboard` | `app/routers/dashboard.py` | `/dashboard/*` |
| `sync` | `app/routers/sync.py` | `/sync/export`, `/sync/import`, `/sync/telegram` |
| `files` | `app/routers/files.py` | `/explain/file`, `/content/file` |
| `metrics` | `app/routers/metrics.py` | `/metrics/*`, `/feedback`, `/history`, `/pipeline/trace` |
| `admin` | `app/routers/admin.py` | `/reindex`, `/index/*`, `/cache/*`, `/profile/*`, `/faq/similar` |

## Learner goal snapshot (E24-B)

Персистентный снимок полей в форме `goal_context` (совместим с E24-A / `build_learner_goal_context_dict`). Хранится в SQLite (`user_state`). Для `POST /ask` см. ниже: незаполненные в теле поля `tutor_goal_*` могут быть дополнены из снимка (`subtopic`, `target_level`, `desired_outcome`, `time_budget_min`); явные поля запроса имеют приоритет.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/learner/goal-snapshot` | Текущий снимок или `goal_context: null`, если строки нет |
| PUT | `/learner/goal-snapshot` | Upsert снимка; тело — опциональные поля `topic`, `subtopic`, `target_level`, `desired_outcome`, `time_budget_min`, `preferred_style`, `learning_goal` |
| DELETE | `/learner/goal-snapshot` | Удалить снимок (`{"status": "cleared"}`) |

## SSR misroute feedback (L5 data foundation)

Локальная запись реакций пользователя на рекомендацию Smart Study Router **без** изменения политики маршрутизации. В SQLite сохраняются только `action` (`accept` | `reject` | `defer`), `hint_kind`, `primary_nav`, опционально SHA-256 слабого концепта, длина текста «Почему сейчас» (число), метаданные объяснения — **без** свободного текста объяснения и без сырого названия темы.

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/ssr/recommendation-feedback` | Тело: `action`, `hint_kind`, `primary_nav`, опционально `weak_concept_sha256` (64 hex), `why_now_len`, `explanation_outcome`, `latency_ms`, `session_key_prefix`. Ответ: `{"status":"ok","id":<row_id>}` или `422` при неверных полях |

## Core

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` | Корень API |
| GET | `/health` | Быстрый healthcheck |
| GET | `/health/deep` | Проверка API, индекса и LLM |
| GET | `/ui/bootstrap` | Стартовый пакет для Streamlit |
| GET | `/tutor/example` | Примеры tutor-запросов |

## `POST /ask`

Главный endpoint для Q&A, tutor и multi-turn.

Основные поля запроса:

- `question`
- `folder`
- `folder_rel`
- `file_name`
- `relative_path`
- `topic`
- `homework_mode`
- `assistance_level`
- `homework_level`
- `study_mode`
- `followup_context`
- `session_id`
- `query_mode`
- `quiz_learning_mode`
- `profile` - optional public RAG profile override. Accepted values:
  `fast`, `quality`, `graph_aware`. Raw `retrieval_mode` is not accepted on
  public `/ask`; it remains config/debug/admin-only.
- `tutor_goal_subtopic` — опционально, узкий фокус цели в tutor loop (E24-A)
- `tutor_goal_target_level` — опционально, желаемый уровень (короткая строка)
- `tutor_goal_desired_outcome` — опционально, формулировка желаемого результата
- `tutor_goal_time_budget_min` — опционально, бюджет времени в минутах (1–240)

Для каждого поля `tutor_goal_*`: если в теле оно не задано (`null`/не передано), а в SQLite есть строка `learner_goal_snapshot`, сервер подставляет соответствующее значение из `goal_context` до валидации: `subtopic` → `tutor_goal_subtopic`, `target_level` → `tutor_goal_target_level`, `desired_outcome` → `tutor_goal_desired_outcome`, `time_budget_min` → `tutor_goal_time_budget_min`. Явно заданное поле не перезаписывается снимком.

**Streamlit (локальный UI):** при старте вкладки один раз за сессию браузера поля `goal_context` из SQLite подмешиваются в `st.session_state` (цель, подтема, бюджет и т. д., без перезаписи уже заполненных значений). После CTA «Учить эту тему 5 минут» на вкладке «Быстрый ответ» снимок обновляется через `upsert_learner_goal_snapshot`.

Ключевые особенности:

- `query_mode="tutor"` включает tutor route
- `session_id` включает persisted multi-turn
- `quiz_learning_mode` управляет режимом prompt-шаблона для quiz
- `profile` selects a validated RAG profile and is serialized internally as
  `rag_profile`; unknown profiles return `invalid_profile` with the valid list.
- поля `tutor_goal_*` нормализуются на сервере; в ответе tutor-путь отражает их в `learner_profile.goal_context` (и внутренний снимок `learner_goal_context`)

Ключевые поля ответа:

- `answer`
- `sources`
- `confidence`
- `tutor` — только если включен tutor path (`tutor_cycle`, `orchestration_state`, `tutor_orchestration_pipeline`, `tutor_pipeline`, `socratic`, `auto_quiz`, `policy_clamped`, `policy_clamp_reasons`, …)
- `tutor_answer` — нормализованный teaching-контракт (если есть)
- `debug`

Стабильные tutor-поля, на которые можно опираться вне `debug`:

- `tutor.tutor_cycle`
- `tutor.orchestration_state`
- `tutor.tutor_orchestration_pipeline`
- `tutor.tutor_pipeline`
- `tutor.socratic`
- `tutor.policy_clamped`
- `tutor.policy_clamp_reasons`

Практический смысл typed tutor полей:

- `tutor_orchestration_pipeline` — компактный маршрут оркестрации педагогического решения
- `tutor_pipeline` — summary шагов tutor pipeline в read-friendly контракте
- `policy_clamped` / `policy_clamp_reasons` — признак и причины policy clamp поверх tutor decision

В `debug` могут приходить:

- timings (`pipeline_ms`, `engine_acquire_ms`, `query_execute_ms`, `total_answer_ms`)
- `query_type`
- retrieval info
- `token_usage`
- `estimated_cost_usd`
- `quality_checks`
- `pipeline_trace`
- `retrieval_trace`
- `retrieval_routing` / `pipeline_trace.retrieval_routing` when route decisions
  are available. The trace includes selected/effective profile and retrieval
  mode, graph augmentation decision, fallback reason, classify inputs, and
  whether the profile came from an explicit request.
- `guardrails`
- `request_id`

## Sessions

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/sessions` | Список сессий |
| GET | `/sessions/{session_id}` | Одна сессия (messages + metadata; **404**, если записи в БД нет) |
| PATCH | `/sessions/{session_id}/metadata` | Частичный merge JSON в `session_metadata` |
| DELETE | `/sessions/{session_id}` | Удаление сессии |

## Global Analytics

Design-time specification. Implementation in a future package.

| Метод | Путь | Назначение | Статус |
|-------|------|------------|--------|
| POST | `/global-analytics` | Запуск job глобального анализа корпуса | Design — реализация отложена |
| GET | `/global-analytics/<job_id>` | Статус и результат job | Design — реализация отложена |
| GET | `/global-analytics` | Список всех jobs | Design — реализация отложена |

Design details: [`adr_021a_global_analytics_design.md`](adr_021a_global_analytics_design.md).

Строгие границы (ADR-021 §4.3):
- `global_graph` НЕ добавляется в `KNOWN_RETRIEVAL_MODES`
- `/ask` endpoint НЕ содержит fallback на global analytics
- `POINT /global-analytics` — явный, scoped, потенциально long-running

## Knowledge

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/topics` | Каталог тем и документов |
| POST | `/synthesize` | Конспект по теме или подборке документов |
| POST | `/learning-plan` | Learning plan по теме или подборке |
| GET | `/kb/source-readiness` | Readiness summary for indexed source coverage and source-state checks |
| GET | `/kb/overview` | Сводка по knowledge base |
| GET | `/kb/search` | Поиск по темам, документам и концептам |
| GET | `/kb/suggestions` | Related topics и unexplored documents |

`POST /learning-plan` принимает `topic`, `topic_id`, `documents`, `goal`, `level`, `time_budget_hours`, `known_topics`, `user_progress`.

## Quiz и Review

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/quiz/generate` | Генерация quiz по теме или документу |
| POST | `/quiz/evaluate` | Проверка micro-quiz ответа; в теле ответа — `diagnostic_feedback_status` (`recognized` / `recalled` / `misconception` / `cannot_apply`) |
| GET | `/review/due` | Просроченные повторения |

`POST /quiz/generate`:

- `scope`: `document` или `topic`
- для `document`: `relative_path` или `identifier`
- для `topic`: `topic_id`, `topic_name` или `identifier`; опциональный `documents: list[str]` ограничивает quiz конкретными файлами (course-scope)
- `num_questions`: 5..8
- `difficulty`
- `learning_mode`

**Course scope:** только `/flashcards/generate` (с `scope=course` и `source_paths`) поддерживает course-scope как первоклассный параметр. `/quiz/generate` и `/synthesize` принимают `documents` для scope-ограничения; `/learning-plan` — аналогично через `documents`. `/ask` (тьютор) фильтрует поиск через `folder_rel` при активном курсе.

Скрытый alias для совместимости:

- `POST /quiz/generate/scoped` — исключен из схемы, но поддерживается

## Flashcards

| Method | Path | Purpose |
|---|---|---|
| POST | `/flashcards/generate` | Generate flashcards for a document, uploaded content, or active-course batch (`scope`: `document` / `upload` / `course`; course uses `source_paths`) |
| POST | `/flashcards/decks` | Save a flashcard deck (`cards`: **≥ 5** items; fewer → validation error, typically HTTP **400**) |
| GET | `/flashcards/decks` | List flashcard decks |
| GET | `/flashcards/decks/{deck_id}` | Read one flashcard deck |
| DELETE | `/flashcards/decks/{deck_id}` | Delete a flashcard deck |
| GET | `/flashcards/due/count` | Count due flashcards |
| GET | `/flashcards/due` | List due flashcards |
| POST | `/flashcards/due/recovery` | Defer tail of due queue (shift `next_review` beyond first `keep_limit` cards; optional `deck_id`, `tags`, `keep_limit`, `stagger_days`) |
| GET | `/flashcards/due/schedule` | Nearest future review date/count and safely undoable recovery count |
| POST | `/flashcards/due/recovery/undo` | Return never-reviewed cards deferred by recovery to the due queue (optional `deck_id`, `tags`) |
| POST | `/flashcards/review` | Record flashcard review outcome |
| PUT | `/flashcards/cards/{card_id}` | Update one flashcard |
| POST | `/flashcards/cards` | Add one flashcard |
| DELETE | `/flashcards/cards/{card_id}` | Delete one flashcard |
| GET | `/flashcards/decks/{deck_id}/export/anki` | Export deck as Anki `.apkg` |

## Dashboard

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/dashboard/mastery` | Mastery dashboard |
| GET | `/dashboard/coach_plan` | Персональный coach plan |
| GET | `/dashboard/adaptive_daily_plan` | Adaptive daily plan |
| GET | `/dashboard/analytics` | Расширенная аналитика |
| GET | `/dashboard/offline_status` | Offline flag и provider probe |

## Files

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/explain/file` | Краткое объяснение файла из `data/` |
| GET | `/content/file` | Содержимое файла для preview |

Ограничение:

- поддерживаются `.txt`, `.md`, `.html`, `.pdf`, `.docx` (для `.docx` нужен пакет `python-docx`)

## Sync

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/sync/export` | Полный JSON-снимок локального состояния |
| POST | `/sync/import` | Импорт snapshot; перезаписывает локальные таблицы |
| GET | `/sync/telegram` | Справка по локальной связке Telegram и UI |

## Metrics, Feedback, History

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/metrics` | Общие runtime metrics |
| GET | `/metrics/quality` | Quality metrics |
| GET | `/metrics/cost` | Cost dashboard |
| GET | `/metrics/dashboard` | Сводный metrics dashboard |
| GET | `/metrics/learner` | Learner migration and profile metrics |
| GET | `/metrics/educational` | Aggregated quiz correctness, retention, transfer, SRS stability, and micro-quiz parse metrics |
| GET | `/metrics/mastery-validation` | Mastery/quiz correlation, transfer state, and false-positive graduation signals |
| GET | `/metrics/alerts` | SLO и anomaly alerts |
| POST | `/metrics/knowledge-workflow` | Логирование knowledge workflow событий |
| GET | `/metrics/knowledge-workflow` | Чтение knowledge workflow метрик |
| POST | `/feedback` | Пользовательский feedback |
| GET | `/metrics/feedback` | Сводка по feedback |
| GET | `/metrics/store` | Сырые записи metrics store |
| GET | `/history` | История запросов |
| GET | `/pipeline/trace` | Pipeline trace по запросам |

## Admin

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/reindex` | Запуск reindex |
| GET | `/reindex/status` | Статус reindex |
| GET | `/index/stats` | Статистика индекса |
| GET | `/index/version` | Версия и metadata поколения индекса |
| GET | `/index/diff` | Diff файлов после индексации |
| GET | `/faq/similar` | Похожие вопросы из FAQ memory |
| GET | `/cache/stats` | Состояние cache |
| GET | `/cache/benchmark` | Бенч cache для query engine |
| GET | `/cache/answer-flow-stats` | Статистика answer flow |
| POST | `/cache/answer-flow-reset` | Сброс answer flow stats |
| GET | `/cache/answer-benchmark` | Бенч answer flow |
| GET | `/learner-state/diagnostics` | Learner-state diagnostics and migration health |
| GET | `/profile/query` | Профилирование одного запроса |
| GET | `/profile/compare` | Сравнение двух конфигураций |
| GET | `/profile/compare-eval` | Сравнение двух конфигураций с eval |
