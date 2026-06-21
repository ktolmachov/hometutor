---
title: ИИ-тьютор с RAG
emoji: 🎓
colorFrom: blue
colorTo: purple
sdk: streamlit
sdk_version: "1.32.0"
app_file: app/ui/main.py
pinned: false
---

# hometutor — Деплой на Hugging Face Spaces (Демо-режим)

Этот каталог содержит конфигурационные файлы для развёртывания **hometutor** в публичном демонстрационном режиме на платформе **Hugging Face Spaces**.

В этом режиме приложение работает в связке: **Streamlit UI** + **облачная LLM (OpenRouter / OpenAI)** + заранее подготовленный демонстрационный корпус лекций (`demo_data/`) и скомпилированный векторный индекс (`demo_chroma_db/`).

---

## 🎭 Плюсы и Минусы Hugging Face Spaces

### 👍 Плюсы:
1. **Полностью бесплатно (Free Tier):** Hugging Face предоставляет бесплатный CPU-инстанс (2 vCPU, 16 ГБ RAM), которого с запасом хватает для Streamlit UI.
2. **Публичный адрес 24/7:** Вы получаете постоянную HTTPS-ссылку вида `https://huggingface.co/spaces/<username>/hometutor`.
3. **Безопасное хранение ключей:** API-ключи провайдеров и настройки хранятся в зашифрованных секретах платформы (HF Secrets).
4. **Простой деплой:** Обновление приложения происходит стандартной отправкой коммитов (`git push spaces main`).

### 👎 Минусы:
1. **Только облачные LLM:** Бесплатный тариф не поддерживает запуск локальных моделей (Ollama / LM Studio) из-за нехватки GPU/CPU ресурсов.
2. **Фиксированный демонстрационный корпус:** Диск контейнера сбрасывается при перезапусках. Для стабильности используется готовая папка `demo_data/` и предрассчитанный индекс `demo_chroma_db/`.
3. **Без FastAPI REST API:** Streamlit SDK на Hugging Face Spaces блокирует запуск параллельных фоновых процессов вроде FastAPI (`api.py`). Работает только Streamlit UI. Для работы REST API требуется VPS или Docker Space.

---

## 🔑 Секреты и Переменные (Space Settings → Secrets)

Для работы приложения добавьте в настройках вашего Space следующие **Secrets**:

| Секрет | Пример значения | Назначение |
|---|---|---|
| `OPENAI_API_KEY` | `sk-or-v1-abc...` | API-ключ OpenRouter или OpenAI-compatible API |
| `OPENAI_API_BASE` | `https://openrouter.ai/api/v1` | URL-точка входа для API |
| `LLM_MODEL` | `mistralai/mistral-7b-instruct:free` | Модель для чата тьютора и объяснений |
| `EMBED_MODEL` | `perplexity/pplx-embed-v1-0.6b` | Модель для поиска векторов (должна совпадать с локальной при сборке) |
| `EMBED_DIMENSIONS` | `1024` | Размерность векторов (по умолчанию `1024`) |
| `ENABLE_METADATA_ENRICHMENT` | `false` | Отключить фоновое обогащение для экономии токенов |
| `ENABLE_DOCUMENT_SUMMARIES` | `false` | Отключить генерацию суммаризаций в облаке |
| `ENABLE_RERANKER` | `false` | Отключить реранкер (если не требуется тяжелый локальный BAAI) |

---

## 🏃 Пошаговая инструкция по деплою

### Шаг 1: Сборка демонстрационного индекса концептов
Перед отправкой кода соберите векторный индекс локально на вашей машине разработчика:
```bash
# Выполните в корне репозитория (нужны настройки .env для доступа к EMBED_MODEL)
.\.venv\Scripts\python.exe scripts/build_demo_chroma.py
```
Это прочитает файлы из `demo_data/` и соберёт готовую Chroma базу в `demo_chroma_db/`.

### Шаг 2: Коммит индекса в Git
Добавьте индекс в систему контроля версий:
```bash
git add demo_chroma_db/
git commit -m "chore: pre-build demo database index"
```

### Шаг 3: Создание репозитория на Hugging Face
1. Перейдите на [Hugging Face](https://huggingface.co/) и нажмите **New Space**.
2. Укажите имя (например, `hometutor`), выберите SDK **Streamlit** и бесплатный тариф **CPU basic**.
3. В созданном Space перейдите во вкладку **Settings** -> **Variables and secrets** и добавьте все переменные из таблицы выше.

### Шаг 4: Настройка локального репозитория
Добавьте удалённый репозиторий Hugging Face в список remote вашего Git:
```bash
git remote add spaces https://huggingface.co/spaces/ВАШ_ЛОГИН_HF/hometutor
```

### Шаг 5: Обновление README и отправка кода
Перед отправкой скопируйте блок метаданных (строки 1–10 этого файла с разделителями `---`) в самое начало вашего корневого файла `README.md` в корне проекта (иначе Hugging Face не распознает SDK).

Выполните отправку:
```bash
git add README.md
git commit -m "docs: sync hf spaces meta in root README"
git push spaces main --force
```

### Шаг 6: Запуск
Hugging Face автоматически соберёт образ и запустит контейнер. При старте скрипт [`bootstrap_demo_paths.sh`](bootstrap_demo_paths.sh) скопирует базу в рабочие директории, и веб-интерфейс станет доступен по вашей публичной ссылке!
