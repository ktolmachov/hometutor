# hometutor — Деплой на Hugging Face Spaces (Docker SDK)

Этот каталог содержит конфигурацию для развёртывания **hometutor** в публичном
демо-режиме на **Hugging Face Spaces**, используя **Docker SDK** (не Streamlit SDK).

> Почему Docker, а не Streamlit SDK: Streamlit-SDK Space не запускает параллельно FastAPI
> (`app/api.py`), а Streamlit UI ходит в API по HTTP (`app/ui_client.py`). Docker-Space
> поднимает оба процесса через [`deploy/docker/docker_entrypoint.sh`](../docker/docker_entrypoint.sh)
> (см. корневой [`Dockerfile`](../../Dockerfile)): Streamlit публично на `8501`
> (это `app_port` в YAML-заголовке корневого `README.md`), uvicorn внутри контейнера на `8000`
> (Streamlit обращается к нему через `ui_api_base_url=http://127.0.0.1:8000`, наружу HF этот
> порт не проксирует).

В этом режиме приложение работает в связке: **Streamlit UI + FastAPI** + облачная LLM
(OpenRouter/OpenAI-совместимый провайдер) + заранее подготовленный демо-корпус (`demo_data/`)
и скомпилированный векторный индекс (`demo_chroma_db/`). При старте контейнера
[`bootstrap_demo_paths.sh`](bootstrap_demo_paths.sh) копирует их в рабочие `data/`/`chroma_db/`,
если они ещё пусты (эфемерный FS контейнера — см. ограничения ниже). Встроенный курс
`demo_data/uploads/hometutor_101/` гарантированно докладывается в `data/uploads/hometutor_101/`,
если курса там ещё нет: это self-demo курс о самом продукте с лекциями, smart-конспектами,
`*.media.json` и короткими MP4 для панели «🎞 Все видео урока» в Living Konspekt.

---

## 🎭 Плюсы и ограничения

### 👍 Плюсы
1. **Бесплатно (Free Tier):** CPU-инстанс (2 vCPU, 16 ГБ RAM) достаточен для Streamlit + FastAPI на облачной LLM.
2. **Публичный адрес 24/7:** постоянная HTTPS-ссылка `https://huggingface.co/spaces/<username>/hometutor`.
3. **Секреты:** ключи провайдеров, `JWT_SECRET`, `YANDEX_METRIKA_ID` хранятся в HF Space Secrets, не в репозитории.
4. **Полный runtime:** в отличие от Streamlit-SDK варианта, здесь работает и REST API (`/docs`, `/health`), и аутентификация (`AUTH_ENABLED=true`).
5. **Обновление:** snapshot-push (см. Шаг 4) — вручную или автоматически через `.github/workflows/deploy.yml`.

### 👎 Ограничения
1. **Только облачные LLM:** бесплатный тариф не запускает локальные модели (Ollama/LM Studio) — нет GPU/достаточного CPU.
2. **Эфемерный FS:** диск контейнера сбрасывается при каждом рестарте/пересборке Space.
   - Демо-корпус восстанавливается автоматически из `demo_data/`/`demo_chroma_db/` (см. выше).
   - Без attached volume `data/auth.db` (пользователи) и per-user
     `data/users/<id>/user_state.db` **не персистентны** — демо-аккаунты и прогресс обучения
     пропадают при рестарте контейнера.
   - Для постоянного хранения подключите Hugging Face Storage Bucket как read-write volume
     и смонтируйте его в `/data` (entrypoint автоматически использует `/data/hometutor`), либо
     задайте `HOME_RAG_HOME` на ваш mount path.

---

## 🔑 Секреты и переменные (Space Settings → Variables and secrets)

