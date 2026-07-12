# Быстрый старт

Актуализировано: 2026-07-10.

Цель этого документа: поднять `hometutor` локально, проиндексировать материалы и пройти первый учебный цикл: вопрос -> ответ с источниками -> тьютор -> quiz/flashcards -> прогресс -> живой конспект.

## Что нужно

- Windows PowerShell, Python 3.11+ и Git.
- Доступный OpenAI-compatible LLM endpoint: локальный LM Studio/llama.cpp/Ollama-compatible proxy или облачный провайдер.
- Учебные файлы в `data/`: `.pdf`, `.docx`, `.md`, `.html`, `.txt`.

`config.env` хранит tracked defaults. Локальные секреты и переопределения кладите в `.env`: `app/config.py` читает сначала `config.env`, затем `.env` с приоритетом `.env`.

## 1. Установка

```powershell
git clone <repo-url> hometutor
cd hometutor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Создайте `.env` только с локальными секретами и нужными overrides.

**Fully local (рекомендуется для приватных материалов):**

```env
OPENAI_API_KEY=local-no-key
LLM_API_BASE=http://127.0.0.1:8080/v1
LLM_MODEL=your-local-model-id
EMBED_API_BASE=http://127.0.0.1:1234/v1
EMBED_MODEL=text-embedding-qwen3-embedding-0.6b
```

**С облачными embeddings (данные уходят провайдеру):**

```env
OPENAI_API_KEY=sk-...
LLM_API_BASE=http://127.0.0.1:8080/v1
LLM_MODEL=your-local-model-id
EMBED_API_BASE=https://openrouter.ai/api/v1
EMBED_MODEL=perplexity/pplx-embed-v1-0.6b
```

> **Privacy:** `config.env` по умолчанию направляет embeddings на локальный loopback endpoint (`127.0.0.1:1234/v1`). Если вы выбираете облачный embedding provider, задайте `EMBED_API_BASE` и `EMBED_MODEL` явно в `.env` и считайте это opt-in: при индексации и запросах чанки документов отправляются провайдеру.

Убедитесь, что `LLM_MODEL` и `EMBED_MODEL` совпадают с идентификаторами моделей, которые отдаёт ваш локальный сервер (`GET /v1/models`). Дефолтные значения в `config.env` (`qwopus3.6-35b-a3b-v1-mtp`, `text-embedding-qwen3-embedding-0.6b`) — это локальная рабочая установка; на чистом клоне их можно заменить на модели, которые реально загружены у вас.

## 2. Проверка окружения

```powershell
.\.venv\Scripts\python.exe scripts\local_readiness.py
```

Проверка смотрит локальные каталоги, `.venv`, конфигурацию, порты `8000/8501` и, при явной опции, уже поднятые endpoints.

Если API/Streamlit уже запущены:

```powershell
.\.venv\Scripts\python.exe scripts\local_readiness.py --allow-running --check-running
```

## 3. Данные и индекс

Положите материалы в `data/` или задайте внешний корень через `HOME_RAG_HOME`.

> **Важно:** `scripts\local_start.ps1` и `docker-compose.yml` по умолчанию используют `HOME_RAG_HOME=D:\AI\app` — путь конкретной машины автора. На чистом клоне этого каталога нет, и запуск упадёт или будет работать с пустым `data/`. Задайте переменную перед запуском:

```powershell
$env:HOME_RAG_HOME = (Get-Location).Path
```

```powershell
.\.venv\Scripts\python.exe ingest.py
```

Индекс и runtime-артефакты:

| Артефакт | Где лежит |
|---|---|
| исходные материалы и `user_state.db` | `data/` |
| Chroma/BM25 индекс | `chroma_db/` |
| active generation pointer | `index_registry.json` в `HOME_RAG_HOME` (по умолчанию корень checkout; при внешнем `HOME_RAG_HOME` — внешний runtime root) |
| логи, метрики, SSR-профили | `logs/` |

## 4. Запуск

Самый простой путь:

```powershell
.\scripts\local_start.ps1 -SkipPip
```

Ручной путь, в двух терминалах:

```powershell
.\.venv\Scripts\python.exe main.py
```

```powershell
.\.venv\Scripts\streamlit.exe run app\ui\main.py
```

Откройте:

- Streamlit UI: http://127.0.0.1:8501
- API health: http://127.0.0.1:8000/health
- OpenAPI: http://127.0.0.1:8000/docs

Опционально: включите read-only agent-сценарии в `.env` или `config.env`:

```env
AGENT_ENABLED=true
```

Smoke-проверка agent mode через API:

```powershell
$body = @{
  question = "Собери короткую учебную сессию по теме из моих материалов"
  query_mode = "agent"
  session_id = "agent-smoke"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/ask" `
  -ContentType "application/json" `
  -Body $body
```

В ответе проверьте `answer_status`, `debug.answer_path.scenario_id`,
`debug.agent_trace.run_id` и `debug.agent_trace.tool_calls`. Agent-сценарии
read-only: кроме compact run trace они не сохраняют карточки, quiz-result,
правки графа или Живого конспекта.

Опциональный прогрев retrieval после старта API:

```powershell
.\scripts\Warmup-HomeRagRag.ps1
```

## 5. Первый учебный цикл

1. На главной откройте `Быстрый ответ`.
2. Задайте вопрос по материалам.
3. Проверьте источники и confidence.
4. Перейдите в `Чат с тьютором`, если нужно разобрать тему.
5. Откройте `Интерактивный Quiz`, чтобы проверить понимание.
6. Создайте колоду во `Flashcards`, отредактируйте preview и сохраните.
7. Во вкладке `Прогресс обучения` посмотрите adaptive plan, mastery и следующий шаг.
8. В `Knowledge Graph` выберите концепт: у связанных документов видны точные разделы конспекта («📍 «заголовок»» — Obsidian, «🖥 VS Code: раздел» — строка файла); кнопками «➕ раздел» / «➕ Собрать всё по концепту» наполните корзину.
9. Откройте `Живой конспект`: добавьте разделы через встроенный поиск по markdown-конспектам или из уже наполненной корзины, упорядочьте их кнопками `↑`/`↓`, при необходимости используйте bulk-действия документа, прочитайте сборку во вкладке `📖 Читать`, оставьте «Мою мысль» и отметьте прочитанные фрагменты, затем сохраните рабочий конспект (дословная сшивка или LLM-синтез). Во вкладке `🌐 Дальше` проверьте актуальность по «🔗 Ссылкам из лекции» и поисковикам, посмотрите graph-lens и скопируйте deep-study промпт для облачной модели. Если у конспекта есть валидный `.media.json` sidecar, панель покажет все видео урока, плейлист «Мои N минут», а раздел — безопасный timestamp action только для доверенного таймкода; low-confidence остаётся кандидатом без встроенного видео. Результат сохраняется в `data/living-konspekt/` и попадёт в поиск и граф после обновления индекса.

Точные разделы работают для документов с подготовленным конспектом (кнопка «Подготовить для Obsidian» во вкладке `Темы`); для `.txt` без конспекта UI подскажет подготовить его.

Медиа-панель в `Живом конспекте` пока не создаёт sidecar сама: ASR/import видео и автоматическое
выравнивание таймкодов относятся к следующему этапу. Уже существующий sidecar должен лежать
внутри `data/`, pointer в frontmatter должен быть `DATA_DIR`-relative, а полный список роликов
можно хранить в `media.videos[]` при сохранении основного источника в `media.video`.

Главная `Mission Control` собирает resume-карточки, Smart Study Router и быстрые переходы в режимы: `Быстрый ответ`, `Тьютор`, `Quiz`, `Flashcards`, `Темы`, `Курс`, `Адаптивный план`, `Агент` (при `AGENT_ENABLED=true`), `Knowledge Graph`, `Живой конспект`, `История`, `Метрики`, `Объяснить файл`.

## Docker

```powershell
docker compose up --build
```

По умолчанию compose монтирует данные из `${HOME_RAG_HOME:-D:/AI/app}`. Для LM Studio или llama.cpp используйте overlay-файлы:

```powershell
docker compose -f docker-compose.yml -f docker-compose.lmstudio.yml up --build
docker compose -f docker-compose.yml -f docker-compose.llamacpp.yml up --build
```

## Если что-то не работает

| Симптом | Что проверить |
|---|---|
| API не стартует | порт `8000`, `.env`, `OPENAI_API_KEY`, доступность LLM endpoint |
| UI не открывается | порт `8501`, запущен ли `main.py`, значение `UI_API_BASE_URL` |
| Streamlit падает с `WinError 10055` / `socketpair` | закройте лишние `python.exe`/Streamlit/localhost-вкладки и перезапустите терминал; если повторяется — выполните `netsh winsock reset` от администратора, перезагрузите Windows и снова запустите `.\scripts\local_start.ps1 -SkipPip` |
| нет источников | был ли выполнен `ingest.py`, есть ли файлы в `data/`, не пуст ли `chroma_db/` |
| Knowledge Graph пустой | graph LLM / `graph_quality_report.json` в `data/graph_generations/`; graph-only пересборка без re-embed: `scripts/rebuild_knowledge_graph.py` пишет `graph_audit_report.json/.md` рядом с bundle |
| проверить graph LLM перед сменой модели | `scripts/probe_graph_llm.py --live-doc --no-cache` → отчёт в `logs/graph_llm_probe_report.json` |
| локальный LLM недоступен | `LLM_API_BASE`, id модели, запущен ли LM Studio/llama.cpp |
| REST возвращает `401` | задан `HOME_RAG_API_KEY`; добавьте заголовок `X-API-Key` |

Дальше: [user_guide.md](user_guide.md), [api_reference.md](api_reference.md), [architecture.md](architecture.md).
