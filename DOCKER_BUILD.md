# Docker: сборка и деплой hometutor

## Быстрый старт

```powershell
cd D:\Projects\hometutor

# 1. Подготовить секреты
copy .env.example .env
# Отредактировать .env: заполнить OPENAI_API_KEY и/или LLM_API_BASE

# 2. Подготовить данные (если нет)
# Положить PDF/MD в ./data/<курс>/
# Или использовать ./demo_data/ (копируется в образ)

# 3. Собрать и запустить
docker compose up --build
```

После старта:
- FastAPI: http://127.0.0.1:8000/docs
- Streamlit UI: http://127.0.0.1:8501

## Что происходит при сборке

```
Dockerfile
├── FROM python:3.11-slim
├── pip install -r requirements.txt      ← зависимости (кеш Docker слоёв)
├── COPY deploy/docker/docker_entrypoint.sh  ← скрипт запуска (uvicorn + streamlit)
├── COPY . .                             ← код приложения (см. .dockerignore)
└── ENTRYPOINT docker_entrypoint.sh      ← стартует оба сервиса
```

`.dockerignore` исключает: `.git`, `.venv`, `data/`, `chroma_db/`, `logs/`, `.env`, `tests/`, `doc/`, `__pycache__/`.

## Тома (volumes)

```yaml
volumes:
  - ./data:/app/data            # Документы + user_state.db + кэш
  - ./chroma_db:/app/chroma_db  # Векторный индекс
  - ./logs:/app/logs            # Логи, метрики
  - ./.env:/app/.env:ro         # Секреты (read-only)
```

Все данные — на хосте. Пересборка образа **не затрагивает** состояние ученика, индекс и логи.

## Первая индексация

После первого `docker compose up` индекс пустой. Два варианта:

**A. Индексация внутри контейнера:**
```powershell
docker compose exec hometutor python ingest.py
```

**B. Индексация на хосте (быстрее, если venv уже есть):**
```powershell
cd D:\Projects\hometutor
.\.venv\Scripts\python ingest.py
# chroma_db/ появится на хосте → Docker подхватит через volume
```

## Пересборка после изменений кода

```powershell
docker compose up --build
```

Docker кеширует слой `pip install` — пересборка занимает секунды, если `requirements.txt` не менялся.

## С LM Studio / Ollama на хосте

```powershell
docker compose -f docker-compose.yml -f docker-compose.lmstudio.yml up --build
```

В `.env`:
```
LLM_API_BASE=http://127.0.0.1:1234/v1
```

socat-мост пробрасывает `127.0.0.1:1234` контейнера → `host.docker.internal:1234` хоста.

## Деплой в `d:\AI\app\` через Docker

Одна переменная `HOME_RAG_HOME` переключает все тома:

```powershell
cd D:\Projects\hometutor

# Вариант A: через переменную окружения
$env:HOME_RAG_HOME="D:/AI/app"
docker compose up --build -d

# Вариант B: прописать в D:\AI\app\.env
# HOME_RAG_HOME=D:/AI/app
# тогда просто:
docker compose up --build -d
```

Docker-compose подставит `HOME_RAG_HOME` в пути volume mounts:
- `D:/AI/app/data` → `/app/data`
- `D:/AI/app/chroma_db` → `/app/chroma_db`
- `D:/AI/app/logs` → `/app/logs`
- `D:/AI/app/.env` → `/app/.env`

Без `HOME_RAG_HOME` — дефолт `./` (данные рядом с репо).

### Переиндексация с хоста

```powershell
cd D:\Projects\hometutor
$env:HOME_RAG_HOME="D:/AI/app"
.\.venv\Scripts\python ingest.py
# config.py прочитает HOME_RAG_HOME и направит данные в D:\AI\app\
# контейнер подхватит свежий индекс без рестарта
```

## Проверка

```powershell
# Статус
docker compose ps

# Логи
docker compose logs -f --tail 50

# Health check
curl http://127.0.0.1:8000/health

# Shell внутри контейнера
docker compose exec hometutor bash

# Остановить
docker compose down
```

## Troubleshooting

| Проблема | Решение |
|---|---|
| `port 8000 already in use` | Остановить другой инстанс: `docker compose down` или убить процесс на порту |
| `ModuleNotFoundError` | `docker compose build --no-cache` (пересоберёт с нуля) |
| Индекс не видно | Проверить, что `./chroma_db` на хосте не пустой; `docker compose exec hometutor python ingest.py` |
| LM Studio не доступен | Использовать `docker-compose.lmstudio.yml` override; проверить что LM Studio слушает на `0.0.0.0`, не только `127.0.0.1` |