| Секрет/переменная | Пример значения | Назначение |
|---|---|---|
| `OPENAI_API_KEY` | `sk-or-v1-abc...` | API-ключ OpenRouter/OpenAI-совместимого провайдера |
| `OPENAI_API_BASE` | `https://openrouter.ai/api/v1` | URL провайдера |
| `HOME_RAG_HOME` | `/data/hometutor` | Корень persistent runtime-данных. Нужен, если bucket смонтирован не в `/data`; при mount `/data` выставляется автоматически |
| `HOME_RAG_DATA_MODE` | `demo` | Демо-режим данных; для HF выставляется автоматически, если переменная не задана |
| `HOME_RAG_LOCAL_PROFILE` | `cloud_fast` | Primary chat идёт сразу в облачный OpenAI-compatible endpoint |
| `OFFLINE_PROBE_LLM_ENDPOINT` | `false` | Не проверять loopback LM Studio/llama.cpp внутри Space |
| `LLM_LOCAL_WARMUP` | `false` | Не запускать startup-probe локального SSR endpoint |
| `LLM_MODEL` | `openai/gpt-4o-mini` | Модель тьютора/объяснений. Free-модели OpenRouter могут ловить upstream 429; для публичного demo лучше paid/BYOK model |
| `QUIZ_LLM_MODEL` | `openai/gpt-4o-mini` | Модель генерации квизов; по умолчанию в HF берётся из `LLM_MODEL` |
| `GRAPH_LLM_API_BASE` | `https://openrouter.ai/api/v1` | Endpoint для graph/concept LLM; по умолчанию в HF берётся из `OPENAI_API_BASE` |
| `GRAPH_MODEL` | `openai/gpt-4o-mini` | Graph/concept модель; по умолчанию в HF берётся из `LLM_MODEL` |
| `SSR_LLM_API_BASE` | `https://openrouter.ai/api/v1` | Endpoint Smart Study Router; по умолчанию в HF берётся из `OPENAI_API_BASE` |
| `SSR_LLM_MODEL` | `openai/gpt-4o-mini` | SSR-модель; по умолчанию в HF берётся из `LLM_MODEL` |
| `EMBED_API_BASE` | `https://openrouter.ai/api/v1` | Endpoint embeddings; должен соответствовать `EMBED_MODEL` |
| `EMBED_MODEL` | `perplexity/pplx-embed-v1-0.6b` | Модель эмбеддингов (должна совпадать с использованной при сборке `demo_chroma_db/`) |
| `EMBED_DIMENSIONS` | `1024` | Размерность векторов |
| `ENABLE_METADATA_ENRICHMENT` | `false` | Отключить фоновое обогащение (экономия токенов) |
| `ENABLE_DOCUMENT_SUMMARIES` | `false` | Отключить облачные суммаризации |
| `ENABLE_RERANKER` | `false` | Отключить тяжёлый локальный reranker |
| `TUTOR_INLINE_QUIZ_SEPARATE_LLM_CALL` | `false` | Не делать отдельный LLM-вызов для inline quiz после каждого ответа тьютора в HF demo |
| `ENABLE_TUTOR_AUTO_QUIZ_LOOP` | `false` | Не генерировать server-side micro-quiz автоматически после каждого tutor-turn в HF demo |
| `AUTH_ENABLED` | `true` | Включить логин/регистрацию (Workstream A) |
| `JWT_SECRET` | `<сильный случайный секрет>` | Подпись JWT — обязательно своё значение, не дефолт из `config.env` |
| `YANDEX_METRIKA_ID` | `<id счётчика>` | Опционально — аналитика посещений (Workstream E) |
| `CORS_ORIGINS` | `https://<username>-hometutor.hf.space` | Добавить домен Space, если открываете API напрямую |

`deploy/docker/docker_entrypoint.sh` выставляет HF-safe defaults для `HOME_RAG_*`,
`OFFLINE_PROBE_LLM_ENDPOINT`, `LLM_LOCAL_WARMUP`, tutor quiz latency-флаги,
`QUIZ_*`, `GRAPH_*`, `SSR_*` и `EMBED_API_BASE`, когда контейнер запущен в Hugging Face Space (`SPACE_ID` или
`SPACE_HOST` присутствует). Если в контейнере есть writable `/data`, entrypoint также
направляет runtime-состояние в `/data/hometutor`: там окажутся `data/auth.db`,
`data/users/<id>/user_state.db`, `chroma_db/` и `logs/`. Явно заданные Space
Variables/Secrets имеют приоритет.

