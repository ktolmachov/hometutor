# AI-агент в hometutor: архитектура и волновая дорожная карта

Актуализировано: 2026-07-10.
Статус: Wave 1A–1C MVP (`study_session`, `graph_gap_finder`,
`living_konspekt_coach`) реализованы поверх Wave 1 Foundation; Wave 2
получила первый persistence/observability slice для `agent_runs`/`agent_steps`.
Это **канонический**
документ; внешний session-plan `d-ai-app-data-4-noble-pine.md` (вне этого
репозитория) устарел и не является источником истины.
Основание: курс «AI-агенты» (уроки 1–5) + курс «Deep Agents» (модули 1–8);
рекомендации лекций смаппированы на текущую кодовую базу (см. § Traceability).
Правки после код-аудита (2026-07-10) сведены в § 8.

---

## 1. Контекст и мотивация

Сегодня `hometutor` отвечает на вопросы фиксированным линейным RAG-пайплайном:
`/ask` → guardrails → classify → condense → rewrite → retrieval (hybrid BM25+vector,
RRF, reranker, graph-expansion) → LLM-синтез → постобработка. Агентного цикла и
tool calling нет: система не может динамически выбирать действия (поискать ещё,
посмотреть профиль ученика, сгенерировать квиз, предложить карточки) и останавливаться
по условию.

Ближайший «прото-агент» в коде:

- `app/tutor_orchestrator.py::invoke_pedagogical_orchestrator_llm` — одноразовое
  LLM-решение (`response_format=json_object`, `temperature=0`, нормализация,
  rule-fallback). Паттерн переиспользуется в decision-слое агента.
- `app/orchestrator_router.py::PedagogicalRouter` — реестр псевдо-агентов:
  экспериментальный/альтернативный роутер, импортируемый из tutor-кода, но не
  подменяющий основной `/ask` pipeline без явного вызова. Паттерн реестра
  переиспользуется в tool registry.

Harness-примитивы из лекций уже наполовину есть и переиспользуются:

| Примитив (лекции) | Уже есть в hometutor |
|---|---|
| Guardrails вход/выход | `app/guardrails.py`, `app/input_validation.py` |
| Structured logs + request_id | `app/logging_config.py`, `app/middleware.py` |
| Трейсинг span'ов | `app/otel_tracing.py` (`trace_tool_span`), `app/langfuse_trace_export.py` |
| Учёт токенов/стоимости | `app/usage_cost.py`, `app/llm_guards.py` (JSONL cost-log) |
| Circuit breaker / fallback | `app/llm_local_circuit.py`, `app/llm_resilience.py` |
| Evals + baseline gates | `app/eval_service.py`, `app/eval_baseline.py`, `scripts/home_rag_*_v1.py` |
| Feature flags | `app/ui/feature_registry.py`, `app/config.py` |

Пробелы (Gap 1–7): (1) нет tool-loop и stop controller; (2) structured output
только `json_object` (без строгой схемы); (3) общий streaming-путь пока не имеет
полноценного учёта стоимости, поэтому provider сейчас вызывает chat с
`stream=False`; (4) `HARD_TOKEN_LIMIT=20_000` (`app/llm_guards.py`) ограничивает
накапливающийся контекст; (5) нет `run_id` для мультишаговых прогонов; (6)
дедуп-кэш ответов может закэшировать промежуточный шаг цикла; (7) качество
tool-calling локальной модели (llama.cpp) не подтверждено.

Факт про транспорт: `app/provider_openai.py::OpenAI._chat` и `_achat` передают
kwargs в `chat.completions.create` через `_get_model_kwargs(**kwargs)`, а
импортированный из llama-index `from_openai_message` используется для сборки
`ChatResponse`. Поэтому native tools API **предположительно достижим** без
переписывания транспорта, но Wave 0 обязан mock-тестом доказать, что
`tools`/`tool_choice` реально доходят до payload. `app/llm_resilience.py::
chat_with_resilience` тоже форвардит kwargs (fallback-цепочка сохраняется).

---

## 2. Целевая архитектура

### 2.1 Агентный цикл — параллельный поток, не pipeline-шаг

Вход по `query_mode == "agent"` внутри `answer_question`
(`app/query_service.py:906`), после `_prepare_query_context` (guardrails/classify
уже отработали). Агентный поток идёт **внутри budget-wrapper'а** наравне с
main-flow, чтобы бесплатно переиспользовать latency-budget:

```python
def _budgeted_answer():
    if options.query_mode == "agent" and settings.agent_enabled:
        return run_agent_flow(question, options, ctx, ...)   # app/agent/__init__.py (facade)
    return _answer_question_main_flow(...)
budget = with_budget(surface, _budgeted_answer)
```

Обоснование: контракт `process(QueryContext)->QueryContext` линеен —
многошаговый FSM-цикл в него не помещается; RAG-пайплайн становится
**инструментом агента** (агент над пайплайном); бесплатно переиспользуются
input-guardrails, latency budget, обработка исключений и конверт `AskResponse` —
UI/CLI/Telegram не меняются. `QueryContext.metadata`/`trace` — scratchpad агента
(`ctx.trace["agent"]`).

Важно про recursion guard: инструменты `rag.answer`/`rag.search` **обязаны**
вызывать non-agent путь (main-flow / приватный RAG-helper), а не
`answer_question(..., query_mode="agent")` — иначе получим рекурсию
agent → tool → agent.

