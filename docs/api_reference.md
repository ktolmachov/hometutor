# HTTP API

Актуализировано по `app/api.py` и `app/routers/*`: 2026-06-24.

Живая схема API доступна после запуска сервера:

- Swagger: `GET /docs`
- ReDoc: `GET /redoc`
- Health: `GET /health`

Базовый локальный URL: `http://127.0.0.1:8000`.

## Auth и общие правила

- `GET /`, `GET /health`, `GET /health/deep`, `GET /learner/state/health`, `GET /ui/bootstrap`, `GET /tutor/example` и `POST /ssr/explain` подключены без `require_api_key`.
- Остальные роутеры подключены с `require_api_key`.
- Если `HOME_RAG_API_KEY` или `API_KEY` не заданы, защищённые endpoints работают без ключа в dev/demo режиме.
- Если ключ задан, передавайте `X-API-Key: <value>`.
- Middleware добавляет `X-Request-ID`; `/ask` также отдаёт request id в debug payload.

Типовые ошибки:

| Код | Когда |
|---|---|
| `400` | input validation, guardrails, неверный пользовательский payload |
| `401` | отсутствует или неверен `X-API-Key` при настроенном ключе |
| `404` | файл, сессия, deck или другой ресурс не найден |
| `409` | reindex уже идёт |
| `422` | output guardrails / request validation |
| `503` | пустой индекс, reindex in progress, недоступный runtime dependency |

## Карта роутеров

| Тег | Модуль | Пути |
|---|---|---|
| `core` | `app/routers/core.py` | `/`, `/health`, `/health/deep`, `/learner/state/health`, `/ui/bootstrap`, `/tutor/example` |
| `ssr` | `app/routers/ssr.py` | `/ssr/explain` |
| `query` | `app/routers/query.py` | `/ask` |
| `sessions` | `app/routers/sessions.py` | `/sessions`, `/sessions/{session_id}`, `/sessions/{session_id}/metadata` |
| `knowledge` | `app/routers/knowledge.py` | `/topics`, `/synthesize`, `/learning-plan`, `/kb/*` |
| `learner` | `app/routers/learner.py` | `/learner/goal-snapshot` |
| `ssr-feedback` | `app/routers/feedback.py` | `/ssr/recommendation-feedback` |
| `quiz` | `app/routers/quiz.py` | `/quiz/generate`, `/quiz/generate/scoped`, `/quiz/evaluate` |
| `review` | `app/routers/review.py` | `/review/due` |
| `flashcards` | `app/routers/flashcards.py` | `/flashcards/*` |
| `dashboard` | `app/routers/dashboard.py` | `/dashboard/*` |
| `sync` | `app/routers/sync.py` | `/sync/export`, `/sync/import`, `/sync/telegram` |
| `files` | `app/routers/files.py` | `/explain/file`, `/content/file` |
| `metrics` | `app/routers/metrics.py` | `/metrics/*`, `/feedback`, `/history`, `/pipeline/trace` |
| `admin` | `app/routers/admin.py` | `/reindex`, `/index/*`, `/cache/*`, `/profile/*`, `/learner-state/*`, `/faq/similar` |
| `debug` | `app/routers/debug_session_tape.py` | `/debug/session-tape/{session_id}` |

## Core

| Method | Path | Назначение |
|---|---|---|
| GET | `/` | корень API |
| GET | `/health` | быстрый healthcheck |
| GET | `/health/deep` | API + индекс + LLM readiness |
| GET | `/learner/state/health` | health learner-state слоя |
| GET | `/ui/bootstrap` | стартовый payload для Streamlit |
| GET | `/tutor/example` | примеры tutor-запросов |

## Query: `POST /ask`

Главный endpoint для Q&A, tutor и multi-turn.

| Method | Path | Назначение |
|---|---|---|
| POST | `/ask` | Q&A, tutor route, multi-turn и RAG profile selection |

Основные поля:

- `question`
- `folder`, `folder_rel`, `file_name`, `relative_path`
- `topic`
- `session_id`
- `query_mode`
- `profile`: `fast`, `quality`, `graph_aware`
- `homework_mode`, `assistance_level`, `homework_level`, `study_mode`
- `quiz_learning_mode`
- `followup_context`
- `tutor_goal_subtopic`, `tutor_goal_target_level`, `tutor_goal_desired_outcome`, `tutor_goal_time_budget_min`

Особенности:

- `query_mode="tutor"` включает tutor route.
- `session_id` включает persisted multi-turn.
- `profile` валидируется как public RAG profile; raw `retrieval_mode` не является публичным параметром `/ask`.
- Незаполненные `tutor_goal_*` могут быть дополнены из learner goal snapshot.

Ключевые поля ответа:

- `answer`
- `sources`
- `confidence`
- `tutor` и `tutor_answer`, если включён tutor path
- `debug`

В `debug` могут быть timings, usage/cost, retrieval trace, routing, guardrails, pipeline trace и request id.

## SSR

| Method | Path | Назначение |
|---|---|---|
| POST | `/ssr/explain` | server-side SSR explanation path; streaming/SSE совместимый слой объяснений |
| POST | `/ssr/recommendation-feedback` | локальная запись `accept/reject/defer` feedback по рекомендации |

Feedback сохраняет структурные поля рекомендации и технические метаданные без свободного текста объяснения.

## Learner goal snapshot

| Method | Path | Назначение |
|---|---|---|
| GET | `/learner/goal-snapshot` | прочитать текущий snapshot |
| PUT | `/learner/goal-snapshot` | upsert `goal_context` |
| DELETE | `/learner/goal-snapshot` | очистить snapshot |

Snapshot может подмешиваться в `/ask` для tutor goal fields.

## Knowledge

