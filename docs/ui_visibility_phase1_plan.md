# Фаза 1: «Растущий интерфейс» — единая модель видимости UI

Статус: ТЗ к реализации (handoff-документ, самодостаточный).
Подготовлено: 2026-07-03. Прошло аудит; продуктовые инварианты ниже — обязательные.

## 1. Контекст проекта (минимум, чтобы не читать весь репозиторий)

`hometutor` — локальный учебный RAG-сервис: FastAPI (`app/routers/*`, сборка в
`app/api.py`) + Streamlit multipage UI (`app/ui/*`, entry point `app/ui/main.py`) +
Chroma/BM25 + SQLite user-state (`app/user_state*.py`). Язык UI — русский.
Конвенции: `docs/conventions.md` (KISS; конфиг только через `get_settings()`;
persistence только через `app/user_state*.py`, SQLite напрямую из UI не открывать;
бизнес-логику во view-коде не дублировать).

Проверка перед сдачей:

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

### Как устроена навигация UI сейчас

- `app/ui/main.py` — тонкий роутер. Жёсткий список из 16 разделов
  `view_options` (main.py:133–150), selectbox с ключом `current_view`
  (main.py:265), диспетчеризация if/elif (main.py:282+).
- Deep-links / e2e / отложенная навигация валидируются **по `view_options`**:
  - main.py:243 — сброс невалидного `current_view` на первый элемент;
  - main.py:247–249 — `e2e_view` query param через `_e2e_view_map`;
  - main.py:256–262 — `PENDING_CURRENT_VIEW_KEY` (навигация с Mission Control / SSR).
- `HOME_VIEW = "Mission Control"` — константа в `app/ui/breadcrumb.py:8`.
- Mission Control (`app/ui/mission_control.py`): плитки `_tile_definitions()`
  (7 плиток, строка ~258), `MORE_TOOLS` (6 инструментов, строка 47),
  **уже существующий** progressive-disclosure слой для «холодного» пользователя:
  `_COLD_USER_TILE_IDS` (строка 120, ровно 3 плитки: quick_question, tutor, quiz)
  и `_is_cold_user()` (строка 146). Покрыт тестами
  `tests/test_mission_control_progressive.py` — **их поведение менять нельзя**.
- Сайдбар (`app/ui/sidebar.py::render_sidebar`, строка 342): live-метрики,
  кнопки навигации на страницы, геймификация, активный курс, backup/QR-sync
  (`_render_sidebar_backup_restore_panel`, строка 223), секции «База знаний» и
  «Инструменты» (`_render_mission_control_sidebar_sections`, строка 322),
  свёрнутый expert-блок с голосом и фильтрами Q&A (строка 441+), заметки,
  research-сессии, reading/focus toggles.
- Expert-слои: `app/ui/expert_controls.py::render_expert_controls` — вызывается из
  `adaptive_daily_plan_layout.py:185`, `flashcards_review_view.py:207`,
  `interactive_quiz.py:356`, `tutor_chat_footer.py:143`.
  Debug-панель: `app/ui/debug_panel.py::render_debug_summary` — вызывается из
  `query_tab_answer_section.py:302`.
- Отдельные страницы: `app/ui/pages/3_Мой_прогресс.py`, `app/ui/pages/4_Аналитика.py`,
  `app/ui/pages/feedback_insights.py` (переходы через `st.switch_page` из сайдбара).

### Persistence (проверенные факты)

- KV-хранилище: `app/user_state_core.py::get_kv(key, default)` (строка 403) и
  `set_kv(key, value)` (строка 420) поверх таблицы `app_kv` в `data/user_state.db`.
  Импортируются как `from app.user_state import get_kv, set_kv` (или `from app import
  user_state; user_state.get_kv(...)` — оба паттерна уже встречаются в коде).