Важно про trace: `history_service.get_pipeline_trace(request_id)` читает
`debug.pipeline_trace` из history JSONL (`app/history_service.py:204`) — агентная
траектория туда сама не попадает. Текущий Wave 2 slice пишет компактный
`debug.agent_trace.run_id` и append-only записи `agent_runs`/`agent_steps`.
Публичный read-only `GET /agent/runs` и `GET /agent/runs/{run_id}` реализован в A2 (этот документ описывает состояние на момент написания более ранних секций).
Старый pipeline-trace не ломается.

### 2.2 Пакет `app/agent/`

```
app/agent/
  __init__.py          # фасад: run_agent_flow(...)
  contracts.py         # ToolSpec (name, when_to_use, args: Pydantic strict, limits,
                       #   access: read|write, idempotent) + ToolResult {ok, data, error, meta}
                       #   + AgentState (running/tool_call/repairing/stopped/completed)
  tool_registry.py     # реестр rag.* / learner.* / quiz.* / cards.*; to_openai_tools()
  tools_rag.py         # rag.search (retrieval-only) / rag.answer (non-agent full pipeline)
  tools_learner.py     # learner.get_profile, progress.get_mastery, graph.inspect,
                       #   konspekt.inspect — learner_model_service, quiz_adaptive,
                       #   knowledge_graph, workbench_service
  tools_quiz.py        # quiz_service
  tools_flashcards.py  # cards.get_due / cards.propose; write tools — Wave 5
  scenarios.py         # Wave 1A–1C: intent-роутер (konspekt → graph_gap →
                       #   study_session) + сценарные промпты/output-контракты
  decision.py          # два бэкенда: JSON-decision + native tools; repair <= 1
  runner.py            # AgentRunner: FSM running/tool_call/repairing/stopped/completed;
                       #   переход = запись + reason (guardrail-стоп = STOPPED +
                       #   StopReason.GUARDRAIL_TRIGGERED, отдельного guarded-состояния нет)
  stop_controller.py   # resource/tool/quality/control-стопы -> StopDecision(reason)

  # Ещё не созданы (план, см. Wave 2/3/5):
  context_builder.py   # KV-cache дисциплина: статичный префикс, компакция, offloading
  state.py             # обёртка над user_state_agent_runs (run_id, step_id,
                       #   checkpoint/recovery, idempotency keys) + needs_human FSM (Wave 5)
  tracing.py           # span на шаг через otel_tracing.trace_tool_span; run_id; usage/cost
```

Вне пакета (по конвенциям репо):

- `app/user_state_agent_runs.py` — таблицы `agent_runs`, `agent_steps`
  (+ позже `agent_memory`) в `_ensure_schema` (`app/user_state_db.py`);
  state только через `user_state*.py`.
- Промпты агента (`AGENT_SYSTEM_PROMPT`, `AGENT_DECISION_USER_TEMPLATE`) —
  в `app/prompts/_impl.py` рядом с `ORCHESTRATOR_SYSTEM_PROMPT`, зарегистрированы
  в `PROMPTS`/`PROMPT_VERSIONS` под ключами `"agent_system"` / `"agent_decision"`.
  Сценарные промпты Wave 1A–1C зарегистрированы там же под ключами
  `"agent_study_session"`, `"agent_graph_gap_finder"`,
  `"agent_living_konspekt_coach"`.
- Флаги — только через `get_settings()` (`app/config.py`): `agent_enabled=False`,
  `agent_tool_call_mode: json|native|auto` (`auto` = native для cloud-путей при
  consent, JSON-decision для локальной модели), `agent_max_steps=6`,
  `agent_max_run_tokens`, `agent_max_run_cost_usd`, `agent_max_run_seconds`.
  Эти флаги уже заведены в `app/config.py`, `.env.example` и `config.env`;
  дальнейшие настройки добавлять во все три места одновременно.
- Read-only роутер `app/routers/agent.py` (A2): `GET /agent/runs`, `GET /agent/runs/{run_id}` реализован и зарегистрирован с `_protected_dependencies`. (POST /resume — Wave 5 HITL, не в scope.)
- UI-фича: `FeatureSpec("view:agent_session")` с `requires=("agent_enabled",)` объявлен в `feature_registry.py`, плитка «Агент» на Mission Control и dedicated view присутствуют. Ветка `agent_enabled` в `requirement_context_ok` покрыта тестами.

### 2.3 Стартовый набор инструментов (read-only в Wave 1 / 1A–1C)

