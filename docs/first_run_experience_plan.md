# Первый запуск без тупиков: пять работ для нового пользователя

Статус: ТЗ к реализации (handoff-документ, самодостаточный).
Подготовлено: 2026-07-03. Родственный документ: `docs/ui_visibility_phase1_plan.md`
(уровни интерфейса — работа W5 ссылается на него, остальные независимы).

## 1. Контекст проекта (минимум для исполнителя)

`hometutor` — локальный учебный RAG-сервис: FastAPI (`app/routers/*`) + Streamlit UI
(`app/ui/*`, entry `app/ui/main.py`) + Chroma/BM25 + SQLite user-state
(`app/user_state*.py`). Язык UI — русский. Local-first: UI и API работают на одной
машине (или в одном Docker-контейнере), у Streamlit-процесса есть прямой доступ к
файловой системе проекта.

Конвенции (`docs/conventions.md`): KISS; конфиг только через `get_settings()`;
persistence через `app/user_state*.py`; бизнес-логику не дублировать во view-коде;
LLM только через `app/provider.py`; при изменении runtime-поведения обновлять `docs/`.

Проверка перед сдачей каждого шага:

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

### Верифицированные факты (проверены по коду 2026-07-03)

| Факт | Где |
|---|---|
| UI→API клиент: `fetch_json(method, path, timeout=, json=, params=)`, сам подставляет `X-API-Key` и Bearer | `app/ui_client.py:40` |
| Сброс кэшей GET после переиндексации: `clear_ui_api_caches()` | `app/ui_client.py:183` |
| `GET /health/deep` — компоненты `index` (`ok/empty/missing/error` + counts), `llm` (`ok/timeout/error`, latency_ms, llm-проба с таймаутом 2 с), `api`; верхний `status: ok/degraded`. Публичный, без auth | `app/routers/core.py:75` |
| `POST /reindex?reset=false` → `{"status":"started"}`, фоновая задача; `GET /reindex/status` → в т.ч. `ingest_run_summary` | `app/routers/admin.py:111` |
| Паттерн поллинга статуса переиндексации в UI (session flag `poll_reindex_status`) | `app/ui/query_tab_poll.py:10` |
| Кнопка «Переиндексировать» уже есть во вкладке «Быстрый ответ» | `app/ui/query_tab_ask_panel.py:133` |
| Важно: текущий poller `poll_reindex_status_for_query_tab()` вызывается только в Quick Answer (`query_tab.py`, `quick_answer.py`), поэтому флаг `poll_reindex_status` сам по себе **не работает на Mission Control** | grep по `poll_reindex_status_for_query_tab` |
| Важно: `build_index(reset=...)` сейчас падает при нуле поддерживаемых файлов до очистки/активации индекса (`ValueError("В папке data нет поддерживаемых документов")`). Удаление последних демо-файлов нельзя закрывать обычным `reset=false` | `app/ingestion_loader.py:201–204, 373–382` |
| Пути данных: `DATA_DIR` (env `HOME_RAG_DATA_DIR`, по умолчанию `HOME_RAG_HOME/data`) | `app/config.py:46` |
| Демо-материалы: `demo_data/` в корне репо — 6 учебных `.md` (alpha_rag_intro, beta_vector_db, gamma_hybrid, delta_srs, epsilon_guardrails, python_basics) + README.md. **Нигде в `app/` не используются** | корень репо |
| В UI нет загрузки материалов: единственные `st.file_uploader` — временный файл для флеш-карт (`flashcards_generate_view.py:284`) и JSON-бэкап (`sidebar.py:262`) | grep по `file_uploader` |
| Пустой индекс в сайдбаре: текст «Индекс пока недоступен…» без CTA | `app/ui/sidebar.py:434` |
| Баннер здоровья LLM покрывает **только SSR-endpoint** (payload `llm_local` из bootstrap); тексты подсказок «запустите LM Studio, загрузите модель X» уже написаны там | `app/ui/llm_local_banner.py:25` |
| `/health/deep` не вызывается ни из одного UI-модуля | grep по `health/deep` в `app/ui` |
| Онбординг: модальный диалог при `get_kv("onboarding_v1_done") != "1"`, спрашивает цель+время, кнопка ведёт в «Чат с тьютором», ставит KV и session-ключи `learning_goal`, `tutor_answer_depth`, `estimated_minutes`, вызывает `set_preferred_style("balanced")`, `_persist_tutor_goal_snapshot_from_session()`, `track_event("onboarding_completed", ...)` | `app/ui/home_hub.py:60–112`, показ в `app/ui/main.py:97–103` |
| Seed-вопросы: `build_first_session_artifact()` строит 3 детерминированных вопроса по шаблонам `_DEFAULT_SEED_TEMPLATES` + retrieval trace; артефакт course-scoped, собирается на хвосте ingest | `app/services/first_session_builder.py:20,141` |
| Рендер seed-вопросов на главной уже есть, но только при активном course scope и готовом артефакте; иначе пассивное «Первый обзор курса готовится…» | `app/ui/mission_control_first_session.py:199–227` |
| `GET /kb/suggestions` **требует** параметр `question` — это follow-up-подсказки, для стартовых вопросов не подходит | `app/routers/knowledge.py:305` |
| Каталог тем доступен в session_state после bootstrap: `st.session_state["topics_catalog"]` (`{"topics": [{"topic_name": ...}, ...]}`); ленивая загрузка — `app/ui/topics_catalog.py::load_topics_catalog()` | `app/ui/main.py:104–108` |
| Список файлов индекса: `index_stats["files"]`, статус: `index_stats["status"] == "ok"`, `documents_count` | использование в `sidebar.py:414+` |
| Событийная аналитика UI: `from app.ui_events import track_event` | использование в `home_hub.py:62` |
| Навигация: `st.session_state["current_view"]`; отложенный переход — `PENDING_CURRENT_VIEW_KEY` из `app/ui/session_state.py`; префилл вопроса + переход на «Быстрый ответ» — колбэк `_prefill_and_navigate_to_quick_answer` в `mission_control.py` (передаётся как `navigate_to_question`) | `app/ui/mission_control.py:540–546` |
| Черновик вопроса Quick Answer: `st.session_state["question_draft"]` | `app/ui/sidebar.py:86` |
| Фаза 1 уровней интерфейса уже в текущем коде: `ALL_VIEWS` вынесен в constants, `get_ui_level()` импортируется и используется в `main.py`; W5 больше не нужно откладывать “до влития Фазы 1” | `app/ui/main.py:25,51,248–261`, `app/ui_preferences.py:59` |

