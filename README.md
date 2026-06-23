# hometutor

Локальный учебный RAG runtime: FastAPI + Streamlit + Chroma/BM25 + OpenAI-compatible LLM/embeddings.

Репозиторий содержит продуктовый runtime: API, UI, индексацию, learner state, tutor, quiz, flashcards, Smart Study Router, Knowledge Graph и эксплуатационные документы. Процессные материалы, backlog, user stories, сценарные манифесты и генератор demo-документа живут в `hometutor-studio`.

## Быстрый запуск

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`config.env` содержит tracked defaults. Локальные секреты и overrides кладите в `.env`:

```env
OPENAI_API_KEY=local-or-real-key
LLM_API_BASE=http://127.0.0.1:8080/v1
LLM_MODEL=your-local-model-id
EMBED_API_BASE=http://127.0.0.1:8080/v1
EMBED_MODEL=your-embedding-model-id
```

Проверка окружения:

```powershell
.\.venv\Scripts\python.exe scripts\local_readiness.py
```

Если хотите хранить `data/`, `chroma_db/`, `logs/` и `index_registry.json` прямо в checkout:

```powershell
$env:HOME_RAG_HOME = (Get-Location).Path
```

Индексация и запуск:

```powershell
.\.venv\Scripts\python.exe ingest.py
.\scripts\local_start.ps1 -SkipPip
```

Ручной запуск в двух терминалах:

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\streamlit.exe run app\ui\main.py
```

- Streamlit UI: http://127.0.0.1:8501
- API health: http://127.0.0.1:8000/health
- OpenAPI: http://127.0.0.1:8000/docs

## Docker

```powershell
docker compose up --build
```

Для локальных LLM профилей:

```powershell
docker compose -f docker-compose.yml -f docker-compose.lmstudio.yml up --build
docker compose -f docker-compose.yml -f docker-compose.llamacpp.yml up --build
```

## Основные документы

- [docs/index.md](docs/index.md) — карта актуальной runtime-документации.
- [docs/user_guide.md](docs/user_guide.md) — пользовательский путь и режимы приложения.
- [docs/quickstart.md](docs/quickstart.md) — локальный запуск и первый учебный цикл.
- [docs/quickstart_demo.md](docs/quickstart_demo.md) — demo-витрина GIF/PNG из `docs/screenshots/final/`.
- [docs/api_reference.md](docs/api_reference.md) — HTTP API.
- [docs/architecture.md](docs/architecture.md) — системная архитектура.
- [docs/technical_specification.md](docs/technical_specification.md) — runtime-модули, entrypoints, storage.

## Maintenance

```powershell
.\.venv\Scripts\python.exe scripts\check_chroma_health.py
.\.venv\Scripts\python.exe scripts\probe_graph_llm.py --live-doc --no-cache
.\.venv\Scripts\python.exe scripts\rebuild_knowledge_graph.py --dry-run
.\.venv\Scripts\python.exe scripts\audit_knowledge_graph.py
```

Опасные операции защищены confirmation token:

```powershell
.\.venv\Scripts\python.exe scripts\delete_all_data.py --verify-only --json
.\.venv\Scripts\python.exe scripts\fresh_start.py --confirm-token DELETE-ALL-LOCAL-HOME-RAG-DATA
```