- **Таблица `app_kv` уже входит в sync-bundle**: объявлена в
  `_SYNC_TABLE_COLUMNS` (`app/user_state_db.py:195`), экспортируется
  `export_full_sync_bundle()` (`app/user_state_sync.py:16`). Значит настройки,
  сохранённые через `set_kv`, автоматически переезжают через backup/QR/restore.
  Отдельная работа по синхронизации не нужна — только тест-фиксация.
- Признак существующего пользователя: `get_kv("onboarding_v1_done") == "1"`
  (ставится в `app/ui/home_hub.py:99`, проверяется в `main.py:99`).
- При `AUTH_ENABLED=true` user_state изолирован по пользователю автоматически
  (contextvar в `app/auth_context.py`) — код фазы 1 об этом знать не должен.

## 2. Цель фазы 1

Ввести единую модель видимости UI на 5 уровней опыта, чтобы новичок видел
простой интерфейс, а эксперт — всё, без потери доступа к чему-либо.

Уровни: 1 Начальный · 2 Основной · 3 Продвинутый · 4 Профи · 5 Эксперт.

## 3. Продуктовые инварианты (результат аудита — нарушать нельзя)

1. **Существующие пользователи не теряют ни одного пикселя.** Миграционный
   дефолт для пользователя с `onboarding_v1_done == "1"` (или любой активностью) —
   специальный уровень `"all"`, эквивалент «всё включено». Снижение шума —
   только добровольное действие в панели.
2. **Скрытое ≠ недоступное.** Deep-links (`e2e_view`), pending-навигация и
   `st.switch_page` обязаны открывать разделы, скрытые уровнем. Для этого
   валидация навигации остаётся по полному списку `ALL_VIEWS`, а фильтруется
   только состав selectbox.
3. **Cold-user слой Mission Control не заменяется.** Tier-gating — второй,
   независимый слой: `visible = allowed_by_level AND allowed_by_context`.
   Тесты `tests/test_mission_control_progressive.py` должны остаться зелёными
   без правок.
4. **RAG-профили (`fast`/`quality`/`graph_aware`) не трогаем.** Никаких
   автоматических подмен качества ответа по уровню.
5. **`/ui/bootstrap` и HTTP API не трогаем.** Preferences читаются в Streamlit
   напрямую из `user_state` (после `require_ui_auth_or_stop()` в main.py:86).
6. **Реестр фич — аддитивный.** Существующие списки (`view_options`,
   `MORE_TOOLS`, `_tile_definitions`) не удаляются; реестр описывает видимость
   поверх них. Никаких больших рефакторингов диспетчеризации.
7. **Панель — не вторая админка.** Слой 1: выбор пресета (карточки уровней).
   Слой 2: свёрнутый expander «Тонкая настройка» с человеческими подписями
   (не «session tape», а «Диагностика сессий для отладки»).

## 4. Архитектура

### 4.1 Новый модуль `app/ui/feature_registry.py`

```python
"""Реестр фич UI: уровни опыта и правила видимости (аддитивный слой)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

@dataclass(frozen=True)
class FeatureSpec:
    id: str                    # "view:<slug>" | "panel:<slug>" | "sidebar:<slug>"
    title_ru: str              # человеческая подпись для панели управления
    tier: int                  # 1..5
    surface: str               # "nav" | "tile" | "sidebar" | "panel" | "page"
    view_name: str | None = None      # для surface="nav": точное имя из view_options
    requires: tuple[str, ...] = ()    # контекстные требования, см. 4.3
    fallback_hint_ru: str | None = None
    group_ru: str = "Разделы"         # группировка в панели управления

FEATURES: Final[tuple[FeatureSpec, ...]] = (...)   # полный список в §5

def feature_by_id(feature_id: str) -> FeatureSpec | None: ...
def features_for_surface(surface: str) -> tuple[FeatureSpec, ...]: ...
```

Требования: id уникальны; для каждого `surface="nav"` заполнен `view_name`,
и он существует в `ALL_VIEWS`; tier в диапазоне 1..5. Всё это фиксируется тестами.

### 4.2 Новый модуль `app/ui_preferences.py` (вне `app/ui/` — переиспользуем из тестов без Streamlit)