## 2. Общая цель

Новый пользователь за первые 2 минуты должен: увидеть, готова ли система;
получить материалы в индекс (свои или демо) без терминала; получить первый ответ
по клику на готовый вопрос. Ни одно состояние не заканчивается текстом без кнопки.

Пять работ ниже независимы, кроме указанных зависимостей. Каждая — отдельный
коммит (или PR), после каждой ruff + pytest зелёные.

---

## W1. Демо-песочница и загрузка материалов (empty-state rescue)

**Проблема.** При пустом `data/` UI — тупик: материалы добавляются только руками
через файловую систему + `ingest.py`/кнопка «Переиндексировать», спрятанная во
вкладке «Быстрый ответ». `demo_data/` не предлагается.

### W1.1 Домен: `app/demo_sandbox.py` (без Streamlit-импортов)

```python
DEMO_SUBDIR = "demo"          # DATA_DIR / "demo"
UPLOADS_SUBDIR = "uploads"    # DATA_DIR / "uploads"
ALLOWED_UPLOAD_EXTS = {".md", ".txt", ".pdf", ".docx", ".html"}

def demo_source_dir() -> Path: ...        # BASE_DIR / "demo_data" (BASE_DIR из app.config)
def demo_target_dir() -> Path: ...        # DATA_DIR / DEMO_SUBDIR
def is_demo_installed() -> bool: ...
def install_demo_materials() -> list[str]: ...
    # Копирует *.md из demo_data/ (кроме README.md) в DATA_DIR/demo/.
    # Идемпотентно (перезапись допустима). Возвращает список относительных путей.
def remove_demo_materials() -> int: ...
    # Удаляет ТОЛЬКО DATA_DIR/demo/ (проверить, что путь — потомок DATA_DIR; паттерн
    # безопасности путей см. app/path_safety.py). Возвращает число удалённых файлов.
def count_supported_materials() -> int: ...
    # Считает поддерживаемые документы в DATA_DIR после операций с demo/uploads.
    # Использовать те же расширения, что ingestion: .pdf/.txt/.md/.docx/.html.
def save_uploaded_files(files: list[tuple[str, bytes]]) -> list[str]: ...
    # Сохраняет в DATA_DIR/uploads/ с санитизацией имён (только basename, разрешённые
    # расширения, замена недопустимых символов); возвращает сохранённые пути.
```