| Инструмент | Обёртка над | access |
|---|---|---|
| `rag.search` | **retrieval-only adapter**: `retriever.retrieve(QueryBundle)` напрямую (как в extractive-ветке `query_rag_execution.py:165`), НЕ `execute_rag_query` (тот запускает генерацию) | read |
| `rag.answer` | non-agent полный pipeline: `answer_question(sub_question, QueryOptions(query_mode=None))` (повторно проходит guardrails/classify/condense/rewrite, но без ветки agent) либо приватный RAG-helper; как «умный инструмент» | read |
| `learner.get_profile` | `learner_model_service.get_personalized_learner_profile` (реализовано; `build_tutor_session_state` пока не используется этим tool'ом) | read |
| `cards.get_due` | `user_state_flashcards.get_due_flashcards` | read |
| `cards.propose` | кандидатные flashcards/cloze из ответа, конспекта или quiz-контекста; **без сохранения** до Wave 5 | read/draft |
| `progress.get_mastery` | обёртка над `quiz_adaptive.py::list_quiz_mastery_state` / `get_weak_concepts` / `get_all_mastery_levels` (реализовано в `tools_learner.py`); `learner_state_scope.get_quiz_mastery_rows_for_kg` и `analytics_service.get_advanced_analytics` существуют в коде, но этим tool'ом пока не используются | read |
| `quiz.generate` | `quiz_service.generate_topic_quiz` (без записи) | read |
| `graph.inspect` | read-only adapter над active knowledge graph / mastery-вектором: узлы, соседние связи, prerequisites, слабые/изолированные концепты | read |
| `konspekt.inspect` | `workbench_service.load_rows` / `normalize_runtime_rows` + helpers Living Konspekt для coverage/selected rows; без изменения корзины | read |
| Wave 5: `cards.save_deck`, `sr.update_card`, `quiz.record_result` | flashcard_service / `update_flashcard_sr` | write + idempotency-key + HITL |

Примечания к адаптерам (из аудита):
- `rag.search` — чистый retrieval; `execute_rag_query` не подходит, т.к. его
  extractive early-exit условный (`_two_stage_eligible` + пороги score/nodes),
  иначе идёт LLM-синтез.
- `rag.answer` — принудительно non-agent путь (иначе рекурсия).
- `progress.get_mastery` — read-API для mastery уже есть, но разнесён по
  модулям (`quiz_adaptive.py::list_quiz_mastery_state` / `get_weak_concepts` /
  `get_all_mastery_levels`, `learner_state_scope.get_quiz_mastery_rows_for_kg`);
  нужен тонкий агрегирующий helper, не ad hoc SQL в tool-коде. (Примечание:
  `user_state_quiz.py` mastery не управляет — там только `quiz_results` и
  `micro_quiz_events`; mastery-стек живёт в `quiz_adaptive.py`.)

Правила контрактов (Урок 2/3): args — Pydantic strict, enum вместо свободных
строк; `ToolResult{ok,data,error}`; лимиты на размер результата;
`user_id`/`session_id` инжектятся harness'ом из auth-контекста — модель их
**не выбирает** (least privilege, Урок 5).

### 2.4 Правки provider-слоя (точечные)

1. **Сделано.** `provider_openai.py`: **bypass дедуп-кэша** при наличии
   `tools`/`tool_choice`/`response_format` в kwargs — **в обеих ветках**:
   `_has_structured_or_tool_kwargs()` (`provider_openai.py:74-88`), используется
   в sync `_chat` (`:433`, bypass-флаг `:446`, пропуск `cache.set` `:500`) и в
   async `_achat` (`:511`, флаг `:523-524`, пропуск `cache.set` `:570`). Причина:
   `request_cache._hash_request` (`request_cache.py:109`) хэширует только
   `model/messages/temperature/max_tokens/top_p` и полностью игнорирует
   `tools`/`tool_choice`/`response_format`, поэтому два разных structured/tool-шага
   с одинаковыми messages дали бы cache-hit → «зависший» агент. Покрыто тестами
   в `tests/test_provider_openai_structured.py`.
2. **Сделано.** Учёт токенов схем инструментов при оценке `input_tokens` **в
   provider-layer**: `_estimate_structured_kwargs_tokens()`
   (`provider_openai.py:91-109`), используется на `:276-277`
   (`schema_tokens = _estimate_structured_kwargs_tokens(kwargs, self.model)`,
   сложение с `message_tokens` перед `llm_guards.check_input_tokens` на `:282`)
   — сам `check_input_tokens` принимает уже готовое число, поэтому правка идёт в
   оценку, а не в guard. Покрыто тестами в
   `tests/test_provider_openai_structured.py`.
3. **Не сделано (план, Wave 3).** Роль-геттеры в `app/provider.py` по образцу `_build_role_llm`:
   `get_agent_planner_llm()` (сильная модель), `get_agent_executor_llm()`
   (дешёвая/локальная для компакции). **Consent enforced кодом**: cloud-модель
   для planner допускается только при `home_rag_llm_cloud_consent` (проверка в
   геттере, а не по одному лишь cloud model id — `_build_role_llm` сам consent
   не проверяет).
4. Стриминг агентных шагов — осознанный non-goal (`stream=False`), чтобы не
   терять cost-tracking до отдельного решения общего streaming-gap.

### 2.5 Принятые политики

- **Облачная политика: Balanced.** Локальная модель — основная; облако
  (OpenRouter, gpt-4o-mini) разрешено для planner-роли и LLM-judge в evals при
  `home_rag_llm_cloud_consent`. `agent_tool_call_mode=auto`: native tools для
  cloud-путей, JSON-decision для локальной модели (уточняется по probe Wave 0).
- **Stop controller живёт в harness, не в модели** (Урок 4): каждый стоп —
  FSM-переход с reason, записанный в trace/state.

---

## 3. Дорожная карта (волны; каждая — независимо shippable за флагом `agent_enabled`)

### Wave 0 — Фундамент и spike (без пользовательских изменений)

Принципы: Урок 1 «начинай просто»; Урок 2 «инструменты = контракты».

- `scripts/agent_toolcall_probe.py`: 15–20 промптов с `tools=` против локальной
  модели (`LLM_MODEL` на llama.cpp) и OpenRouter; метрики: валидность JSON-args,
  выбор инструмента, галлюцинации имён. Отчёт → выбор режима для
  `agent_tool_call_mode`.
- `provider_openai.py`: cache-bypass при `tools`/`tool_choice`/
  `response_format` (обе ветки); учёт токенов схем в оценке input-токенов.
  **Статус: сделано** (см. §2.4 — `_has_structured_or_tool_kwargs`,
  `_estimate_structured_kwargs_tokens`, тесты в
  `tests/test_provider_openai_structured.py`).
- `config.py` + `.env.example` + `config.env`: флаги + бюджеты уже заведены;
  Wave 0 остаётся закрепить это targeted-тестами и сохранять doc-sync для
  новых настроек.
- Тесты — конкретные файлы (директории `tests/agent/` ещё нет): расширить/создать
  `tests/test_provider_*.py` — `tools=`/`tool_choice=`/`response_format=`
  доходят до payload `chat.completions.create` (mock-клиент), кэш
  пропускается при structured/tool kwargs, токены схем учтены. `tests/agent/`
  заводится в Wave 1.

DoD: отчёт probe с рекомендацией; тесты зелёные; main-flow не тронут.
Non-goals: сам цикл, роутер, состояние.

### Wave 1 — Read-only single agent MVP (ReAct)

Принципы: Урок 1 (single agent, read-only first), Урок 2 (контракты),
Урок 3/4 (harness owns control, repair ≤ 1).

- Создать `app/agent/*` (contracts, tool_registry, tools_*, decision, runner,
  stop_controller); промпты в `_impl.py`.
- `decision.py`: **JSON-decision режим первым** (образец
  `invoke_pedagogical_orchestrator_llm`); native — заглушка за флагом.
- `stop_controller`: `max_steps=6`, `max_time`, `max_cost`, `tool_error_limit=2`,
  повтор идентичного вызова (hash tool+args), invalid args → 1 repair → stop,
  `guardrail_triggered`.
- Финальный ответ через `apply_output_guardrails` + конверт как в
  `app/query_service.py::_assemble_rag_result`; ветка в `query_service.answer_question`;
  траектория в `ctx.trace["agent"]`.
- Тесты `tests/agent/`: каждый тип стопа, валидность схем реестра, runner с
  фейковым LLM (happy-path / loop-stop / repair), интеграционный с mock-provider.

DoD: `query_mode="agent"` отвечает на 10 технических сценариев; флаг off → поведение
идентично main-flow. Non-goals: write-tools, персистентность, native, компакция.

### Wave 1A — Agent Study Session (первый продуктовый сценарий)

Зависит от Wave 1. Цель: не «универсальный агент», а короткая учебная сессия
по теме: объяснение → проверка → кандидаты на закрепление.

Статус MVP (2026-07-10): `query_mode="agent"` по умолчанию маршрутизируется в
сценарий `study_session`; сценарий использует read-only agent loop,
специализированный prompt и финальный контракт поверх tool trace. Persistence
появляется отдельно в Wave 2; Wave 1A не добавляет роутеры, UI или write-tools.

- Сценарий `study_session` — **реализовано** (`app/agent/scenarios.py`): вход —
  тема/вопрос + текущий курс; агент вызывает `learner.get_profile`,
  `rag.search`/`rag.answer`, при необходимости `progress.get_mastery`,
  `quiz.generate`, `cards.propose`.
- Выходной контракт MVP — **реализовано, заголовки секций совпадают с кодом**:
  `## Диагностика`, `## Что изучать сейчас`, `## План на 10–20 минут`,
  `## Проверочные вопросы`, `## Карточки-кандидаты`, `## Следующие шаги`, плюс
  `## Источники`, если использовался RAG.
- UI-поверхность — **реализовано**: `FeatureSpec("view:agent_session")` с
  `requires=("agent_enabled",)` в `feature_registry.py`, плитка «Агент» на
  Mission Control и view «Собрать учебную сессию» с текстовым вводом и
  `POST /ask` + `query_mode:"agent"`.
- Read API (A2) — **реализовано**: `app/routers/agent.py` с `GET /agent/runs` и
  `GET /agent/runs/{run_id}`, зарегистрирован как защищённый эндпоинт.
  Данные из `user_state_agent_runs` (санитайзинг на уровне хранения).
- Evals — **реализовано**: golden-набор расширен до 8 `study_session` кейсов
  (всего 10 кейсов), покрыт `tests/agent/test_agent_golden_cases.py`.
  Проверки: источники, quiz, карточки (draft), stop_reason.
- A1 Polish — **реализовано**: префилл текущей темы/курса из Mission Control в view агента.
- B2 (save cards) — **реализовано**: парсинг «## Карточки-кандидаты» + кнопки «Сохранить» с использованием add_flashcard + create_deck.
- C1 (student history) — **реализовано**: компактная секция «Что агент собирал для вас» в dashboards_progress.py (использует /agent/runs).

DoD: пользователь получает цельную read-only сессию за один запуск. Карточки-кандидаты сохраняются только по явному действию пользователя (B2). Non-goals: автосохранение карточек агентом, запись quiz-result, долгий multi-session plan.

### Wave 1B — Graph Gap Finder

Зависит от Wave 1A. Цель: сделать граф знаний навигационной картой, а не только
визуализацией.

Статус MVP (2026-07-10): сценарный роутер распознаёт graph/prerequisite/gap
запросы и выбирает `graph_gap_finder` до дефолтного `study_session`. Сценарий
read-only, без записи графа, user_state, quiz-result или карточек.

- Сценарий `graph_gap_finder`: агент читает `graph.inspect`,
  `progress.get_mastery`, `learner.get_profile`, при необходимости `rag.search`.
- Выходной контракт MVP: `## Карта пробелов`, `## Цепочка prerequisites`,
  `## Почему это мешает`, `## Рекомендуемый порядок`,
  `## Практическая проверка`, плюс `## Источники`, если использовался RAG.
- Граф не мутируется: новые связи и исправления узлов выводятся как
  `proposed_graph_edits` для будущего approve-flow, но не пишутся в bundle.
- Evals — **частично**: golden-набор на дату аудита содержит 1
  graph_gap_finder-кейс, а не целевые 4 (изолированный узел, слабый
  prerequisite, ложная связь, отсутствующий mastery); checks: нет write,
  порядок prerequisites разумный.

DoD: агент объясняет «что учить дальше и почему» по графу + прогрессу.
Non-goals: автоматическое редактирование графа, promotion graph bundle.

### Wave 1C — Living Konspekt Coach

Зависит от Wave 1B. Цель: превратить Живой конспект в активную учебную
поверхность: что добавить, что повторить, что проверить.

Статус MVP (2026-07-10): сценарный роутер распознаёт konspekt/workbench/конспект
запросы и выбирает `living_konspekt_coach` до graph/study сценариев. Сценарий
read-only, без записи workbench, конспекта, карточек, quiz-result или графа.

- Сценарий `living_konspekt_coach`: агент читает `konspekt.inspect`,
  `rag.search`, `quiz.generate`, `cards.propose`, `graph.inspect`.
- Выходной контракт MVP: `## Состояние конспекта`,
  `## Что добавить или уточнить`, `## Что повторить`,
  `## Проверка понимания`, `## Draft-карточки`, `## Следующий шаг`,
  плюс `## Источники`, если использовался RAG.
- Все изменения конспекта — только draft: добавление разделов, сохранение
  артефакта, заметки и карточки остаются ручными до Wave 5/HITL.
- Evals — **частично**: golden-набор на дату аудита содержит 1
  living_konspekt_coach-кейс, а не целевые 4 (пустой workbench, перегруженный
  workbench, workbench без цели, конспект с видео-citation); checks:
  использованы только выбранные rows, output ссылается на источники, нет
  скрытой записи в `workbench_service`.

DoD: агент даёт полезный план улучшения конспекта и scoped-проверку без
изменения состояния. Non-goals: auto-save конспекта, auto-add sections.

### Wave 2 — Персистентность run + наблюдаемость

Принципы: Урок 3 (state, run_id+step_id, append-only, recovery),
Урок 4 (observability: единица наблюдения = траектория).

- Статус slice (2026-07-10): `run_agent_flow` генерирует `run_id`, возвращает
  его в `debug.agent_trace` / `debug.answer_path` и best-effort сохраняет
  компактную историю в per-user SQLite через `app/user_state_agent_runs.py`.
- Таблицы `agent_runs` / `agent_steps` созданы в `_ensure_schema`.
  Сохраняются `scenario_id`, question preview, `answer_status`, `stop_reason`,
  state, tool calls и compact step summaries; raw `user_id`/`session_id` и
  длинные tool payloads не сохраняются.
- Следующий слой: checkpoint/recovery в `app/agent/state.py`, idempotency key
  для retry/resume, и публичная интроспекция.
- `run_id` дальше должен пойти не только в debug payload, но и:
  расширить `trace_tool_span` (`otel_tracing.py:138`) параметром `run_id`,
  добавить `run_id` в Langfuse-атрибуты и в logging-context filter.
  usage/cost на шаг (`stage=agent_step_{n}`).
- Метрики: `stops_by_reason`, `tool_error_rate`, `cost_per_run`, `steps_per_run`
  в metrics_storage; SLO-хук.
- Read-only роутер `app/routers/agent.py` — **реализовано** (A2): `GET /agent/runs`
  и `GET /agent/runs/{run_id}`. Persisted run хранит `scenario_id` (`generic`,
  `study_session`, `graph_gap_finder`, `living_konspekt_coach`) и summary
  output-контракта, чтобы сценарные evals можно было связывать с реальными
  прод-прогонами. Полная observability (run_id в traces, метрики) — в разработке.
- **Recovery-resume** (после сбоя процесса) — внутренний, в `state.py`: по
  последнему persisted шагу. Это НЕ HITL-approval resume (тот — Wave 5).
- Doc sync: `docs/api_reference.md`, `docs/architecture.md`.

DoD slice: run реконструируем из SQLite на уровне helper-API; `run_id`
проброшен в `/ask` debug; тесты покрывают compact trace, per-user isolation и
ветку `AGENT_ENABLED=false` без записи. Full DoD ещё включает recovery (kill
между шагами → внутренний resume) и публичный read-only router. Non-goals:
HITL-approval resume (`POST .../resume {approve|reject}`) и дашборд UI — Wave 5.

### Wave 3 — Контекстная дисциплина + native tools + роутинг моделей

Принципы: Урок 4 (KV-cache: статичный префикс, append-only, динамика в хвост).

- `context_builder.py`: детерминированная пересборка сообщений из state:
  [system + схемы] (статично, без timestamp) → [сжатая сводка старых шагов] →
  [последние N шагов дословно] → [вопрос]. Компакция при > SOFT_TOKEN_LIMIT (12k);
  полные ToolResult offload'ятся в `agent_steps.result_json`, в контекст —
  `ref_id` + summary.
- `decision.py`: native-режим; `auto` = native для cloud (за
  `home_rag_llm_cloud_consent`), json для локальной (по probe Wave 0).
- `get_agent_planner_llm()` / `get_agent_executor_llm()` в provider.py.
- Тесты: побайтовая стабильность префикса между шагами; run 10+ шагов не
  пробивает HARD_TOKEN_LIMIT ни в одном вызове.

DoD: оба режима работают; компакция покрыта тестом; префикс стабилен.
Non-goals: стриминг шагов.

### Wave 4 — Evals как культура + security-кейсы

Принципы: Урок 4 + Deep 3/4 (golden set, baseline, pass@k/pass^k,
траектория/исход/результат раздельно), Урок 4/5 (red-team, недоверенный контекст).

- `eval_data/agent_golden_v1.json`: 20–30 кейсов — обычные вопросы, отказы,
  провокация зацикливания, вызов несуществующего инструмента, injection в
  вопросе И в RAG-чанке/выводе инструмента, будущие HITL-кейсы.
- Детерминированные trajectory-чекеры кодом: нужный tool вызван, нет повторов,
  stop_reason корректен, шагов ≤ N, cost ≤ бюджета. Outcome — LLM-judge через
  `eval_service.run_eval` с bias-митигацией; baseline через `eval_baseline`.
- `scripts/agent_gate_v1.py` по образцу `home_rag_integration_gate_v1.py`;
  повторные прогоны pass@k / pass^k.
- Guardrails на ToolResult: `detect_prompt_injection`/`redact_sensitive_text`
  к содержимому инструментов перед вставкой в контекст.
- Процесс: каждый прод-фейл (agent_runs со stop_reason=error) → новый eval-кейс.

DoD: gate зелёный; baseline зафиксирован; injection-кейсы блокируются.
Non-goals: write-tools.

### Wave 5 — Write-инструменты + HITL

Принципы: Урок 1/5 (write позже, с подтверждением), Урок 2/3 (идемпотентность),
Урок 5 (generate→validate→execute, least privilege).

- `cards.save_deck`, `sr.update_card`, `quiz.record_result`: generate (модель) →
  validate (Pydantic strict + доменные проверки кодом) → execute (только после
  approve). Idempotency-key = hash(run_id, tool, args), UNIQUE в agent_steps —
  повторный execute = no-op.
- FSM-состояние `needs_human`: run замораживается, `pending_action` персистится;
  `POST /agent/runs/{run_id}/resume {approve|reject}`.
- Поверхности подтверждения: Streamlit-кнопка, Telegram inline-кнопки, CLI-prompt.

DoD: ни одной записи в user_state без approve; дубли невозможны; eval-gate
расширен HITL-кейсами (approve/reject/двойной resume/timeout).
Non-goals: автономные записи без подтверждения.

### Wave 6 — Plan-Execute + эпизодическая память (+ супервизор только при доказанном потолке)

Принципы: Урок 1 (ReAct для диалога, Plan-Execute для декомпозиции),
Урок 3 (память с confidence/TTL — анти-poisoning), Урок 5 (multi-agent только
при потолке).

- Режим plan-execute в runner.py: planner (сильная модель) строит план →
  executor выполняет → replan при ошибке; интеграция с learning_plan_service /
  adaptive_plan (генерация учебного плана, подготовка курса).
- Таблица `agent_memory(kind, content_json, confidence, source_run_id,
  ttl_expires_at)`; запись только верифицированных фактов; чтение — инструмент
  `memory.recall` (не автоподмешивание).
- **Условный** Supervisor: только если метрики Wave 4 показывают потолок одного
  агента (систематические стопы max_steps/max_tokens на классе задач).
  Субагенты = «умные инструменты» с компактным findings; merge-политика кодом;
  session-observability через родительский run_id.

DoD: учебный план собирается plan-execute и проходит eval; память не деградирует
golden set (A/B через eval_baseline).

---

## 4. Ключевые проектные решения

| Решение | Выбор | Почему |
|---|---|---|
| Native tools vs JSON-decision | Два бэкенда; **JSON первым**, native за `agent_tool_call_mode=auto` | Транспорт для native проходим, но качество tool-calling локальной модели не подтверждено; JSON-паттерн проверен боем в tutor_orchestrator |
| Где живёт цикл | Параллельный поток рядом с `_answer_question_main_flow` (`query_mode="agent"`) | Pipeline-контракт линеен; RAG становится инструментом; бесплатный реюз guardrails/budget/AskResponse |
| Где живёт состояние | SQLite через паттерн user_state (`user_state_agent_runs.py`) | Local-first / per-user isolation; конвенция репо; append-only compact trace |
| Лимит 20k токенов | Пересборка контекста из state + offload результатов (ref_id) + компакция при >12k | Накопительная история пробьёт hard-limit к 5–7 шагу |
| Роутинг моделей | Role-геттеры planner/executor в provider.py | Паттерн `_build_role_llm` уже есть; planner → сильная (cloud при consent), executor → дешёвая локальная |
| Дедуп-кэш | Bypass при `tools`/`tool_choice`/`response_format` в kwargs | Кэш-хит промежуточного шага = «зависший» агент |
| run_id | ContextVar + проброс в `trace_tool_span`/Langfuse-атрибуты/logging-filter | request_id — на HTTP-запрос, run_id — на весь прогон; одного ContextVar мало для span/трейсинга |

## 5. Риски и митигации

| Риск | Митигация |
|---|---|
| Локальная модель галлюцинирует имена/args инструментов | Wave 0 probe до кода; JSON-режим + нормализация + rule-fallback «ответь через rag.answer»; enum-args; repair ≤ 1 |
| Зацикливание / бюджетный разгон | stop_controller в коде: max_steps, hash повтора, no_progress, max_cost/max_time |
| Пробитие 20k лимита | компакция + offloading + учёт схем в guards; стоп max_tokens как страховка |
| Кэш возвращает промежуточный шаг как финал | cache-bypass в Wave 0, до первого запуска цикла |
| Injection через RAG-чанки/ToolResult | guardrails на выводы инструментов; red-team в golden set; user_id только от harness |
| Scope creep первых сценариев | Wave 1A/1B/1C независимы, read-only, каждый имеет свой output-контракт и eval; write переносится в Wave 5 |
| Двойная запись при retry/resume | idempotency-key UNIQUE; generate→validate→execute; HITL |
| Латентность мультишага на локальной модели | max_steps=6; executor на дешёвой модели; latency budget уже обвязан |
| Отравление памяти | confidence/TTL/source_run_id обязательны; memory.recall — инструмент; A/B через eval_baseline |
| Регрессия основного flow | параллельная ветка; флаг off по умолчанию; гейты scripts/home_rag_* в CI |

## 6. Верификация

1. **Wave 0:** `scripts/agent_toolcall_probe.py` против локального llama.cpp и
   OpenRouter; targeted provider/config tests: `tests/test_provider_openai_structured.py`
   (payload `tools`/`tool_choice`/`response_format`, cache-bypass,
   token-estimate для схем) + затронутые config-тесты. На момент Wave 0
   `tests/agent/` ещё не было — сейчас (после Wave 1–2) каталог существует
   (12 тестовых модулей, см. § ниже).
2. **Wave 1+:** `pytest tests/agent/`; smoke `/ask` с `query_mode="agent"` при
   `AGENT_ENABLED=true`; при `false` — ответ идентичен main-flow.
3. **Wave 1A–1C:** scenario golden sets:
   `agent_study_session`, `agent_graph_gap_finder`,
   `agent_living_konspekt_coach`; checks на read-only режим, источники,
   отсутствие скрытых writes и корректный output-contract. MVP-набор Wave 1A–1C
   лежит в `eval_data/agent_scenarios_golden_v1.json`.
4. **Wave 2:** текущий slice — `tests/agent/test_agent_persistence.py`
   покрывает compact SQLite trace, `run_id` в debug и per-user isolation.
   Следующий gate: kill между шагами → resume восстанавливает run;
   `GET /agent/runs/{run_id}` возвращает траекторию.
5. **Wave 4:** `scripts/agent_gate_v1.py` зелёный; pass^k ≥ порога;
   injection-кейсы дают `guardrail_triggered`.
6. **Всегда:** `scripts/home_rag_integration_gate_v1.py` /
   `home_rag_product_baseline_v1.py` не деградируют.

## 7. Traceability: лекции → волны

- Урок 1 (ReAct/Plan-Execute, harness, stop conditions, start simple) →
  Wave 1 (ReAct), Wave 1A–1C (малые продуктовые сценарии), Wave 6
  (Plan-Execute), stop_controller везде.
- Урок 2 (tools=контракты, read-only first, context engineering, structured
  output) → Wave 0/1/3.
- Урок 3 (память/стейт, FSM, idempotency, checkpointing, retrieve≠read) →
  Wave 2/5/6.
- Урок 4 (200 OK≠OK, stop controller, KV-cache, evals, guardrails,
  observability) → Wave 2/3/4.
- Урок 5 (write-tools с HITL, generate→validate→execute, least privilege,
  мультиагентность только при потолке, Supervisor, merge) → Wave 5/6.
- Deep 3/4 (датасеты, eval-методология, baseline, конфигурации) → Wave 4.
- Deep 5/6 (vector DB, GraphRAG) → уже покрыто существующим retrieval
  (hybrid+rerank+graph) — переиспользуется как инструменты; Wave 1B делает
  graph-навигацию первым отдельным сценарным продуктом.
- Deep 8 (context engineering, offloading, subagents) → Wave 3/6.

---

## 8. Правки после код-аудита (2026-07-10)

Проверено по коду и учтено в разделах выше (найденные проблемы переведены в статус решённых или спроектированных):

Решённые блокеры:
- **Feature flag** (§2.2): низкоуровневая ветка `agent_enabled` внутри
  `requirement_context_ok` (`feature_registry.py:128`) **решена кодом** и покрыта
  тестами (`tests/test_feature_registry.py`). `FeatureSpec("view:agent_session")`
  объявлен с `requires=("agent_enabled",)` — Wave 1A UI-фича подключена к флагу.
- **Оценка токенов** (§2.4): input-токены схем инструментов оцениваются в
  provider-layer через `_estimate_structured_kwargs_tokens()`
  (`provider_openai.py:91-109`, вызов на `:276-277`), а не в
  `check_input_tokens` (тот берёт уже готовое число). **Решено кодом и тестами**
  (`tests/test_provider_openai_structured.py`).
- **Cache-bypass** (§2.4): `_hash_request` (`request_cache.py:109`) игнорирует
  `tools`/`tool_choice`/`response_format` → bypass реализован в обеих ветках
  через `_has_structured_or_tool_kwargs()` (`provider_openai.py:74-88`; `_chat`
  `:433/446/500`, `_achat` `:511/523-524/570`). **Решено кодом и тестами**
  (`tests/test_provider_openai_structured.py`).
- **`rag.search`** (§2.3): не через `execute_rag_query` (запускает генерацию), а
  через retrieval-only adapter (`app/agent/tools_rag.py:73-99`). Решено кодом.
- **`rag.answer`** (§2.1/§2.3): принудительно non-agent путь — иначе рекурсия
  agent → tool → agent (`app/agent/tools_rag.py:102-125`, `query_mode=None`).
  Решено кодом.

Учтённые в проекте блокеры (спроектировано, ещё не реализовано):
- **Роль-геттеры provider'а** (§2.4 п.3): `get_agent_planner_llm()` /
  `get_agent_executor_llm()` в `app/provider.py` — Wave 3, в коде пока нет.
- **`context_builder.py` / `state.py` / `tracing.py`** (§2.2): три модуля пакета
  `app/agent/` пока не созданы — компакция контекста (Wave 3), checkpoint/recovery
  и idempotency (Wave 2/5), проброс `run_id` в `trace_tool_span` (Wave 2).
- **Wave 1A UI CTA** («Собрать учебную сессию» в Mission Control/Tutor chat) —
  в коде не найден; текст в §3 Wave 1A описывает целевое, а не текущее состояние.


Серьёзные:
- **Agent trace** (§2.1/Wave 2): `get_pipeline_trace` читает
  `debug.pipeline_trace`; агентная траектория идёт в compact
  `agent_runs`/`agent_steps` (+ `debug.agent_trace.run_id`), не «бесплатно».
- **Resume** (§2.2/Wave 2/Wave 5): разведены recovery-resume (после сбоя, Wave 2)
  и HITL-approval resume (Wave 5).
- **Doc-sync настроек** (§2.2/Wave 0): `.env.example` + `config.env` вместе с
  `config.py`.
- **run_id observability** (Wave 2): `debug.agent_trace.run_id` уже есть;
  проброс в `trace_tool_span`/Langfuse/logging остаётся следующим шагом.
- **Cloud consent** (§2.4): дизайн-решение — enforced кодом внутри будущих
  agent role getters, не по одному лишь model id; сами getters ещё не
  реализованы (см. Wave 3 выше), поэтому проверку consent пока негде вызывать.

Мелкие:
- Локальная модель именуется как `LLM_MODEL`, не хардкод конкретного id.
- `progress.get_mastery`: read-API уже существует (`quiz_adaptive.py`,
  `learner_state_scope.py`, `analytics_service.py`); фактически tool в
  `tools_learner.py` использует только три функции `quiz_adaptive.py`, а
  `learner_state_scope.get_quiz_mastery_rows_for_kg` и
  `analytics_service.get_advanced_analytics` пока не подключены — нужен тонкий
  агрегирующий helper, без ad hoc SQL в tool-коде.
- Wave 0 тесты ссылаются на конкретные `tests/test_provider_*.py`;
  `tests/agent/` заводится в Wave 1 (и уже существует — 12 тестовых модулей на
  дату аудита, включая `test_agent_persistence.py`, `test_runner.py`,
  `test_study_session_scenario.py` и т.д.).
- Agent settings (`AGENT_*`) уже заведены в `config.py`, `.env.example` и
  `config.env`; Wave 0 больше не должен описывать это как невыполненную работу.
- `app/agent/__init__.py` описан выше как «фасад: `run_agent_flow(...)`» — этот
  файл реализует и модуль-инвентарь §2.2 корректен по месту, но сам roadmap
  ранее (до этого аудита) ошибочно указывал `run_agent_flow` в `runner.py` —
  исправлено в §2.1/§2.2.
- `AgentState` (`app/agent/contracts.py`) содержит только
  `running/tool_call/repairing/stopped/completed` — состояний `guarded` и
  `needs_human` из более раннего текста §2.2 в коде нет; guardrail-стоп
  выражается как `stopped` + `StopReason.GUARDRAIL_TRIGGERED`, `needs_human`
  запланирован на Wave 5 (см. `state.py` выше).
- `app/agent/scenarios.py` (роутер Wave 1A–1C + сценарные промпты/output-контракты)
  ранее отсутствовал в инвентаре §2.2 — добавлен.
- Eval-покрытие Wave 1A–1C (§3, §6): текст описывает целевое число кейсов
  (8–10 study_session + по 4 для graph_gap/konspekt); фактический
  `eval_data/agent_scenarios_golden_v1.json` на дату аудита содержит 4 кейса
  (2 study_session, 1 graph_gap_finder, 1 living_konspekt_coach) — целевые числа
  в §3 нужно читать как backlog, не как факт.