---

## 🏃 Пошаговая инструкция по деплою

### Шаг 1: Сборка демонстрационного индекса
```bash
.\.venv\Scripts\python.exe scripts/build_demo_chroma.py
```

Пересобирайте `demo_chroma_db/` после изменения `demo_data/`, включая встроенный
`uploads/hometutor_101/`. Иначе файлы курса будут скопированы в Space, но готовый
прединдекс может ещё не отвечать по ним до ручного reindex из UI.

### Шаг 2: Коммит индекса
```bash
git add demo_chroma_db/
git commit -m "chore: pre-build demo database index"
```

### Шаг 3: Создание Space
1. [Hugging Face](https://huggingface.co/) → **New Space**.
2. SDK: **Docker**, тариф **CPU basic** (free).
3. **Settings → Variables and secrets** — добавить значения из таблицы выше.

### Шаг 4: Remote и отправка snapshot-коммита

> ⚠️ **Не делайте `git push space main`** — HF отклоняет push сырых бинарных блобов,
> а история `main` содержит PNG/GIF скриншотов. В Space пушится **один snapshot-коммит**
> дерева `main` без `doc/screenshots/` и `docs/screenshots/`; `demo_chroma_db/` и
> встроенные MP4 курса `hometutor_101` уходят LFS-указателями (правила в
> `.gitattributes`), их объекты заливаются `git lfs push`.

Требуется установленный [git-lfs](https://git-lfs.com/) (входит в Git for Windows;
проверка: `git lfs version`, разовая настройка хуков в репозитории: `git lfs install --local`).

PowerShell:

```powershell
git remote add space https://huggingface.co/spaces/ВАШ_ЛОГИН_HF/hometutor
# если remote уже существует:
# git remote set-url space https://huggingface.co/spaces/ВАШ_ЛОГИН_HF/hometutor

# snapshot-дерево без doc/screenshots и docs/screenshots (через временный индекс, рабочая копия не трогается);
# finally гарантирует сброс GIT_INDEX_FILE — иначе все последующие git-команды
# в этой сессии молча работали бы с временным индексом
try {
    $env:GIT_INDEX_FILE = ".git/space-index"
    git read-tree 'main^{tree}'
    git rm -r --cached --quiet --ignore-unmatch doc/screenshots docs/screenshots
    $tree = git write-tree
} finally {
    Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
}

$commit = git commit-tree -m "Deploy hometutor to HF Space" $tree
git lfs push space $commit
git push space "${commit}:refs/heads/main" --force
```

Корневой `README.md` уже содержит нужный YAML-заголовок (`sdk: docker`, `app_port: 8501`) —
отдельно копировать его не нужно (в отличие от старого Streamlit-SDK варианта).

### Шаг 5: Автодеплой из CI (опционально)
`.github/workflows/deploy.yml` делает то же самое автоматически (snapshot-коммит + LFS)
после успешного прохождения CI на `main`, если в GitHub Secrets заданы `HF_TOKEN`
и `HF_USERNAME`.

### Шаг 6: Проверка
Hugging Face соберёт образ по корневому `Dockerfile` и запустит
[`docker_entrypoint.sh`](../docker/docker_entrypoint.sh) (bootstrap demo-данных → uvicorn → streamlit).
Откройте публичную ссылку Space и зарегистрируйтесь (если `AUTH_ENABLED=true`).
Наружу HF проксирует только Streamlit (порт 8501) — REST API (`/health`, `/docs`) снаружи
недоступен; работу uvicorn проверяйте по логам Space (вкладка **Logs**: uvicorn стартует
до Streamlit, UI ходит к нему внутри контейнера через `http://127.0.0.1:8000`).