| Method | Path | Назначение |
|---|---|---|
| GET | `/topics` | каталог тем и документов |
| POST | `/synthesize` | конспект по теме или документам |
| POST | `/learning-plan` | learning plan |
| GET | `/kb/graph/prerequisites-health` | диагностика prerequisite-графа |
| GET | `/kb/graph/next-best-actions` | graph-aware следующие действия |
| GET | `/kb/learner/profile-history` | история learner profile |
| GET | `/kb/learning-plan/graph-bundle` | graph bundle для learning plan |
| GET | `/kb/source-readiness` | readiness источников |
| GET | `/kb/overview` | обзор базы знаний |
| GET | `/kb/search` | поиск по KB |
| GET | `/kb/suggestions` | suggestions |

## Quiz и review

| Method | Path | Назначение |
|---|---|---|
| POST | `/quiz/generate` | сгенерировать quiz |
| POST | `/quiz/generate/scoped` | compatibility alias, исключён из OpenAPI |
| POST | `/quiz/evaluate` | оценить ответ |
| GET | `/review/due` | due concept-level reviews |

## Flashcards

| Method | Path | Назначение |
|---|---|---|
| POST | `/flashcards/generate` | preview карточек по document/upload/course |
| POST | `/flashcards/decks` | сохранить колоду |
| POST | `/flashcards/decks/import-quiz` | создать колоду из quiz items |
| GET | `/flashcards/bootstrap` | due count + deck list одним запросом |
| GET | `/flashcards/decks` | список колод |
| GET | `/flashcards/decks/{deck_id}` | чтение колоды |
| GET | `/flashcards/decks/{deck_id}/progress` | прогресс колоды |
| DELETE | `/flashcards/decks/{deck_id}` | удалить колоду |
| GET | `/flashcards/due/count` | число due карточек |
| GET | `/flashcards/due` | due карточки |
| POST | `/flashcards/due/recovery` | разнести хвост очереди |
| GET | `/flashcards/due/schedule` | ближайшее расписание и undoable count |
| POST | `/flashcards/due/recovery/undo` | вернуть ещё не повторённые deferred cards |
| POST | `/flashcards/review` | записать SM-2 review |
| PUT | `/flashcards/cards/{card_id}` | обновить карточку |
| POST | `/flashcards/cards` | добавить карточку |
| DELETE | `/flashcards/cards/{card_id}` | удалить карточку |
| GET | `/flashcards/decks/{deck_id}/export/anki` | экспорт `.apkg` |

## Dashboard

| Method | Path | Назначение |
|---|---|---|
| GET | `/dashboard/mastery` | mastery dashboard |
| GET | `/dashboard/coach_plan` | coach plan |
| GET | `/dashboard/adaptive_daily_plan` | adaptive daily plan |
| GET | `/dashboard/analytics` | analytics |
| GET | `/dashboard/offline_status` | offline/provider status |

## Sessions

| Method | Path | Назначение |
|---|---|---|
| GET | `/sessions` | список сессий |
| GET | `/sessions/{session_id}` | чтение сессии |
| PATCH | `/sessions/{session_id}/metadata` | merge metadata |
| DELETE | `/sessions/{session_id}` | удалить сессию |

## Files

| Method | Path | Назначение |
|---|---|---|
| GET | `/explain/file` | объяснить файл |
| GET | `/content/file` | preview содержимого |

Поддерживаемые форматы preview/explain: `.txt`, `.md`, `.html`, `.pdf`, `.docx`.

## Sync

| Method | Path | Назначение |
|---|---|---|
| GET | `/sync/export` | JSON snapshot локального состояния |
| POST | `/sync/import` | импорт snapshot |
| GET | `/sync/telegram` | справка по Telegram sync |

## Metrics и history

| Method | Path | Назначение |
|---|---|---|
| GET | `/metrics` | runtime metrics |
| GET | `/metrics/quality` | quality metrics |
| GET | `/metrics/cost` | cost dashboard |
| GET | `/metrics/dashboard` | dashboard summary |
| GET | `/metrics/learner` | learner metrics |
| GET | `/metrics/educational` | educational metrics |
| GET | `/metrics/mastery-validation` | validation metrics |
| GET | `/metrics/alerts` | alerts |
| POST | `/metrics/knowledge-workflow` | записать workflow event |
| GET | `/metrics/knowledge-workflow` | прочитать workflow metrics |
| POST | `/feedback` | user feedback |
| GET | `/metrics/feedback` | feedback summary |
| GET | `/metrics/store` | raw metrics store |
| GET | `/history` | история запросов |
| GET | `/pipeline/trace` | pipeline trace |

## Admin и debug

| Method | Path | Назначение |
|---|---|---|
| POST | `/reindex` | запустить reindex |
| GET | `/reindex/status` | статус reindex |
| GET | `/faq/similar` | похожие FAQ-вопросы |
| GET | `/index/stats` | статистика индекса |
| GET | `/index/version` | версия индекса |
| GET | `/index/diff` | diff файлов |
| GET | `/learner-state/diagnostics` | diagnostics/migration health |
| GET | `/learner-state/archive` | список архивных snapshots |
| POST | `/learner-state/archive/restore` | восстановить snapshot |
| POST | `/learner-state/archive/purge` | очистить archive |
| GET | `/cache/stats` | cache stats |
| GET | `/cache/benchmark` | query engine cache benchmark |
| GET | `/cache/answer-flow-stats` | answer-flow stats |
| POST | `/cache/answer-flow-reset` | reset answer-flow stats |
| GET | `/cache/answer-benchmark` | answer benchmark |
| GET | `/profile/query` | профиль одного запроса |
| GET | `/profile/compare` | сравнение конфигураций |
| GET | `/profile/compare-eval` | eval-сравнение |
| GET | `/debug/session-tape/{session_id}` | gated debug replay session tape |