```python
"""Пользовательские настройки видимости UI поверх user_state KV (app_kv)."""
from __future__ import annotations

import json
from app.user_state import get_kv, set_kv

UI_LEVEL_KEY = "ui_level"                    # "1".."5" | "all"
UI_OVERRIDES_KEY = "ui_feature_overrides"    # JSON: {feature_id: bool}
LEVEL_ALL = "all"

def get_ui_level() -> str: ...
    # Нет ключа? Миграция: onboarding_v1_done == "1" -> LEVEL_ALL (и сохранить),
    # иначе -> "1" (новый пользователь; сохранять не обязательно до онбординга).
def set_ui_level(level: str) -> None: ...
    # Валидация: level in {"1","2","3","4","5", LEVEL_ALL}. Смена уровня сбрасывает overrides.
def get_overrides() -> dict[str, bool]: ...
def set_override(feature_id: str, enabled: bool) -> None: ...
def clear_overrides() -> None: ...
```

Все чтения KV оборачивать в try/except с деградацией к дефолту (паттерн проекта:
UI не падает из-за SQLite; см. `main.py:98–102`).

### 4.3 Visibility policy — там же, в `app/ui_preferences.py` (чистая функция) + контекст-чекеры в `app/ui/feature_registry.py`

```python
def level_allows(spec_tier: int, level: str) -> bool:
    return level == LEVEL_ALL or spec_tier <= int(level)

def feature_visible(spec, *, level: str, overrides: dict[str, bool],
                    context_ok: bool = True) -> bool:
    if spec.id in overrides:
        return overrides[spec.id] and context_ok
    return level_allows(spec.tier, level) and context_ok
```

Контекстные требования (`requires`) — маленькие чекеры в `feature_registry.py`,
переиспользующие существующие проверки (не дублировать логику):

| requires-ключ | Как проверять (уже есть в коде) |
|---|---|
| `active_course` | `app/ui/study_scope.py::get_active_scope()` не None |
| `has_debug_payload` | `st.session_state.get("last_debug")` непусто (проверяется на call-site, как сейчас) |
| `auth_enabled` | `get_settings().auth_enabled` |

Cold-user слой Mission Control остаётся отдельной, уже существующей проверкой —
он **не** переносится в registry (инвариант 3).

### 4.4 Панель управления `app/ui/control_panel.py`

- Точка входа: кнопка «⚙️ Настроить интерфейс» в сайдбаре (рядом с
  reading/focus toggles, `sidebar.py` около строки 492) + такая же на
  Mission Control в блоке инструментов.
- Реализация: `@st.dialog("Панель управления")` (паттерн уже есть:
  `main.py:93` `_render_onboarding_dialog`).
- Слой 1: 5 карточек уровней + карточка «Всё включено» (уровень `all`).
  Каждая: название + 3–5 слов описания. Клик → `set_ui_level(...)`,
  `clear_overrides()`, `st.rerun()`. Смена уровня при непустых overrides —
  через подтверждающий checkbox («сбросить точечные настройки»).
- Слой 2: `st.expander("Тонкая настройка", expanded=False)` — тумблеры
  `st.toggle` по группам (`group_ru`), подпись = `title_ru`, справа бейдж
  уровня. Тоггл пишет `set_override(...)`. Кнопка «Сбросить к пресету» →
  `clear_overrides()`.
- Подпись внизу: «Настройки хранятся локально в вашем профиле и попадают в backup».

### 4.5 Интеграция в `app/ui/main.py`

Минимальный диф:

1. Переименовать текущий список в `ALL_VIEWS` (содержимое не менять).
2. Вся существующая валидация (main.py:243, 247–249, 256–262) — по `ALL_VIEWS`.
3. Построить `visible_nav_views`:

```python
_level = get_ui_level()
_overrides = get_overrides()
_hidden = {
    spec.view_name
    for spec in features_for_surface("nav")
    if spec.view_name and not feature_visible(spec, level=_level, overrides=_overrides)
}
visible_nav_views = [v for v in ALL_VIEWS if v not in _hidden]
_current = st.session_state.get("current_view")
if _current in ALL_VIEWS and _current not in visible_nav_views:
    visible_nav_views.append(_current)   # deep-link в скрытый раздел: он в селекторе, пока активен
```

4. `st.selectbox("Раздел", visible_nav_views, ...)` вместо `view_options`.
5. `HOME_VIEW` и «Быстрый ответ» не могут быть скрыты (tier 1, в реестре).
6. Пункт «Ещё…»: если `_hidden` непусто — под селектором `st.expander("Ещё разделы")`
   с кнопками, которые ставят `PENDING_CURRENT_VIEW_KEY` (существующий механизм,
   `app/ui/session_state.py`) и `st.rerun()`. Плюс кнопка «Настроить интерфейс».

Осторожно: `visible_nav_views.append(_current)` добавляет текущий скрытый вид в
конец списка — selectbox с `key="current_view"` подхватит его корректно, т.к.
значение присутствует в options. Не менять порядок первых элементов (e2e
стабильность).

### 4.6 Интеграция в `app/ui/sidebar.py`

Гейтим целые секции (не отдельные виджеты) через `feature_visible`:

| Секция (текущий код) | feature id |
|---|---|
| «Синхронизация и перенос» expander (строка 408) | `sidebar:sync_backup` |
| Expert-блок с голосом/фильтрами Q&A (строка 441) | `sidebar:expert_filters` |
| «Голос» вложенный expander (строка 443) | `panel:voice` |
| «Исследования» (строка 147) | `sidebar:research_sessions` |
| «Актуальность индекса (freshness)» (строка 423) | `panel:index_freshness` |
| Кнопка «Аналитика» → страница (строка 363) | `page:analytics` |

Важно: `render_sidebar` возвращает кортеж фильтров
`(folder, folder_rel, file_name, relative_path, topic_quick, folder_quick)`.
При скрытом expert-блоке возвращать дефолты, которые уже инициализированы
(строки 435–440) — сигнатуру и контракт не менять.

### 4.7 Интеграция в Mission Control и expert/debug-слои

- `_render_tile_grid` (mission_control.py:391): после существующей cold-логики
  добавить фильтр `tiles = [t for t in tiles if tile_feature_visible(t.tile_id, ...)]`.
  Cold-ветка (строки 399–406) остаётся первой и нетронутой.
- `MORE_TOOLS` в сайдбаре/инструментах: фильтровать по `feature_visible`
  (ids вида `view:knowledge_graph` и т.п.).
- `render_expert_controls` (expert_controls.py:36): в начале функции —
  `if not feature_visible_by_id("panel:expert_controls"): return`. Один гейт
  закрывает все 4 call-site.
- `render_debug_summary` (debug_panel.py:119): аналогично,
  `panel:debug_summary`. Контекст `has_debug_payload` уже проверяется на
  call-site (query_tab_answer_section.py:302 передаёт `last_debug or {}` —
  внутри есть ранний `if not debug: return`, не дублировать).

### 4.8 Онбординг (`app/ui/home_hub.py::_render_onboarding`, строка 60)

Добавить шаг выбора режима — **3 варианта, не 5** (инвариант 7):

- «Начинаю с нуля» → уровень `"1"`;
- «Учусь регулярно» → уровень `"2"`;
- «Показать всё» → уровень `"all"`.

`st.radio` перед кнопкой «Начать обучение»; в обработчике кнопки —
`set_ui_level(...)` рядом с `set_kv("onboarding_v1_done", "1")` (строка 99).
Дефолт radio — «Учусь регулярно».

## 5. Полный реестр фич фазы 1

`surface="nav"` — скрывает раздел из selectbox. `view_name` — точная строка из `ALL_VIEWS`.

