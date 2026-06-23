# Соглашения: prompts, API, ошибки, тесты, документация

Актуализировано: 2026-06-23.

## Prompts

- Prompt templates live in `app/prompts/`.
- Prompt names and exports должны проходить через package API, не через копипасту строк в UI/routers.
- Pipeline выбирает prompt через context/contract, а не через ad hoc if в endpoint.
- При изменении prompt behavior обновляйте smoke/trace ожидания и пользовательскую документацию, если меняется UX.

## API endpoints

- Полная карта API: [api_reference.md](api_reference.md) и live OpenAPI `/docs`.
- Структура endpoint: noun-first, action только когда это операция.
- GET — чтение; POST/PUT/PATCH/DELETE — side effects.
- Новый роутер подключается только в `app/api.py`.
- Если endpoint защищён, он должен корректно работать с `HOME_RAG_API_KEY` / `X-API-Key`.

## Ошибки и деградация

- Пользовательские ошибки должны быть понятными: что случилось и что проверить.
- `except Exception` допустим только как осознанный fallback с локальным rationale или логированием.
- Pipeline degradation:
  - classify -> fallback to `qa`;
  - rewrite -> passthrough;
  - rerank -> skip;
  - retrieval weakness -> disclaimer/trace;
  - generation failure -> surfaced error.
- File endpoints должны различать: not found, unsafe path, unsupported format, extraction failure.
- Guardrails возвращают 400/422 с безопасным сообщением.

## Тестирование и проверки

В этом runtime checkout может не быть локального `tests/` каталога, но зависимости для pytest присутствуют. Для изменений используйте доступную проверку по уровню риска:

| Изменение | Минимальная проверка |
|---|---|
| docs-only | link check по `docs/*.md`, `git diff` |
| API route/contract | OpenAPI/manual request или targeted pytest при наличии tests |
| query/retrieval | локальный `/ask` smoke на маленьком корпусе |
| ingestion | `ingest.py` на demo/малой папке |
| UI | запуск Streamlit и ручной проход affected screen |
| Docker/deploy | `docker compose config` или build smoke |

Если в окружении есть тесты:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Для localhost readiness:

```powershell
.\.venv\Scripts\python.exe scripts\local_readiness.py
```

## Документация

- Runtime-документы живут в `docs/`.
- Не ссылаться на локальные `doc/*`, `docs/screenshots/*`, `docs/scenarios/*`, если этих файлов нет.
- Если материал принадлежит `hometutor-studio`, пишите это явно.
- При изменении API обновляйте [api_reference.md](api_reference.md).
- При изменении пользовательского потока обновляйте [user_guide.md](user_guide.md) и [quickstart.md](quickstart.md).
- При изменении architecture/config/persistence обновляйте [architecture.md](architecture.md), [technical_specification.md](technical_specification.md) и при необходимости [conventions_architecture.md](conventions_architecture.md).

## Dependency policy

- Новые библиотеки добавлять только при явной необходимости.
- Предпочитать уже выбранный стек: FastAPI, Streamlit, llama-index, Chroma, pydantic-settings, aiogram, pytest.
- Optional heavy dependencies должны деградировать понятно в headless/local environments.
