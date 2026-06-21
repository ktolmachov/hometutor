# Правила и соглашения по разработке

Статус: `Live`  
Роль: актуальные соглашения по коду и сопровождению проекта. При конфликте с историческими design/roadmap документами ориентироваться на этот файл и на код.

> **Контекст для агентов:** не подтягивать этот файл и вложенные справочники целиком в промпт. Always-on выжимка: [`.cursor/rules/conventions.mdc`](../.cursor/rules/conventions.mdc). Детали — только по задаче: модули в `app/…` и нужный фрагмент из таблицы ниже.

## TL;DR

- **KISS:** малые модули, явные зависимости, без лишних слоёв.
- **Конфиг:** только `get_settings()` / `get_retrieval_settings()` из `app/config.py`.
- **LLM / embed:** только `app/provider.py`.
- **HTTP:** `app/routers/*` (+ `api_requests.py` / `api_models.py`); точка входа `app/api.py`.
- **Knowledge / guardrails:** `knowledge_service.py`, `guardrails.py`.
- **Пайплайн запроса:** `pipeline_runner.py`, `pipeline_steps.py`, контракт шага `process(QueryContext) -> QueryContext`.
- **DB / persistence:** user-state таблицы — через `app/user_state.py` и `_with_db()`; отдельные локальные SQLite-хранилища — только через документированные store wrappers / artifacts (см. `conventions_architecture.md`).
- **Промпты:** единственный источник `app/prompts/`.
- **Тесты:** `tests/`; env — фикстура `settings_env` в `conftest.py`.
- **Итерации:** scope и критерии — `doc/backlog_registry.yaml`; `doc/tasklist.md` — производный weekly view; процесс — `.cursor/rules/workflow.mdc`.

## Навигация (якоря и вынесенные файлы)

| Тема | Где читать |
|------|------------|
| Основные принципы, стиль | [§ Основные принципы](#основные-принципы), [§ Стиль кода](#стиль-кода) |
| Конфиг, retrieval, graph, tutor, дерево `app/` | [conventions_architecture.md](conventions_architecture.md) |
| Промпты, REST-соглашения, ошибки, агенты, тесты, doc-sync | [conventions_reference.md](conventions_reference.md) |

## Основные принципы

- KISS: решения должны оставаться простыми.
- Модульность: логика делится по небольшим, понятным модулям.
- Явные зависимости: общая логика должна быть вынесена в отдельный модуль, а не копироваться.
- Минимум лишних абстракций: новые слои добавляются только если они реально уменьшают дублирование или риск ошибок.

## Стиль кода

- Следовать PEP 8.
- Использовать говорящие имена функций и переменных.
- Добавлять короткие комментарии только там, где логика неочевидна.
- Предпочитать небольшие функции с одной понятной ответственностью.

## Детали

Вся прежняя глубина (архитектурные буллеты, дерево проекта, промпты, API, ошибки, тесты, документация) перенесена без смысловых сокращений в:

- [conventions_architecture.md](conventions_architecture.md)
- [conventions_reference.md](conventions_reference.md)

При изменении этих файлов имеет смысл синхронизировать [`.cursor/rules/conventions.mdc`](../.cursor/rules/conventions.mdc), чтобы подсказки агента не расходились с репозиторием.