Флаг песочницы: `set_kv("demo_sandbox_active", "1"/"0")` — для баннера.

### W1.2 UI: `app/ui/first_run.py`

`render_empty_index_hero(index_stats) -> bool` (True = отрисован, дальше
Mission Control рисовать в сокращённом виде):

- Условие показа: `index_stats` — dict и (`status != "ok"` или `documents_count == 0`).
  Если `index_stats is None` (API недоступен) — hero НЕ показывать: это зона W2.
- Заголовок: «Добавьте материалы — и получите первый ответ за минуту».
- Три двери (колонки):
  1. **Загрузить файлы**: `st.file_uploader(accept_multiple_files=True,
     type=[...ALLOWED_UPLOAD_EXTS])` → `save_uploaded_files` →
     `fetch_json("POST", "/reindex", params={"reset": False}, timeout=30)` →
     `st.session_state["poll_reindex_status"] = True` → `st.rerun()`.
  2. **Попробовать на демо-материалах**: кнопка → `install_demo_materials()` →
     `set_kv("demo_sandbox_active", "1")` → тот же reindex-поллинг. После
     успешного статуса `completed` poller сбрасывает UI-кэши и пользователь сразу
     видит seed-вопросы (W4) по демо-темам.
  3. **У меня уже есть папка**: caption с путём `DATA_DIR` (показать реальный
     resolved путь) + кнопка «Переиндексировать» (тот же вызов).
- `track_event("first_run_door_selected", {"door": "upload"|"demo"|"folder"})`.

Баннер песочницы (рисовать на Mission Control, когда
`get_kv("demo_sandbox_active") == "1"` и индекс не пуст): «Вы в демо-песочнице —
это учебные материалы для знакомства. Замените их на свои конспекты, когда будете
готовы» + кнопка «Удалить демо-материалы» → `remove_demo_materials()` →
`set_kv("demo_sandbox_active", "0")` → если `count_supported_materials() > 0`,
запустить `/reindex?reset=false`; если поддерживаемых файлов не осталось,
запустить `/reindex?reset=true` и активировать пустой индекс (см. W1.5) →
`poll_reindex_status`.

### W1.3 Интеграция

- `app/ui/mission_control.py::render_mission_control`: порядок строго такой:
  сначала `render_preflight_card()` из W2; если он вернул `"api_down"` — сразу
  выйти; затем `render_empty_index_hero(index_stats)`. Если hero вернул True,
  отрисовать только hero и выйти (не рисовать SSR/плитки по пустой базе).
- Вынести `poll_reindex_status_for_query_tab()` в нейтральный общий poller
  (`app/ui/reindex_poll.py::poll_reindex_status()`), вызывать его и в
  Mission Control, и в Quick Answer. Обновить оба существующих call-site старого
  поллера: `app/ui/query_tab.py:12,26` и `app/ui/quick_answer.py:14,59`.
  Именно poller при `status == "completed"` вызывает `clear_ui_api_caches()` и
  `st.rerun()`. До завершения фоновой индексации кэши не чистить: иначе
  bootstrap может снова закэшировать пустой индекс.
- `app/ui/sidebar.py:434`: к тексту «Индекс пока недоступен…» добавить кнопку
  «Добавить материалы» → переход на Mission Control (`current_view = HOME_VIEW`
  через `PENDING_CURRENT_VIEW_KEY`).

