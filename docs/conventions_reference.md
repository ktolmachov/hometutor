# Соглашения: промпты, API, ошибки, тесты, документация

Роль: справочный слой к [conventions.md](conventions.md).

## Промпты

- Все промпты хранятся в пакете `app/prompts/` — единый источник правды. Словарь `PROMPTS` маппит тип запроса на промпт.
- Именование: `QA_PROMPT`, `SYNTHESIS_PROMPT`, `LEARNING_PLAN_PROMPT`, `OVERVIEW_PROMPT`, `KEYWORD_PROMPT`.
- Промпты не хардкодятся в endpoint-модулях или UI. Pipeline runner через `QueryContext.prompt_key` определяет промпт.
- `pipeline_factory.py` реэкспортирует `QA_PROMPT` и `KEYWORD_PROMPT` из пакета `app/prompts/` для обратной совместимости.

## Именование API endpoints

Полный перечень путей и методов — в [`doc/api_reference.md`](api_reference.md) и в OpenAPI (`GET /docs`). Здесь дублировать таблицу не нужно: она быстро расходится с `app/routers/*`.

Роутеры (модули под `app/routers/`): `core`, `query`, `sessions`, `knowledge`, `quiz`, `review`, `flashcards`, `dashboard`, `sync`, `files`, `metrics`, `admin` — подключение в `app/api.py`.

Соглашения для новых endpoints (актуально с итерации 13):

- Структура: `/<ресурс>/<действие>` — noun-first, действие опционально.
- GET для чтения, POST для операций с side-effects.
- Группировка по домену: `knowledge/` (topics, synthesize), `admin/` (reindex, cache), `debug/` (profile).
- Точка сборки приложения — `app/api.py`; HTTP-маршруты сгруппированы в `app/routers/` (`core`, `query`, `admin`, `knowledge`, `metrics`, `files`, `sessions`, `quiz`, `review`, `flashcards`, `sync`, `dashboard`). Новые маршруты добавлять в соответствующий роутер и подключать через `include_router`.
- Часть сценариев (eval, faq, debug) может жить внутри перечисленных модулей; отдельные `faq`/`eval` роутеры — по мере необходимости (см. `doc/tasklist.md`, итерация 15).

## Работа с зависимостями

- Зависимости фиксируются в `requirements.txt`.
- Новые библиотеки добавляются только при явной необходимости.
- Предпочтительно использовать уже выбранный стек: FastAPI, Streamlit, llama-index, Chroma, pydantic-settings, pytest.

## Обработка ошибок

- Ошибки должны логироваться с достаточным контекстом для отладки.
- `except Exception` допускается только с `# noqa: BLE001` и коротким rationale. Inline diagnostic `import logging; logging.getLogger(...)` внутри такого блока допустим, если import стоит непосредственно после annotated broad-except и нужен для local fallback logging без module-level logger.
- Пользовательские ошибки в API должны возвращать понятные сообщения.
- Для pipeline-ошибок сохраняем принцип graceful degradation: classify → fallback в `qa`, rewrite → passthrough, rerank → skip; generate — единственная стадия без fallback.
- File-related endpoints должны различать:
  - файл не найден,
  - путь небезопасен,
  - формат файла не поддерживается для text preview.
- Guardrails-ошибки (prompt injection, слишком длинный запрос) возвращаются с HTTP 400 и понятным описанием.

## Взаимодействие с агентами (Cursor)

Краткий процесс итераций и коммитов — [`.cursor/rules/workflow.mdc`](../.cursor/rules/workflow.mdc). Ниже — то же в развёрнутом виде для людей и для синхронизации с правилами редактора.

- Задача формулируется через **`doc/tasklist.md`** (текущая итерация, scope). «Готово» = выполнены **exit criteria** из `tasklist` для этого среза, без параллельного набора критериев в чате.
- Перед кодом — **план и явное «ок»** пользователя (как в workflow); после — тесты по критериям итерации.
- В промпт агенту: **цель** и при необходимости указатель на этот файл или модуль (`app/...`); не передавать репозиторий целиком — поиск по коду в задаче агента.
- После изменений, затрагивающих **graph**- или **learner**-контуры и CI — `pytest` плюс релевантные smoke/gate (см. `tasklist`, workflows под `.github/workflows/`).
- Для типовых agent-задач использовать готовые verification bundles из [agent_workflow_test_bundles.md](agent_workflow_test_bundles.md) вместо ручного подбора команд в каждом новом потоке.
- Если контекст диалога переполнен или тема сменилась — **новый чат** с коротким резюме и ссылками на разделы `doc/` и пути файлов.
- Повторяющиеся договорённости фиксировать **парой**: правка [`.cursor/rules/`](../.cursor/rules/) и [conventions.md](conventions.md) / вынесенные файлы — чтобы подсказки IDE не расходились с репозиторием.
- Перед merge полезно **просмотреть свой diff** (особенно `config`, pipeline, retrieval, tutor). Отдельный чужой ревью — опционально.
- **Линтер и строгий typecheck** как обязательный барьер в проекте на сегодня **не зафиксированы**; введение — отдельное решение и объём работы, не подразумевается каждый день.

