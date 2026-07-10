# AI-агент в hometutor: архитектура и волновая дорожная карта

Актуализировано: 2026-07-10.
Статус: одобренный план внедрения (Wave 0 — в работе). Это **канонический**
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

Пробелы (Gap 1–7): нет tool-loop и stop controller; structured output только
`json_object` (без строгой схемы); общий streaming-путь пока не имеет полноценного
учёта стоимости, поэтому provider сейчас вызывает chat с `stream=False`;
`HARD_TOKEN_LIMIT=20_000` (`app/llm_guards.py`)
ограничивает накапливающийся контекст; нет `run_id` для мультишаговых прогонов;
дедуп-кэш ответов может закэшировать промежуточный шаг цикла; качество
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
(`app/query_service.py`), после `_prepare_query_context` (guardrails/classify
уже отработали):

```python
if options.query_mode == "agent" and settings.agent_enabled:
    return run_agent_flow(question, options, ctx, ...)   # app/agent/runner.py
return _answer_question_main_flow(...)
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
траектория туда сама не попадёт. Нужно либо писать `debug.agent_trace` в ту же
history-запись, либо (Wave 2) отдельный `GET /agent/runs/{run_id}` из таблиц
`agent_runs`/`agent_steps`. Старый pipeline-trace не ломается.

### 2.2 Пакет `app/agent/`

```
app/agent/
  __init__.py          # фасад: run_agent_flow(...)
  contracts.py         # ToolSpec (name, when_to_use, args: Pydantic strict, limits,
                       #   access: read|write, idempotent) + ToolResult {ok, data, error, meta}
  tool_registry.py     # реестр rag.* / learner.* / quiz.* / cards.*; to_openai_tools()
  tools_rag.py         # адаптеры над execute_rag_query / query_service
  tools_learner.py     # learner_model_service, analytics_service
  tools_quiz.py        # quiz_service
  tools_flashcards.py  # flashcard_service, user_state_flashcards (write — Wave 5)
  decision.py          # два бэкенда: JSON-decision + native tools; repair <= 1
  runner.py            # AgentRunner: FSM running/tool_call/repairing/guarded/
                       #   stopped/completed/needs_human; переход = запись + reason
  stop_controller.py   # resource/tool/quality/control-стопы -> StopDecision(reason)
  context_builder.py   # KV-cache дисциплина: статичный префикс, компакция, offloading
  state.py             # обёртка над user_state_agent_runs (run_id, step_id,
                       #   checkpoint/recovery, idempotency keys)
  tracing.py           # span на шаг через otel_tracing.trace_tool_span; run_id; usage/cost