### W1.4 Backend: пустой reset после удаления последних файлов

Сейчас `POST /reindex?reset=true` тоже падает, если в `DATA_DIR` нет ни одного
поддерживаемого документа (`ingestion_loader.py:201–204`). Для удаления
демо-песочницы это критичный баг: файлы удалены, а активный Chroma-индекс может
остаться с демо-документами.

Минимальная правка в существующем `/reindex`, без нового endpoint:

- в `ingestion_loader.build_index(reset=True)`, если `file_count == 0`, создать
  пустые canonical collections (chunks + summaries), вызвать
  `activate_reset_generation(..., documents_count=0, summary_documents_count=0,
  nodes_count=0, source_paths=[], source_content_hashes=[])`, затем
  `clear_retrieval_cache()`, `apply_index_activation_hooks(reset=True)`,
  `update_snapshot_after_index()` и выставить `_ingestion_status["status"] =
  "completed"` с human-readable summary «Индекс очищен: материалов нет»;
- `reset=False` при пустом `DATA_DIR` остаётся ошибкой, чтобы случайный обычный
  reindex не стирал рабочий индекс;
- `/health/deep` после такого reset должен вернуть `index.status == "empty"`,
  а `/index/stats` — `status: "ok", documents_count: 0, files: []`.

### W1.5 Тесты

- `install_demo_materials`: копирует ровно 6 `.md`, пропускает README, идемпотентно
  (tmp_path + monkeypatch `DATA_DIR`/`demo_source_dir`).
- `remove_demo_materials`: удаляет только `DATA_DIR/demo`, отказывается работать
  вне `DATA_DIR`.
- `count_supported_materials`: считает только `.pdf/.txt/.md/.docx/.html`,
  игнорирует README/служебные файлы, корректно работает при пустом `DATA_DIR`.
- `save_uploaded_files`: отбрасывает запрещённые расширения, санитизирует
  `../evil.md` → `evil.md`.
- Чистая функция условия показа hero: `(None → False)`, `({"status":"ok",
  "documents_count":5} → False)`, `({"status":"empty"} → True)`,
  `({"status":"ok","documents_count":0} → True)`.
- Backend-тест: `build_index(reset=True)` при пустом `DATA_DIR` не падает,
  активирует пустой индекс и приводит `/index/stats` к `documents_count == 0`.
- UI/poller-тест: после `status == "completed"` вызывается `clear_ui_api_caches()`;
  сразу после `POST /reindex` кэши не сбрасываются.

**DoD W1:** свежая установка (пустой `data/`) → Mission Control показывает три
двери; клик по «демо» без терминала приводит к проиндексированной базе и living
Mission Control; баннер песочницы удаляется одной кнопкой.

---

## W2. Предполётный чек готовности системы

**Проблема.** Если LM Studio/llama.cpp не запущен, пользователь узнаёт об этом
после ввода вопроса и ожидания (таймаут `/ask` — 120 с). `/health/deep` в UI не
используется; llm_local_banner покрывает только SSR-endpoint.

### W2.1 UI: `app/ui/preflight.py`

```python
@st.cache_data(ttl=45, show_spinner=False)
def _cached_health_deep(api_base: str) -> dict | None: ...
    # GET /health/deep, timeout=8 (llm-проба внутри ограничена 2 с), None при ошибке сети.

def preflight_rows(payload: dict | None) -> list[tuple[str, str, str]]: ...
    # Чистая функция: payload -> [(label_ru, status_icon, hint_ru)].
    # index: ok→«Материалы: N документов»; empty/missing→«Материалов нет —
    #   добавьте ниже» (ссылка на W1); error→текст ошибки коротко.
    # llm: ok→«Модель отвечает (X мс)»; timeout/error→«Запустите LM Studio или
    #   совместимый сервер и загрузите модель {settings.llm_model}; адрес:
    #   {settings.llm_api_base}» (переиспользовать формулировки llm_local_banner).
    # payload is None → одна строка «API недоступен — запустите main.py
    #   (см. quickstart.md)».

def render_preflight_card() -> str: ...
    # Возвращает overall: "ok" | "degraded" | "api_down".
    # overall ok → одна строка-caption «Система готова: материалы · модель · API» —
    #   без expander'а, максимально тихо.
    # degraded/api_down → st.warning-блок со строками + кнопка «Проверить снова»
    #   (clear cache _cached_health_deep + st.rerun()).
```