| id | title_ru | tier | surface | view_name / привязка | requires |
|---|---|---|---|---|---|
| `view:mission_control` | Главная — Mission Control | 1 | nav | `Mission Control` (HOME_VIEW) | — |
| `view:quick_answer` | Быстрый ответ с источниками | 1 | nav | `Быстрый ответ` | — |
| `view:search` | Поиск по материалам | 1 | nav | `Найти материалы` | — |
| `view:explain_file` | Объяснить файл | 1 | nav | `Объяснить файл` | — |
| `view:tutor` | Чат с тьютором | 2 | nav | `Чат с тьютором` | — |
| `view:quiz` | Интерактивный Quiz | 2 | nav | `Интерактивный Quiz` | — |
| `view:flashcards` | Flashcards и повторения | 2 | nav | `Flashcards` | — |
| `view:progress` | Прогресс обучения | 2 | nav | `Прогресс обучения` | — |
| `view:topics` | Темы и каталог | 2 | nav | `Темы` | — |
| `view:course` | Курс и Course Cockpit | 3 | nav | `Курс` | `active_course` (fallback-подсказка уже есть в main.py:307) |
| `view:adaptive_plan` | Адаптивный план | 3 | nav | `Адаптивный план` | — |
| `view:knowledge_graph` | Knowledge Graph | 3 | nav | `Knowledge Graph` | — |
| `view:living_konspekt` | Живой конспект | 3 | nav | `Живой конспект` | — |
| `view:history` | История запросов | 3 | nav | `История` | — |
| `view:metrics` | Метрики качества и стоимости | 4 | nav | `Метрики` | — |
| `view:print` | Чистый вид (печать) | 4 | nav | `Чистый вид` | — |
| `page:analytics` | Страница «Аналитика» | 4 | page | кнопка sidebar.py:363 | — |
| `sidebar:sync_backup` | Backup, QR-перенос и восстановление | 4 | sidebar | sidebar.py:408 | — |
| `sidebar:expert_filters` | Фильтры области поиска Q&A | 4 | sidebar | sidebar.py:441 | — |
| `panel:voice` | Голосовой ввод и озвучка | 4 | panel | sidebar.py:443 | — |
| `sidebar:research_sessions` | Research-сессии | 3 | sidebar | sidebar.py:147 | — |
| `panel:expert_controls` | Экспертные панели в учебных режимах | 5 | panel | expert_controls.py:36 | — |
| `panel:debug_summary` | Debug: маршрутизация, trace, стоимость | 5 | panel | debug_panel.py:119 | `has_debug_payload` |
| `panel:index_freshness` | Версия и поколение индекса | 5 | panel | sidebar.py:423 | — |

Плитки Mission Control мапятся на те же `view:*` ids по `target_view`
(таблица соответствия tile_id → view уже есть: `HINT_TO_TILE`,
mission_control.py:35, и `MissionTile.target_view`).

Не гейтим в фазе 1 (осознанно): геймификацию, SSR-баннер, заметки,
reading/focus toggles, live-метрики сайдбара, страницу «Мой прогресс» —
это ядро опыта уровня 2, а для уровня 1 они либо безвредны, либо уже
скрываются cold-логикой.

## 6. Пошаговый план работ

Каждый шаг — отдельный коммит, после каждого `ruff` + `pytest` зелёные.

1. **`app/ui/feature_registry.py`** + `tests/test_feature_registry.py`
   (уникальность id, валидность tier/surface, все `view_name` ∈ ALL_VIEWS —
   для этого экспортировать `ALL_VIEWS` из main.py нельзя, он исполняется при
   импорте; вместо этого объявить `ALL_VIEWS` константой в
   `app/ui/constants.py` и импортировать в main.py и в реестр).
2. **`app/ui_preferences.py`** + `tests/test_ui_preferences.py`
   (миграция existing→`all` / new→`1`, level_allows, overrides, сброс при смене
   уровня; KV-функции мокать или использовать tmp user_state — в тестах проекта
   уже есть паттерны работы с user_state, см. соседние тесты `tests/test_*state*`).
