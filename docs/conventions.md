# Правила и соглашения по разработке

Актуализировано: 2026-07-12.

Роль документа: короткий live-набор правил для runtime-репозитория `hometutor`. Подробности вынесены в [conventions_architecture.md](conventions_architecture.md) и [conventions_reference.md](conventions_reference.md).
Инженерный стиль маленьких проверяемых волн описан отдельно:
[evolutionary_development.md](evolutionary_development.md).

## TL;DR

- KISS: маленькие модули, явные зависимости, без лишних слоёв.
- Конфиг: только `get_settings()` / `get_retrieval_settings()` из `app/config.py`.
  Путь к `data/`: `get_settings().data_dir` или `app.path_safety.get_data_dir()`
  (не `from app.config import DATA_DIR` в новом app-коде).
- LLM и embeddings: только через `app/provider.py`.
- HTTP: роутеры в `app/routers/*`, сборка приложения в `app/api.py`.
- UI: Streamlit-модули в `app/ui/*`; бизнес-логику не дублировать во view-коде.
- Persistence: user-state через `app/user_state*.py`; не открывать SQLite напрямую из UI/роутеров.
- Входы: все entry points (API, CLI, UI, Telegram) проходят `app/guardrails.py` / `app/input_validation.py`.
- Retrieval: profiles и modes проводить через существующие registry/contract modules (`app/retrieval_strategies.py`).
- Prompts: использовать пакет `app/prompts/`.
- Ошибки: без bare `except:`; широкий `except Exception` — только осознанный fallback с rationale.
- Проверки: targeted pytest по затронутой области + `ruff check` (конфигурация в `pyproject.toml`); полный прогон — только по явной просьбе.
- Документация: при изменении runtime-поведения обновлять `docs/`.

## Основные принципы

- Простота важнее архитектурной демонстративности.
- Новый слой добавляется только если он снижает реальную сложность или риск.
- Доменные сервисы должны быть переиспользуемыми из FastAPI, Streamlit и Telegram.
- Ошибки должны деградировать понятно для пользователя и диагностируемо для разработчика.
- Runtime-документы не должны ссылаться на локальные файлы, которых нет в этом репозитории.

## Стиль кода

- Следовать PEP 8 и локальным паттернам.
- Предпочитать небольшие функции с ясной ответственностью.
- Комментарии писать только там, где они объясняют неочевидную причину.
- Не хардкодить provider/model/path в бизнес-логике: использовать settings/provider/path helpers.
- Не расширять публичный API без обновления [api_reference.md](api_reference.md).

## Навигация

| Тема | Где читать |
|---|---|
| архитектурные границы, config, persistence, retrieval | [conventions_architecture.md](conventions_architecture.md) |
| prompts, API, errors, testing, docs | [conventions_reference.md](conventions_reference.md) |
| эволюционный подход, волны, критерии завершения | [evolutionary_development.md](evolutionary_development.md) |
| runtime architecture | [architecture.md](architecture.md) |
| HTTP API | [api_reference.md](api_reference.md) |