## Тестирование

- Новые фиксы и новые архитектурные точки должны сопровождаться тестами.
- Минимум: smoke/unit тест на критический сценарий и тест на регрессию для найденного бага.
- Тесты держим в `tests/`, по возможности рядом по смыслу с модулем.
- Изоляция env-настроек: фикстура `settings_env` в `tests/conftest.py` — вызывается как `settings_env({"LLM_MODEL": "gpt-4o-mini", ...})` (имена переменных в стиле pydantic-settings, обычно `UPPER_SNAKE_CASE`), внутри выставляет `monkeypatch.setenv`, `reset_settings_cache()`, возвращает актуальный `get_settings()`; после теста кэш сбрасывается. Для точечных сценариев по-прежнему допустимы `monkeypatch.setattr(..., get_settings, ...)` и `reset_settings_cache()` вручную.
- **Reranker в pytest:** `pytest_configure` в `tests/conftest.py` подменяет `app.config.get_retrieval_settings` так, что `enable_reranker` всегда `False`. Это отключает загрузку Torch/FlagEmbedding в тестовом процессе и снижает риск native-крашей на Windows. Следствие: **юнит-тесты не проверяют поведение reranker**; регрессии по rerank-пути нужно ловить отдельно (интеграционные/e2e-прогоны с явно включённым reranker в контролируемом окружении).
- **FAQ cache в тестах:** `patch_retrieval_faq_cache_enabled(monkeypatch)` — патчит только `app.retrieval.get_settings` (достаточно для `resolve_query_execution_plan` и политики `_faq_cache_policy` без поднятия `query_service`). `patch_faq_cache_enabled(monkeypatch)` — патчит `get_settings` и в `app.query_service`, и в `app.retrieval` (нужно, когда сценарий проходит через `answer_question` и оба модуля должны видеть `enable_faq_cache=True`).

## Документация

- При изменении архитектуры или пользовательского поведения нужно обновлять `doc/`.
- После выполнения значимых итераций нужно обновлять `doc/tasklist.md`.
- Если в `doc/tasklist.md` для возможности указан статус вроде **закрыто в runtime** / **Implemented** / **закрыто по контракту**, в той же итерации должна быть **проверяемая связка**: запись в `doc/changelog.md` (дата, суть), либо ссылка на коммит/PR в сообщении закрытия, либо явное имя регрессионного теста / eval-артефакта. Иначе статус легко превращается в декларацию без трассировки. Default LLM в текстах `doc/` для «текущего runtime» должен совпадать с `get_settings()` в `app/config.py`, а не с устаревшими фразами в исторических блоках (см. «Критический разбор» в `tasklist.md`).
- `doc/vision.md` и `doc/conventions.md` должны синхронизироваться с roadmap минимум по завершении каждой крупной итерации 11+.
- Ключевые документы: `vision.md` (продукт и границы), `architecture.md` (архитектура), `conventions.md` (соглашения), `user_guide.md` (быстрый старт), `user_guide_details.md` (детали использования), `user_scenarios.md` (пользовательские сценарии и джорнисы), `product_idea.md` (идея и roadmap), `tasklist.md` (план итераций), `adr.md` (архитектурные решения и обоснования).
- Персонализированная модель ученика (поля, KV): `personalized_learner_model.md`.
- Аналитические обзоры (например `tutor_architecture_analysis.md`) ведут с **версией и датой**; таблицы «статус в проекте» нужно пересматривать при изменении tutor/RAG-пути (`query_service`, `retrieval`, `quiz_*`, `spaced_repetition`), иначе документ устаревает быстрее `tasklist.md`.
- При существенных правках соглашений или дерева модулей обновлять [`.cursor/rules/conventions.mdc`](../.cursor/rules/conventions.mdc); процесс итераций — [`.cursor/rules/workflow.mdc`](../.cursor/rules/workflow.mdc). См. [`.cursor/README.md`](../.cursor/README.md).