3. **`ALL_VIEWS` в `app/ui/constants.py` + правки `main.py`** (§4.5):
   переименование, `visible_nav_views`, «Ещё…». Тест: скрытый view открывается
   через `PENDING_CURRENT_VIEW_KEY` и через `e2e_view` (см. существующие e2e-паттерны;
   как минимум — юнит-тест построения `visible_nav_views` с current в hidden).
4. **Гейты сайдбара** (§4.6). Проверить вручную: уровень 1 → сайдбар без
   sync/expert/freshness; уровень `all` → сайдбар идентичен текущему.
5. **Гейты Mission Control + expert/debug** (§4.7). Тесты: cold-user тесты
   зелёные без правок; на уровне `all` набор плиток идентичен текущему.
6. **`app/ui/control_panel.py`** (§4.4) + кнопки вызова в сайдбаре и на
   Mission Control.
7. **Онбординг** (§4.8) + тест: выбор «Начинаю с нуля» пишет `ui_level="1"`.
8. **Sync-фиксация**: тест, что `ui_level`/`ui_feature_overrides`, записанные
   через `set_kv`, присутствуют в `export_full_sync_bundle()["tables"]["app_kv"]`
   и переживают `import_full_sync_bundle`.
9. **Документация**: обновить `docs/user_guide.md` (раздел «Панель управления и
   уровни интерфейса») и `docs/index.md` при необходимости — конвенция проекта
   требует обновлять docs при изменении runtime-поведения.

## 7. Definition of Done

- [ ] Новый пользователь после онбординга «Начинаю с нуля» видит в селекторе
      только: Mission Control, Быстрый ответ, Найти материалы, Объяснить файл + «Ещё…».
- [ ] Пользователь с `onboarding_v1_done=="1"` и без `ui_level` видит UI,
      побайтово идентичный текущему (уровень `all`).
- [ ] `?e2e_view=metrics` открывает «Метрики» на уровне 1; раздел появляется в
      селекторе, пока активен.
- [ ] `tests/test_mission_control_progressive.py` зелёный без изменений.
- [ ] Смена уровня в панели мгновенно (один rerun) меняет селектор, сайдбар и плитки.
- [ ] Тумблер в «Тонкой настройке» включает одну фичу поверх пресета; «Сбросить
      к пресету» возвращает дефолты.
- [ ] `ui_level` и overrides переживают экспорт/импорт sync-bundle.
- [ ] `ruff check app tests` и `pytest tests -q` зелёные.
- [ ] RAG-профили, `/ui/bootstrap`, HTTP API, cold-user логика — без изменений (diff-проверка).

## 8. Известные ловушки

- **Streamlit rerun и `key="current_view"`**: selectbox упадёт, если значение
  session_state отсутствует в options — потому текущий скрытый вид всегда
  добавляется в options (§4.5, шаг 3).
- **Порядок инициализации в main.py**: `get_ui_level()` можно звать только после
  `require_ui_auth_or_stop()` (main.py:86) — до этого user_state может указывать
  не на того пользователя.
- **Импорты Streamlit в тестах**: `app/ui/feature_registry.py` и
  `app/ui_preferences.py` не должны импортировать `streamlit` на уровне модуля,
  чтобы тесты не тянули UI-runtime (паттерн: ленивые импорты внутри функций,
  как в остальном коде проекта).
- **`view_options` упоминается в e2e-хелперах** — искать по репозиторию
  `view_options` перед переименованием и обновить все точки.
- **Не удалять `_view_nav_labels`** (main.py:225) — просто применять к
  отфильтрованному списку.
- **Onboarding-диалог показывается до сайдбара** (main.py:93–102) — выбор уровня
  в онбординге не должен требовать данных, которых ещё нет (использовать только KV).

## 9. Вне фазы 1 (не делать)

Nudge-механика (XP/туториал/поведение), `GET/PUT /ui/preferences`,
плотность интерфейса, пер-уровневые дефолты RAG-профиля, изменение
`/ui/bootstrap`, замена диспетчеризации if/elif на registry-driven рендер.