### W2.2 Интеграция

- `mission_control.py::render_mission_control`: `render_preflight_card()` первым
  блоком. Если вернул `"api_down"` — не рисовать hero W1 (files-операции всё равно
  бессмысленны без API для reindex), показать только карточку.
- «Быстрый ответ» (`query_tab_ask_panel.py`): перед полем вопроса, только если
  статус не ok (тихий режим: при ok ничего не рисовать, чтобы не дублировать).
- `track_event("preflight_status", {"overall": ...})` — один раз за сессию
  (session_state-флаг).

### W2.3 Тесты

Чистые тесты `preflight_rows`: все комбинации статусов index/llm из
`app/routers/core.py:75–128` (ok/empty/missing/error × ok/timeout/error), payload
None. Проверить, что тексты не содержат сырых traceback.

**DoD W2:** с выключенным LM Studio пользователь видит жёлтую карточку с
конкретным действием ДО ввода вопроса; после запуска сервера «Проверить снова»
переводит карточку в тихую зелёную строку.

---

## W3. Инверсия онбординга: сначала ценность, потом вопросы

**Проблема.** Диалог первого запуска (`home_hub.py:60`) спрашивает цель и время до
первого ответа и отправляет в «Чат с тьютором» (`home_hub.py:100`) — самый тяжёлый
режим, который при пустом индексе/выключенном LLM падает.

### W3.1 Сократить диалог

В `_render_onboarding`:

- Оставить: приветствие, чекбокс «Запустить интерактивный тур», выбор режима
  интерфейса (3 варианта из Фазы 1, см. `docs/ui_visibility_phase1_plan.md` §4.8:
  «Начинаю с нуля» → `"1"`, «Учусь регулярно» → `"2"`, «Показать всё» → `"all"`).
- Убрать: селект цели и слайдер времени (переезжают в W3.2).
- Кнопка «Начать»: `set_kv("onboarding_v1_done", "1")`,
  `current_view = HOME_VIEW` (Mission Control, НЕ тьютор): там пользователя
  встретит предполётный чек (W2) + либо три двери (W1, пустой индекс), либо
  seed-вопросы (W4, индекс есть).
- `track_event("onboarding_completed", {...})` сохранить (поле `goal` убрать из
  payload или слать `goal: null` — проверить потребителей события grep'ом по
  `onboarding_completed`; на 2026-07-03 потребителей в `app/` нет, событие только
  пишется).

### W3.2 Вопрос о цели — после первого ответа

Новая функция `render_post_first_answer_goal_prompt()` (можно в `home_hub.py`
рядом со старым кодом, чтобы переиспользовать `goal_map`):

- Место вызова: `query_tab_answer_section.py`, после блока рендера успешного
  ответа (рядом с `render_debug_summary`, строка ~302).
- Условие: есть `st.session_state["last_answer"]` и
  `get_kv("goal_prompt_done") != "1"`.
- Вид: свёрнутый expander «🎯 Подстроить объяснения под вас? (30 секунд)» —
  внутри тот же селект цели + слайдер времени + кнопка «Сохранить». Обработчик —
  копия прежней логики: `goal_map` → session-ключи `learning_goal`,
  `tutor_answer_depth`, `estimated_minutes`, `set_preferred_style("balanced")`,
  `_persist_tutor_goal_snapshot_from_session()`, затем
  `set_kv("goal_prompt_done", "1")`.
- Кнопка «Не сейчас» тоже ставит `goal_prompt_done="1"` (не преследовать).

### W3.3 Тесты

- После онбординга `current_view == HOME_VIEW` (не «Чат с тьютором»).
- `goal_prompt` пишет те же session-ключи, что писал старый онбординг
  (snapshot-совместимость: `learning_goal`, `tutor_answer_depth`,
  `estimated_minutes`).
