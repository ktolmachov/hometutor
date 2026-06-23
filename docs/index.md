# Навигатор документации hometutor

Актуализировано: 2026-06-23.

`hometutor` — runtime-репозиторий локального учебного RAG-приложения. Здесь живут приложение, API, UI, запуск, deployment и эксплуатационная документация. Процессные материалы, backlog, user stories, demo screenshots и длинные сценарные артефакты вынесены в `hometutor-studio`.

## Быстрый старт по ролям

| Роль | Читать сначала |
|---|---|
| Пользователь | [user_guide.md](user_guide.md) -> [quickstart.md](quickstart.md) |
| Demo/pitch | [quickstart_demo.md](quickstart_demo.md) -> [user_guide.md](user_guide.md) |
| Backend/API | [api_reference.md](api_reference.md) -> [technical_specification.md](technical_specification.md) |
| Архитектор | [architecture.md](architecture.md) -> [conventions_architecture.md](conventions_architecture.md) |
| Разработчик | [conventions.md](conventions.md) -> [conventions_reference.md](conventions_reference.md) |
| DevOps | [quickstart.md](quickstart.md) -> [../DOCKER_BUILD.md](../DOCKER_BUILD.md) -> [../deploy/hf-spaces/README.md](../deploy/hf-spaces/README.md) |

## Документы

| Документ | Назначение |
|---|---|
| [user_guide.md](user_guide.md) | главная карта продукта и пользовательских режимов |
| [quickstart.md](quickstart.md) | локальный запуск, индекс, первый учебный цикл |
| [quickstart_demo.md](quickstart_demo.md) | ручной demo lane без отсутствующих screenshot-артефактов |
| [api_reference.md](api_reference.md) | актуальная карта HTTP endpoints |
| [architecture.md](architecture.md) | runtime-архитектура и границы хранилищ |
| [technical_specification.md](technical_specification.md) | техническая спецификация runtime-системы |
| [conventions.md](conventions.md) | короткие инженерные правила |
| [conventions_architecture.md](conventions_architecture.md) | архитектурные соглашения по слоям |
| [conventions_reference.md](conventions_reference.md) | справочник по API, ошибкам, тестам и документации |

## Источники истины

| Вопрос | Источник |
|---|---|
| OpenAPI и реальные маршруты | `app/api.py`, `app/routers/*`, `/docs` |
| конфигурация | `app/config.py`, `config.env`, `.env` |
| LLM/embeddings | `app/provider.py` |
| Streamlit UI | `app/ui/main.py`, `app/ui/*` |
| user state | `app/user_state*.py`, `data/user_state.db` |
| flashcards | `app/flashcard_service.py`, `app/routers/flashcards.py` |
| Smart Study Router | `app/smart_study_*.py`, `app/ssr_*.py` |

## Что было исправлено при актуализации

- Убраны ссылки на отсутствующие `docs/screenshots/*`, `docs/scenarios/*`, `user_scenarios.md`, `user_guide_details.md`, `prompts_catalog.md`, `personalized_learner_model.md`.
- Уточнено, что `config.env` является tracked defaults, а `.env` — локальным override.
- Убраны упоминания несуществующих entrypoints вроде `ask.py` и `run_eval.py`.
- `doc/`-ссылки заменены на `docs/` или помечены как материалы `hometutor-studio`.
- API reference синхронизирован с `app/api.py` и `app/routers/*` на дату актуализации.

## Политика документации

- Runtime-документы не должны ссылаться на локальные файлы, которых нет в этом репозитории.
- Если ссылка ведёт в `hometutor-studio`, это нужно писать явно.
- При изменении маршрутов обновляйте [api_reference.md](api_reference.md).
- При изменении пользовательского поведения обновляйте [user_guide.md](user_guide.md) и [quickstart.md](quickstart.md).