```

Вне пакета (по конвенциям репо):

- `app/user_state_agent_runs.py` — таблицы `agent_runs`, `agent_steps`
  (+ позже `agent_memory`) в `_ensure_schema` (`app/user_state_db.py`);
  state только через `user_state*.py`.
- Промпты агента (`AGENT_SYSTEM_PROMPT`, `AGENT_DECISION_PROMPT`) —
  в `app/prompts/_impl.py` рядом с `ORCHESTRATOR_SYSTEM_PROMPT`,
  с записью в `PROMPTS`/`PROMPT_VERSIONS`.
- Флаги — только через `get_settings()` (`app/config.py`): `agent_enabled=False`,
  `agent_tool_call_mode: json|native|auto` (`auto` = native для cloud-путей при
  consent, JSON-decision для локальной модели), `agent_max_steps=6`,
  `agent_max_run_tokens`, `agent_max_run_cost_usd`, `agent_max_run_seconds`.
  Эти флаги уже заведены в `app/config.py`, `.env.example` и `config.env`;
  дальнейшие настройки добавлять во все три места одновременно.
- Роутер `app/routers/agent.py`: `GET /agent/runs/{run_id}`, `GET /agent/runs`
  (интроспекция, Wave 2) и `POST /agent/runs/{run_id}/resume` (**HITL-approval,
  Wave 5** — не путать с recovery-resume внутри `state.py`); регистрация в
  `app/api.py` с `_protected_dependencies`.
- UI-фича: `FeatureSpec` в `app/ui/feature_registry.py` с
  `requires=("agent_enabled",)`. Ветка `agent_enabled` в
  `requirement_context_ok` уже добавлена; неизвестные требования по-прежнему
  возвращают `False`.

### 2.3 Стартовый набор инструментов (5–7, read-only в Wave 1)

| Инструмент | Обёртка над | access |
|---|---|---|
| `rag.search` | **retrieval-only adapter**: `retriever.retrieve(QueryBundle)` напрямую (как в extractive-ветке `query_rag_execution.py:165`), НЕ `execute_rag_query` (тот запускает генерацию) | read |
| `rag.answer` | non-agent main-flow (`_answer_question_main_flow` с `query_mode≠agent`) как «умный инструмент» | read |
| `learner.get_profile` | `learner_model_service` + `app/tutor_orchestrator.py::build_tutor_session_state` | read |
| `cards.get_due` | `user_state_flashcards.get_due_flashcards` | read |
| `progress.get_mastery` | тонкий read-helper в `user_state_quiz` над quiz state (`quiz_results` и/или schema `quiz_mastery` из `user_state_db`) + `analytics_service.get_advanced_analytics` | read |
| `quiz.generate` | `quiz_service.generate_topic_quiz` (без записи) | read |
| Wave 5: `cards.save_deck`, `sr.update_card`, `quiz.record_result` | flashcard_service / `update_flashcard_sr` | write + idempotency-key + HITL |

Примечания к адаптерам (из аудита):
- `rag.search` — чистый retrieval; `execute_rag_query` не подходит, т.к. его
  extractive early-exit условный (`_two_stage_eligible` + пороги score/nodes),
  иначе идёт LLM-синтез.
- `rag.answer` — принудительно non-agent путь (иначе рекурсия).
- `progress.get_mastery` — явного read-API «get mastery» нет; нужен тонкий
  helper в `app/user_state_quiz.py`, не ad hoc SQL в tool-коде.

Правила контрактов (Урок 2/3): args — Pydantic strict, enum вместо свободных
строк; `ToolResult{ok,data,error}`; лимиты на размер результата;
`user_id`/`session_id` инжектятся harness'ом из auth-контекста — модель их
**не выбирает** (least privilege, Урок 5).

### 2.4 Правки provider-слоя (точечные)

1. `provider_openai.py`: **bypass дедуп-кэша** при наличии `tools`/`tool_choice`/
   `response_format` в kwargs — **в обеих ветках** (sync `_chat` ~`:400`,
   async `_achat` ~`:475`). Причина: `request_cache._hash_request`
   (`request_cache.py:109`) хэширует только `model/messages/temperature/
   max_tokens/top_p` и полностью игнорирует `tools`/`tool_choice`/
   `response_format`, поэтому два разных structured/tool-шага с одинаковыми
   messages дали бы cache-hit → «зависший» агент.
2. Учёт токенов схем инструментов при оценке `input_tokens` **в provider-layer**
   (`provider_openai.py` ~`:233`, там где считаются токены перед
   `llm_guards.check_input_tokens`) — сам `check_input_tokens` принимает уже
   готовое число, поэтому править надо оценку, а не guard.
3. Роль-геттеры в `app/provider.py` по образцу `_build_role_llm`:
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

DoD: `query_mode="agent"` отвечает на 10 сценариев; флаг off → поведение
идентично main-flow. Non-goals: write-tools, персистентность, native, компакция.

### Wave 2 — Персистентность run + наблюдаемость

Принципы: Урок 3 (state, run_id+step_id, append-only, recovery),
Урок 4 (observability: единица наблюдения = траектория).

- Таблицы `agent_runs` / `agent_steps` (append-only, idempotency_key UNIQUE) в
  `_ensure_schema`; модуль `app/user_state_agent_runs.py`; checkpoint/recovery
  в `app/agent/state.py`.
- `run_id` — не только ContextVar рядом с `request_id`
  (`logging_config.py:14` сейчас несёт только request_id), но и:
  расширить `trace_tool_span` (`otel_tracing.py:138`) параметром `run_id`,
  добавить `run_id` в Langfuse-атрибуты и в logging-context filter.
  usage/cost на шаг (`stage=agent_step_{n}`).
- Метрики: `stops_by_reason`, `tool_error_rate`, `cost_per_run`, `steps_per_run`
  в metrics_storage; SLO-хук.
- `app/routers/agent.py`: `GET /agent/runs/{run_id}` (реконструкция траектории
  из `agent_runs`/`agent_steps` — это и есть источник агентного trace, отдельно
  от старого `debug.pipeline_trace`).
- **Recovery-resume** (после сбоя процесса) — внутренний, в `state.py`: по
  последнему persisted шагу. Это НЕ HITL-approval resume (тот — Wave 5).
- Doc sync: `docs/api_reference.md`, `docs/architecture.md`.

DoD: run полностью реконструируем из SQLite; тест recovery (kill между шагами →
внутренний resume восстанавливает run). Non-goals: HITL-approval resume
(`POST .../resume {approve|reject}`) и дашборд UI — Wave 5.

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
| Где живёт состояние | SQLite через паттерн user_state (`user_state_agent_runs.py`) | Local-first single-user; конвенция репо; append-only + idempotency |
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
| Двойная запись при retry/resume | idempotency-key UNIQUE; generate→validate→execute; HITL |
| Латентность мультишага на локальной модели | max_steps=6; executor на дешёвой модели; latency budget уже обвязан |
| Отравление памяти | confidence/TTL/source_run_id обязательны; memory.recall — инструмент; A/B через eval_baseline |
| Регрессия основного flow | параллельная ветка; флаг off по умолчанию; гейты scripts/home_rag_* в CI |

## 6. Верификация

1. **Wave 0:** `scripts/agent_toolcall_probe.py` против локального llama.cpp и
   OpenRouter; targeted provider/config tests: `tests/test_provider_*.py`
   (payload `tools`/`tool_choice`/`response_format`, cache-bypass,
   token-estimate для схем) + затронутые config-тесты. `tests/agent/` ещё нет.
2. **Wave 1+:** `pytest tests/agent/`; smoke `/ask` с `query_mode="agent"` при
   `AGENT_ENABLED=true`; при `false` — ответ идентичен main-flow.
3. **Wave 2:** kill между шагами → resume восстанавливает run;
   `GET /agent/runs/{run_id}` возвращает полную траекторию.
4. **Wave 4:** `scripts/agent_gate_v1.py` зелёный; pass^k ≥ порога;
   injection-кейсы дают `guardrail_triggered`.
5. **Всегда:** `scripts/home_rag_integration_gate_v1.py` /
   `home_rag_product_baseline_v1.py` не деградируют.

## 7. Traceability: лекции → волны

- Урок 1 (ReAct/Plan-Execute, harness, stop conditions, start simple) →
  Wave 1 (ReAct), Wave 6 (Plan-Execute), stop_controller везде.
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
  (hybrid+rerank+graph) — переиспользуется как инструменты.
- Deep 8 (context engineering, offloading, subagents) → Wave 3/6.

---

## 8. Правки после код-аудита (2026-07-10)

Проверено по коду и учтено в разделах выше:

Блокеры:
- **Feature flag** (§2.2): `requires=("agent_enabled",)` требовал ветку в
  `requirement_context_ok` (`feature_registry.py:128`); ветка добавлена, чтобы
  будущая UI-фича не скрывалась навсегда.
- **Оценка токенов** (§2.4): править оценку input-токенов в provider-layer
  (`provider_openai.py:233`), а не `check_input_tokens` (тот берёт готовое число).
- **Cache-bypass** (§2.4): `_hash_request` (`request_cache.py:109`) игнорирует
  `tools`/`tool_choice`/`response_format` → bypass нужен в обеих ветках
  (`_chat`/`_achat`).
- **`rag.search`** (§2.3): не через `execute_rag_query` (запускает генерацию), а
  через retrieval-only adapter.
- **`rag.answer`** (§2.1/§2.3): принудительно non-agent путь — иначе рекурсия
  agent → tool → agent.

Серьёзные:
- **Agent trace** (§2.1/Wave 2): `get_pipeline_trace` читает
  `debug.pipeline_trace`; агентная траектория идёт в `agent_runs`/`agent_steps`
  (+ опц. `debug.agent_trace`), не «бесплатно».
- **Resume** (§2.2/Wave 2/Wave 5): разведены recovery-resume (после сбоя, Wave 2)
  и HITL-approval resume (Wave 5).
- **Doc-sync настроек** (§2.2/Wave 0): `.env.example` + `config.env` вместе с
  `config.py`.
- **run_id observability** (Wave 2): проброс в `trace_tool_span`/Langfuse/logging,
  не только ContextVar.
- **Cloud consent** (§2.4): enforced кодом в agent role getters, не по model id.

Мелкие:
- Локальная модель именуется как `LLM_MODEL`, не хардкод конкретного id.
- `progress.get_mastery`: нужен тонкий read-helper над quiz state в
  `user_state_quiz`, без ad hoc SQL в tool-коде.
- Wave 0 тесты ссылаются на конкретные `tests/test_provider_*.py`;
  `tests/agent/` заводится в Wave 1.
- Agent settings (`AGENT_*`) уже заведены в `config.py`, `.env.example` и
  `config.env`; Wave 0 больше не должен описывать это как невыполненную работу.