- Прежний тест онбординга (если есть — найти grep'ом `onboarding` в `tests/`)
  обновить осознанно, не удалять.

**DoD W3:** новый пользователь не отвечает ни на один вопрос анкеты до получения
первого ответа; предложение настройки появляется ровно один раз после первого
успешного ответа и исчезает навсегда по любому из двух исходов.

---

## W4. Стартовые вопросы: пустого поля больше нет

**Проблема.** Первый экран «Быстрого ответа» — пустой textbox; новичок не знает,
что спросить. Готовые вопросы есть только в course-scoped артефакте первой сессии.
`/kb/suggestions` не подходит (требует `question` — это follow-up механизм).

### W4.1 Модуль `app/ui/seed_questions.py`

```python
def build_seed_questions(index_stats, topics_catalog, first_session_artifact) -> list[dict]:
    # -> [{"q": str, "source_label": str}] , максимум 3, детерминированно, БЕЗ LLM.
    # Приоритет источников:
    # 1) first_session_artifact["seed_questions"] (если передан и непуст) —
    #    формат см. app/ui/mission_control_first_session.py:175-193;
    # 2) topics_catalog["topics"][*]["topic_name"] — шаблоны по образцу
    #    _DEFAULT_SEED_TEMPLATES (first_session_builder.py:20):
    #    «Что такое {topic} — коротко и с источниками?»,
    #    «С чего начать изучение темы «{topic}»?»,
    #    «Какие ключевые идеи в теме «{topic}»?» — по одной на первые 3 темы;
    # 3) fallback: index_stats["files"][:3] → «О чём файл {basename}?».
    # Пустой индекс -> [].

def render_seed_question_chips(*, key_prefix: str, navigate_to_question) -> None:
    # До 3 кнопок-чипов (st.button type="secondary") + caption источника.
    # Клик -> navigate_to_question(q).
```

`navigate_to_question` — существующий колбэк `_prefill_and_navigate_to_quick_answer`
(mission_control.py:540); внутри «Быстрого ответа» — локальный сеттер
`st.session_state["question_draft"] = q` + `st.rerun()`.

### W4.2 Интеграция

- Mission Control: под first-session hero (для «тёплого» и «холодного»
  пользователя одинаково), но только если первосессионный блок курса **реально
  отрисовал свои кликабельные seed-вопросы**. Не полагаться только на
  `first_session_load_status == "ok"`: при `empty/error` hero уже рисует
  placeholder/сообщение, но стартовых кнопок нет. Практичная правка:
  `render_first_session_hero(...) -> bool`, где True означает «были отрисованы
  seed-вопросы/CTA», и W4 показывает fallback-чипы только при False.
- «Быстрый ответ»: в пустом состоянии (нет `last_answer` и пустой
  `question_draft`) — над полем ввода, заголовок «Попробуйте спросить:».
- `track_event("seed_question_clicked", {"rank": i})`.

### W4.3 Тесты

Чистые тесты `build_seed_questions`: приоритет артефакт > темы > файлы;
максимум 3; пустой индекс → `[]`; кириллические имена файлов не ломают basename
(Windows-пути с `\`).

**DoD W4:** сразу после индексации (в т.ч. демо из W1) и Mission Control, и пустой
«Быстрый ответ» показывают 3 кликабельных вопроса; один клик = заданный вопрос.

---

## W5. Снижение перегруза навигации (Фаза 1 уже в коде)

Основная работа описана в `docs/ui_visibility_phase1_plan.md` (уровни интерфейса,
реестр фич, панель управления). В текущем коде Фаза 1 уже частично/полностью
влита: `ALL_VIEWS` импортируется из `app/ui/constants.py`, `get_ui_level()` уже
используется в `main.py`. Поэтому W5 не откладывать «до Фазы 1», а реализовывать
как обычную маленькую правку навигационных подписей.

Единственное дополнение из этого плана: **глагольные ярлыки для уровня 1**.
В `main.py` есть словарь подписей `_view_nav_labels` (около строки 209). Добавить
словарь `BEGINNER_VIEW_LABELS_RU` (использовать, когда `get_ui_level() == "1"`):

| view | ярлык уровня 1 |
|---|---|
| Mission Control | «Главная» |
| Быстрый ответ | «Спросить по материалам» |
| Найти материалы | «Найти в материалах» |
| Объяснить файл | «Объяснить файл» |

Применять beginner-labels в `format_func` selectbox и в кнопках expander
«Ещё разделы», только для уровня `"1"`. Для уровней `"2".."5"` и `"all"` оставить
текущие `_view_nav_labels`, чтобы существующие пользователи не получили
неожиданное переименование.

---

## 3. Порядок и зависимости

```
W2 (предполётный чек)  ──┐
W1 (демо + загрузка)   ──┼── W3 (инверсия онбординга: маршрут зависит от W1/W2)
W4 (seed-вопросы)      ──┘
W5 — независимо; Фаза 1 уже доступна в текущем коде
```

Рекомендуемая последовательность коммитов: W2 → W1 → W4 → W3 → W5.
W2 первым: он разграничивает «API недоступен» и «индекс пуст» — W1 опирается на
это различие.

## 4. Известные ловушки

- **`reset=True` в `/reindex` перестраивает весь индекс** — для установки демо и
  загрузок использовать только `reset=False` (частичная переиндексация).
  `reset=True` нужен только после удаления демо, когда поддерживаемых файлов не
  осталось: это должен быть явный путь «очистить активный индекс до empty».
- **Кэш bootstrap живёт 300 с** (`ui_client.py`) — после любой переиндексации
  обязательно `clear_ui_api_caches()`, иначе hero пустого индекса не исчезнет.
  Но чистить кэши нужно только после `/reindex/status == completed`, не сразу
  после `POST /reindex`, иначе UI может закэшировать старое/пустое состояние.
- **Поллинг reindex сейчас не глобальный** — существующий
  `poll_reindex_status_for_query_tab()` вызывается только в Quick Answer. Для W1
  нужен общий poller, который работает на Mission Control.
- **`/health/deep` делает реальный вызов LLM** (1 токен, таймаут 2 с) — не звать
  чаще, чем ttl кэша; не звать в цикле поллинга.
- **Streamlit rerun и file_uploader**: после успешной обработки загрузки очищать
  виджет через смену `key` (счётчик в session_state), иначе файлы обработаются
  повторно при следующем rerun.
- **Онбординг-диалог рисуется до `load_ui_bootstrap()`** (main.py:97–103) — внутри
  диалога не обращаться к index_stats/topics.
- **Windows-пути**: в `demo_sandbox` использовать `Path`, сравнение потомков —
  `Path.resolve()` + `is_relative_to` (Python 3.9+); не сравнивать строки.
- **HF Spaces (эфемерный диск)**: демо-песочница там особенно полезна, но
  `data/` не переживает рестарт — это ожидаемо (см. README, ограничение тарифа).
- **Не показывать W1-hero и W2-warning одновременно с онбордингом** — диалог
  модальный, hero рисовать в обычном потоке страницы.

## 5. Вне скоупа этого документа

Изменение RAG-профилей, `/ui/bootstrap`, новые HTTP-эндпоинты, серверная генерация
seed-вопросов через LLM, переработка туториала, nudge-механика уровней (Фаза 2
документа про уровни). Небольшая правка существующего `/reindex?reset=true` для
пустого `DATA_DIR` входит в W1.4 и не считается новым endpoint.

## 6. Сводный Definition of Done

- [ ] Пустая установка → три двери; путь «демо» даёт первый ответ без терминала.
- [ ] Выключенный LLM виден до ввода вопроса; включённый — тихая зелёная строка.
- [ ] Онбординг не задаёт вопросов до первой ценности; анкета цели — после
      первого ответа, один раз.
- [ ] Пустое поле вопроса всегда сопровождается тремя кликабельными вопросами.
- [ ] Все новые тексты — по-русски, без сырых traceback; каждое новое состояние
      имеет кнопку действия.
- [ ] `ruff check app tests` и `pytest tests -q` зелёные; `docs/user_guide.md`
      дополнен разделом «Первый запуск».
