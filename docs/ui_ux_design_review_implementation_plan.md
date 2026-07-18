# План реализации системного UI/UX-ревью

**Статус runtime (этот репозиторий):** **W1–W9 implemented** (2026-07-18);
**W10 (release gates / visual regression) — pending**.

Исходный продуктовый статус документа: кандидат-программа к утверждению
владельцем. Studio-канбан (`hometutor-studio`) может отставать; ниже — факт
runtime-кода и targeted tests в `hometutor`.

Подготовлено: 2026-07-18.  
Актуализация runtime-статусов: 2026-07-18 (после W1–W9 + residual fixes).

Источник решений: [ui_ux_design_review_2026-07-18.md](ui_ux_design_review_2026-07-18.md).

## 1. Цель

Поднять цельность продукта с baseline 6,1/10 до уровня 8+, не добавляя новый
крупный feature layer. Работа сосредоточена на assessment integrity,
accessibility, hierarchy, navigation и общей semantic design system.

План намеренно разбит на маленькие проверяемые волны. Каждая волна имеет
отдельный write-set, targeted tests и визуальный Definition of Done. Волны не
объединяются в один большой UI rewrite.

## 2. Продуктовые инварианты

1. **Mission Control остаётся home.** Мнемополис — ceremonial hub и пространственная
   проекция знания, но не новый default home.
2. **Честная проекция данных.** Fog, dawn, lantern, rift, mastery, due и address
   показываются только при наличии соответствующего runtime-сигнала.
3. **Одна главная следующая остановка.** На каждой учебной поверхности есть один
   dominant next action и объяснение причины.
4. **Local-first не ослабляется.** UI не добавляет обязательную облачную
   зависимость.
5. **Скрытое не становится недоступным.** Deep link и Expert mode сохраняют доступ
   к существующим разделам.
6. **Никаких декоративных данных и motion.** Random particles, fake metrics,
   celebration без достижения и animation без функции запрещены.
7. **Persistence только через `app/user_state*.py`.** UI не открывает SQLite.
8. **Config только через `get_settings()` / `get_retrieval_settings()`.**
9. **Новые runtime dependencies не добавляются без отдельного решения.**
10. **Каждая волна соблюдает собственный write-set.** Соседний рефакторинг не
    включается автоматически.

## 2.1 Связанные планы и границы источников истины

Product/backlog-планы ниже находятся в отдельном репозитории `hometutor-studio`;
это не локальные runtime-документы:

| Волна | Связанный studio-план | Источник истины |
|---|---|---|
| W2 Onboarding | `doc/next/first_ten_minutes_onboarding_plan.md` | studio-план задаёт product journey и приоритет; этот документ — runtime write-set, tests и visual gates |
| W5 Мнемополис | `doc/next/knowledge_graph_3d_game_plan.md` и `doc/next/knowledge_graph_3d_reorientation_plan.md` | studio-планы задают world/interaction contract; runtime-код и этот план задают реализуемый handoff |
| W8 Library | `doc/next/mega_bundle_catalog_plan.md` | studio-план задаёт address model и UI direction 3→2→1; этот документ задаёт runtime-интеграцию |

Правило синхронизации: до promotion волны владелец сверяет scope и DoD с
соответствующим studio-планом и отражает работу в studio-канбане. При конфликте
product direction решается в `hometutor-studio`, а технические инварианты —
runtime-кодом и `docs/conventions*.md`; после решения обновляются оба документа.

## 3. Целевые показатели

| Область | Baseline | Целевое состояние |
|---|---|---|
| Quiz integrity | correct answer доступен до submit | answer отсутствует в DOM до submit |
| First-run | blocking tour около 26 минут | activation journey 7–10 минут |
| Primary touch controls | местами 24–36 px | 40 px desktop, 44 px coarse pointer |
| Meaningful text | местами 9,9–11,5 px | минимум 12 px; body 16 px |
| Mnemo first frame | несколько control clusters | один mode cluster и один primary CTA |
| Navigation | один selectbox на 18 views | четыре устойчивых destinations + command access |
| Reader | закрытые expanders | открытый current section + reading rail |
| Library | single-column tiles | 3→2→1 с постоянным address pattern |
| Motion | локальные duration/easing | единые tokens и полный reduced-motion |
| Theme | light shell + отдельный spatial dark | semantic light/spatial-dark; full dark только после W3 decision gate |

## 4. Порядок реализации

```text
P0 integrity
  W1 Quiz ✓ ─────────────┐
  W2 Onboarding ✓ ───────┤
                         v
Design-system foundation W3 ✓
                         |
        ┌────────────────┼────────────────┐
        v                v                v
 W4 Flashcards ✓   W5 Mnemo ✓    W6 Navigation ✓
        |                |                |
        └──────────┬─────┴──────────┬─────┘
                   v                v
          W7 Living Route ✓   W8 Library ✓
                   └────────┬───────┘
                            v
                   W9 Tutor + Plan ✓
                            v
                   W10 Release gates  (pending)
```

W1 и W2 могут выполняться независимо. W3 должен предшествовать массовому visual
polish, чтобы новые поверхности не добавляли четвёртую систему токенов.

### 4.1 Сводка статусов runtime (актуально)

| Волна | Тема | Runtime | Примечание |
|---|---|---|---|
| **W1** | Quiz assessment integrity | **done** | submit-gated; без answer до submit |
| **W2** | First-ten-minutes onboarding | **done** | activation journey; tour не auto |
| **W3** | Semantic tokens + a11y foundation | **done** | full dark: **deferred**; base=light |
| **W4** | Flashcards semantics / iframe sizing | **done** | flip a11y, 44px, ResizeObserver |
| **W5** | Мнемополис editorial + a11y | **done** | utility menu, single announcer |
| **W6** | Global navigation IA | **done** | 4 destinations + «Ещё» |
| **W7** | Living Konspekt reading route | **done** | open section + rail Next=read |
| **W8** | Library address + 3→2→1 | **done** | `source_address.py`, lib-card CSS |
| **W9** | Tutor Chat + Adaptive Plan | **done** | hub/detail split; no JSON depth |
| **W10** | Visual regression / release gates | **pending** | screenshot matrix, full gates |

**Residual fixes (после W7/W8, не отдельные волны):** re-export
`_IMAGE_B64_CACHE` / `_resolve_local_images` из `living_konspekt_reader`;
убраны forest hex fallback’и из W8 CSS вне `:root` (theme_presets contract).

## 5. Волны реализации

### W1 — Quiz assessment integrity

**Приоритет:** P0.

**Статус runtime-плана:** implemented 2026-07-18 in `app/ui/interactive_quiz.py`
(+ `tests/test_interactive_quiz_ui_contract.py`, `docs/user_guide.md`).
Submit-gated feedback; no pre-submit answer expander; RU labels; ordering ↑/↓;
celebration ≥80%; graph update after submitted answers only.

**Цель:** исключить подсматривание ответа и привести основной Quiz к уже
существующему interaction contract `scoped_quiz`.

**Evidence из дизайн-ревью:** основной `interactive_quiz` показывает блок с
правильным ответом до submit через expander (`app/ui/interactive_quiz.py:563-567`),
тогда как `scoped_quiz` уже держит корректную модель question → answer →
feedback (`app/ui/scoped_quiz.py:138-197`). Это не visual polish, а нарушение
assessment integrity: learner может получить правильный ответ до попытки, а
значит прогресс, слабые места и graph/plan signals становятся недостоверными.

**Write-set:**

- `app/ui/interactive_quiz.py`;
- при необходимости общий pure helper в существующем quiz-модуле;
- новый `tests/test_interactive_quiz_ui_contract.py`;
- `docs/user_guide.md` при изменении описанного поведения.

**P0 scope boundary:**

- обязательно: state machine `unanswered | submitted | resolved`;
- обязательно: correct answer, explanation и correctness status отсутствуют в
  DOM/state presentation до submit;
- обязательно: submit-гейт для graph/learner-state update;
- обязательно: keyboard flow выбор → submit → feedback → next;
- обязательно: regression-тест, который падает при pre-submit answer leak;
- вне P0, если мешает быстрому закрытию leak: broader visual refresh, новая
  quiz-навигация, full-dark адаптация, новые scoring модели.

**Работы:**

1. Ввести per-question state `unanswered | submitted | resolved`.
2. Не рендерить correct answer, explanation и correctness status до submit.
3. Заменить raw enums на русские пользовательские labels.
4. `True / False` заменить на `Верно / Неверно`.
5. Ordering представить reorder-контролом; обязательно оставить single-pointer
   альтернативу «вверх/вниз» без drag.
6. Удалить session/debug copy из normal layer.
7. Celebration включать только по задокументированному threshold; при низком
   результате давать спокойный recovery action.
8. После feedback показывать ровно один next action.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_interactive_quiz_ui_contract.py tests/test_living_konspekt_scoped_quiz.py
```

**DoD:**

- correct answer отсутствует в HTML/state presentation до submit;
- keyboard проходит выбор → submit → feedback → next;
- все типы имеют русские labels;
- ordering выполним без dragging;
- результат 0% не вызывает celebration;
- graph update происходит только после зафиксированного ответа.

**Registration note:** если владелец решит синхронизировать уже реализованный
runtime-fix с `hometutor-studio`, регистрировать его не как новый execution
scope, а как backfill/closure package `interactive-quiz-assessment-integrity-v1`
с привязкой к фактическому diff и targeted tests. До такой регистрации
runtime-план остаётся SSoT для scope boundary, DoD и release-validation gate.

### W2 — First-ten-minutes onboarding

**Приоритет:** P0.

**Статус runtime:** implemented 2026-07-18 —
`app/ui/tutorial_activation.py`, hooks in scope/Q&A/quiz/main, persistence
`tutorial_service.save_activation_progress`, tests
`tests/test_tutorial_activation_flow.py`. Full dialog tour remains manual-only.

**Цель:** заменить блокирующую презентацию на выполняемый activation journey.

**Связанный product-план:** `hometutor-studio/doc/next/first_ten_minutes_onboarding_plan.md`.
Перед началом W2 journey и success predicates синхронизируются с ним; новый
параллельный backlog в runtime-документации не создаётся.

**Write-set:**

- `app/ui/tutorial_guide.py`;
- `app/ui/tutorial_chapters.py`;
- минимальные call-sites конкретных checkpoints в `app/ui/main.py`, Mission
  Control, Tutor и Quiz;
- новый `tests/test_tutorial_activation_flow.py`;
- `docs/user_guide.md`, `docs/quickstart.md`.

**Архитектурное решение:**

- `@st.dialog` остаётся только для отдельного справочного путеводителя;
- activation flow выводится inline рядом с реальной поверхностью;
- каждый шаг имеет реальный `checkpoint_id`, `target_view`, success predicate и
  fallback;
- переход шага происходит по факту действия, а не по нажатию «Далее» в слайдах;
- persistence использует существующие `user_state` helpers.

**Activation flow:**

1. `course_confirmed`;
2. `first_question_sent`;
3. `source_opened`;
4. `tutor_handoff_completed`;
5. `micro_quiz_submitted`;
6. `memory_change_seen`;
7. `mission_control_returned`.

**Copy rules:**

- не показывать `US-*`, JSON, SM2 и названия внутренних контрактов;
- одна инструкция, одно действие, одна причина;
- всегда доступны Skip, Back и Exit;
- после Skip функция остаётся доступной из справки.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tutorial_activation_flow.py tests/test_first_run_preflight_seed.py
```

**DoD:**

- шаг не блокирует underlying control;
- все checkpoints ссылаются на существующий view/action;
- прогресс переживает rerun и reload;
- путь можно пройти keyboard-only;
- нормальный путь содержит не более семи шагов и рассчитан на 7–10 минут;
- справочный полный tour не запускается автоматически.

### W3 — Semantic design tokens и accessibility foundation

**Приоритет:** P0/P1 foundation.

**Статус runtime:** implemented 2026-07-18 —
`app/ui/design_tokens.py`, foundation + semantic aliases + a11y rules in
`app/ui_theme.css`, spatial aliases in `kg_3d_template.html`, tests
`test_ui_design_tokens.py` / `test_theme_portals_contract.py`.
**Full dark decision: `deferred`** (Streamlit `base = light` unchanged; portal
spike required before `approved`).

**Цель:** создать одну систему для 2D, spatial и embedded UI до дальнейшего
polish. W3 не является автоматическим разрешением полноценной тёмной темы.

**Decision gate full dark:** `.streamlit/config.toml:1-3` фиксирует прежнее
осознанное решение сохранять `base = "light"`: при dark base порталы Base Web
для selectbox/multiselect получали чёрный фон и расходились с основной темой.
Сначала выполняется ограниченный portal spike. Если gate не пройден, продукт
остаётся в `light` + `spatial-dark`, без изменения Streamlit base.

**Write-set:**

- `app/ui/theme_presets.py`;
- `app/ui_theme.css`;
- при необходимости небольшой pure token helper в `app/ui/`;
- `tests/test_theme_presets.py`;
- новый `tests/test_ui_design_tokens.py`;
- новый `tests/test_theme_portals_contract.py` для статического контракта;
- `.streamlit/config.toml` только после успешного full-dark decision gate;
- `docs/user_guide.md` для пользовательского theme behavior.

**Работы:**

1. Добавить semantic tokens surface/text/border/accent/focus/status.
2. Добавить space, radius, type, control-size, elevation и motion tokens.
3. Определить modes `light` и `spatial-dark`; `dark` остаётся кандидатом до
   успешной проверки Base Web portals.
4. Связать `--kgx-*` с spatial semantic tokens, сохранив характер Mnemo.
5. Исправить известные contrast failures SSR и notebook-derived colors в
   runtime UI.
6. Ввести общий focus ring с достаточным contrast.
7. Добавить coarse-pointer rule на 44 px.
8. Meaningful metadata ограничить минимумом 12 px.
9. Создать scoped reduced-motion contract для transform, rotation, shimmer,
   pulse и z-motion.
10. Проверить selectbox, multiselect, popover, dialog и tooltip в portal-слое:
    background, text, border, focus, disabled и error states.

**Token baseline:**

```css
:root {
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --space-12: 48px;

  --radius-control: 8px;
  --radius-card: 12px;
  --radius-panel: 16px;
  --radius-overlay: 20px;

  --type-meta: 12px;
  --type-label: 13px;
  --type-body: 16px;
  --type-section: 18px;
  --type-title: 24px;

  --control-default: 40px;
  --control-touch: 44px;

  --motion-fast: 120ms;
  --motion-default: 180ms;
  --motion-panel: 240ms;
  --ease-standard: cubic-bezier(.2, .8, .2, 1);
}
```

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_theme_presets.py tests/test_ui_design_tokens.py tests/test_theme_portals_contract.py tests/test_ui_preferences.py tests/test_ui_preferences_sync.py
```

**DoD:**

- новые surface styles не содержат hardcoded brand colors;
- normal text проходит WCAG AA на утверждённых themes;
- focus виден на light/spatial backgrounds и, если gate пройден, на full dark;
- coarse pointer получает 44 px primary controls;
- reduced-motion выключает несущественные animations;
- существующие theme preferences и sync не ломаются;
- selectbox/multiselect/popover/dialog/tooltip portals имеют корректные фон,
  текст и focus на screenshot-проверке;
- `.streamlit/config.toml base` остаётся `light`, пока portal gate не пройден;
- решение `full dark: approved | rejected | deferred` явно записано в итогах W3.

### W4 — Flashcards semantics и embedded sizing

**Приоритет:** P0 accessibility / P1 UX.

**Статус runtime:** implemented 2026-07-18 —
single hub radio nav (duplicate button row removed), semantic flip surface +
aria-live side announce, reduced-motion content swap, ResizeObserver +
`frameElement` height with host `scrolling=True` fallback, rating chips 44 px
with mnemonic-primary / interval-secondary, tests in
`tests/test_flashcards_interactive_card.py` (W4 contract).

**Зависимость:** W3.

**Write-set:**

- `app/ui/flashcards_ui.py`;
- `app/ui/flashcards_interactive_card.py`;
- `app/ui/flashcards_interactive_card_style.py` (CSS template extract for size budget);
- `app/ui/flashcards_interactive_card_script.py` (client JS extract for size budget);
- `app/ui/flashcards_review_view.py`;
- `tests/test_flashcards_interactive_card.py`;
- `tests/test_flashcards_review_keyboard.py`;
- затронутые `tests/test_flashcards_*.py` по фактической области.

**Работы:**

1. Удалить duplicate radio/button navigation.
2. Сделать flip surface semantic button с состоянием стороны.
3. Добавить focus-visible и screen-reader label результата flip.
4. Reduced-motion заменяет 3D rotation на content swap/fade.
5. Высота iframe подтверждается ResizeObserver; внутренний scroll не является
   нормальным состоянием, но сохраняется как safety fallback при ошибке observer
   или недооценке высоты.
6. Rating buttons имеют одинаковую 44 px touch geometry.
7. Interval остаётся вторичной строкой, mnemonic label — первичной.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_flashcards_interactive_card.py tests/test_flashcards_review_keyboard.py tests/test_flashcards_review_undo.py tests/test_flashcards_memory_signals.py
```

**DoD:**

- весь review выполним keyboard-only;
- screen reader различает front/back и current rating;
- нет duplicate navigation;
- normal viewport не показывает inner iframe scrollbar;
- при отказе ResizeObserver или ошибочной оценке высоты rating controls остаются
  достижимыми через `scrolling=True` либо эквивалентный min-height/overflow
  fallback; этот degraded state покрыт тестом;
- memory/retention receipts остаются честными и persistent.

### W5 — Мнемополис: editorial reduction и accessible projection

**Приоритет:** P1, сердце продукта.

**Статус runtime:** implemented 2026-07-18 —
`app/ui/assets/kg_3d_template.html`: first-level Route/Constellation/Memory +
stop dock; utility ⋯ menu for weak/calm/clear presets, calm, photo, help,
replay, depth map, camera; single `#kgx-announcer` + `#kgx-scene-summary`;
W3 type/touch baseline (40/44 px); reduced-motion disables orbit/zoom/z-fly;
fog/dawn/lantern/rift data-binding unchanged. Contract asserts in
`tests/test_knowledge_graph_counters.py`.

**Зависимость:** W3.

**Связанные product-планы:**
`hometutor-studio/doc/next/knowledge_graph_3d_game_plan.md` и
`hometutor-studio/doc/next/knowledge_graph_3d_reorientation_plan.md`.

**Write-set:**

- `app/ui/assets/kg_3d_template.html`;
- `app/ui/assets/kg_3d_component/index.html` только если нужен bridge contract;
- Python builder/call-site только при необходимости нового accessible payload;
- `tests/test_knowledge_graph_d3_section.py`;
- `tests/test_knowledge_graph_counters.py` (W5 chrome contract);
- `tests/test_knowledge_graph_audit.py`;
- `tests/test_mnemo_scene_dsl.py`;
- `tests/test_sidebar_mnemo_polis.py`;
- `docs/user_guide.md`.

**Работы:**

1. Удалить только дублирующие scene presets «Маршрут/Созвездие». Уникальные
   «Слабое», calm и reset сохранить, но перенести в utility menu.
2. На первом уровне оставить Route/Constellation, Memory toggle и current stop.
3. `all`, photo, replay и camera tools перенести в utility menu.
4. Поднять controls/type до W3 baseline.
5. Свести live announcements к одному announcer.
6. Добавить nonvisual scene summary: mode, current stop, visible relations,
   retention и gap reason.
7. Reduced-motion отключает z-camera и spatial rotation.
8. Сохранить data-binding fog/dawn/lantern/rift без декоративных замен.
9. Проверить action delivery и pending/ack states после сокращения chrome.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_graph_d3_section.py tests/test_knowledge_graph_audit.py tests/test_mnemo_scene_dsl.py tests/test_sidebar_mnemo_polis.py
```

**Visual gates:**

- 1366×768: нет horizontal/vertical clipping primary actions;
- 390×844: одна колонка, нет horizontal scroll;
- первый route frame содержит не более восьми canvas labels;
- один mode cluster, один dominant CTA;
- 200% zoom сохраняет route list и действия;
- reduced-motion не двигает камеру по глубине.

### W6 — Global navigation и sidebar information architecture

**Приоритет:** P1.

**Статус runtime:** implemented 2026-07-18 —
`app/ui/global_navigation.py` (4 destinations + leaf map + page titles +
PENDING helper), primary rail in `main.py`, command access expander
«Ещё · все разделы» keeps `key=current_view` selectbox, sidebar
context-first (live metrics only on diagnostic), RU labels «Режим
чтения/фокуса». Tests: `tests/test_global_navigation.py` (+ existing
navigation/mission_control bundles).

**Зависимость:** W3.

**Write-set:**

- `app/ui/constants.py` (ALL_VIEWS unchanged as contract);
- `app/ui/global_navigation.py` (new);
- `app/ui/main.py`;
- `app/ui/sidebar.py`;
- `app/ui/feature_registry.py` (no change required if contract holds);
- `app/ui/navigation_visibility.py` (no change required);
- `tests/test_global_navigation.py`;
- `tests/test_navigation_visibility.py`;
- `tests/test_mission_control_navigation.py`;
- `tests/test_mission_control_progressive.py`;
- `docs/user_guide.md`, `docs/quickstart.md`.

**Информационная архитектура:**

- `Главная` — Mission Control;
- `Учиться` — Tutor, Quiz, Adaptive Plan;
- `Память` — Mnemo, Living Konspekt, Flashcards;
- `Библиотека` — Catalog, search, course material;
- `Ещё` / command access — полный список существующих views.

**Работы:**

1. Сохранить полный `ALL_VIEWS` как routing contract.
2. Primary navigation показывает четыре устойчивых destinations.
3. Текущий leaf view всегда имеет понятный parent и page title.
4. Hidden/expert view остаётся доступен через deep link и `Ещё`.
5. Sidebar содержит только context текущего раздела.
6. Live metrics, index, backup и diagnostics переходят в Expert/Developer layer.
7. Унифицировать pending navigation, sidebar buttons и current view state.
8. Перевести оставшиеся normal labels на русский.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_navigation_visibility.py tests/test_mission_control_navigation.py tests/test_mission_control_progressive.py tests/test_ui_preferences.py tests/test_ui_preferences_sync.py
```

**DoD:**

- новичок видит четыре понятных destinations;
- ни один существующий view не потерян;
- deep links открывают скрытый leaf view;
- Back/Home возвращают предсказуемо;
- sidebar больше не начинается с diagnostics в normal mode;
- mobile navigation доступна одним thumb reach pattern.

### W7 — Living Konspekt как reading route

**Приоритет:** P1.

**Статус runtime:** implemented 2026-07-18 —
`living_konspekt_reader.py` reading route (open current section, rail
current/next/reason, Next=mark-read+advance, 3-state confidence, contextual
thought/question, source metadata disclosure); mermaid/markdown split to
`living_konspekt_reader_markdown.py` (size budget). Tests in
`test_living_konspekt_add_panel_reader.py` (route helpers).

**Зависимости:** W3, желательно W6.

**Write-set:**

- `app/ui/living_konspekt_view.py` (call-site unchanged if DI stable);
- `app/ui/living_konspekt_reader.py`;
- `app/ui/living_konspekt_reader_markdown.py` (extract for size budget);
- только затронутые Living Konspekt helpers;
- `tests/test_living_konspekt_view_smoke.py`;
- `tests/test_living_konspekt_add_panel_reader.py`;
- `tests/test_living_konspekt_workbench.py`;
- `tests/test_living_konspekt_scoped_quiz.py`;
- `docs/user_guide.md`.

**Работы:**

1. Текущий раздел открыт по умолчанию.
2. Добавить reading rail с current/next/reason.
3. Previous/Next управляют маршрутом без ручного поиска следующего expander.
4. Три confidence states объединены в segmented control.
5. «Прочитано» фиксируется через явный Next.
6. «Сохранить мысль» становится contextual action.
7. Secondary metadata переносится в disclosure.
8. На mobile rail превращается в compact sticky progress header.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_living_konspekt_view_smoke.py tests/test_living_konspekt_add_panel_reader.py tests/test_living_konspekt_workbench.py tests/test_living_konspekt_scoped_quiz.py
```

**DoD:**

- пользователь начинает читать без раскрытия expander;
- current и next видны одновременно;
- один Next фиксирует progress и переводит фокус;
- five-column action row отсутствует;
- persistence и source citations не меняют контракт.

### W8 — Library / address system / responsive catalog

**Приоритет:** P1.

**Статус runtime:** implemented 2026-07-18 —
`app/ui/source_address.py` (SourceAddress + card HTML), unified
`_render_unified_card` / `_render_card_grid` in `library_schedule.py`,
3→2→1 CSS in `ui_theme.css`, activate requires confirmation checkbox,
same card model for search filter. Tests: `test_source_address.py`,
`test_library_schedule_ui_contract.py`.

**Зависимость:** W3; общий `SourceAddress` согласован с W5/W7.

**Связанный product-план:**
`hometutor-studio/doc/next/mega_bundle_catalog_plan.md`. Его address model и
direction 3→2→1 не переопределяются в runtime-волне.

**Write-set:**

- `app/ui/library_catalog.py`;
- `app/ui/library_schedule.py`;
- `app/ui/source_address.py` (shared address component);
- `app/ui_theme.css` (lib-card + 3→2→1);
- только read-model helpers при доказанной необходимости;
- `tests/test_library_schedule_read.py`;
- `tests/test_library_catalog_read.py`;
- `tests/test_library_schedule_ui_contract.py`;
- `tests/test_source_address.py`;
- `docs/user_guide.md`.

**Работы:**

1. Одна card model для normal и filtered catalog.
2. Responsive grid 3→2→1.
3. Address расположен раньше status и action.
4. Одна primary action; secondary actions — menu.
5. Удалить inline hardcoded styles и split-markdown panel wrapper.
6. Status всегда имеет icon/text, а не только color.
7. Browse не меняет active course без явного подтверждения.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_library_schedule_read.py tests/test_library_catalog_read.py tests/test_library_schedule_ui_contract.py
```

**Visual gates:**

- 1920/1366: три карточки при достаточной ширине;
- tablet: две;
- 390×844: одна;
- address не обрезается и доступен screen reader;
- search не меняет card anatomy.

### W9 — Tutor Chat и Adaptive Plan polish

**Приоритет:** P1/P2.

**Статус runtime:** implemented 2026-07-18 —
W9a: collapsed intro after first reply, history→input→exports order,
human session titles, depth labels without JSON jargon, tech counters only
on diagnostic, reduced-motion chat fade. W9b: hub/detail surface switch in
`main.py`, preview max 2 cols without XP auto, XP multipliers in expert
disclosure, route because/address on plan blocks. Tests:
`test_tutor_chat_ui_contract.py`, `test_adaptive_plan_ui_contract.py`.

**Зависимости:** W3, W6; общий `SourceAddress` после W8.

#### W9a Tutor Chat

**Write-set:**

- `app/ui/tutor_chat_header.py`;
- `app/ui/tutor_chat_controls.py`;
- `app/ui/tutor_chat_footer.py`;
- `app/ui/tutor_chat_session.py`;
- затронутые tutor tests;
- новый `tests/test_tutor_chat_ui_contract.py`.

**Работы:**

- intro сворачивается после первого ответа;
- history и input предшествуют exports;
- human-readable session titles;
- normal depth labels без JSON terminology;
- technical counters только в Expert layer;
- единый source-address и motion tokens.

#### W9b Adaptive Plan

**Write-set:**

- `app/ui/main.py` только в adaptive branch;
- `app/ui/adaptive_plan_hub_layout.py`;
- `app/ui/adaptive_daily_plan_layout.py`;
- `tests/test_adaptive_plan_progress.py`;
- новый `tests/test_adaptive_plan_ui_contract.py`.

**Работы:**

- hub и daily detail больше не рендерятся последовательно;
- master/detail на desktop, drill-down на mobile;
- preview не строит четыре узкие колонки;
- `XP auto` и multiplier internals уходят в Expert disclosure;
- route blocks используют current/next/reason.

**Targeted tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tutor_chat_handoff_scroll.py tests/test_tutor_save_card.py tests/test_tutor_chat_ui_contract.py tests/test_adaptive_plan_progress.py tests/test_adaptive_plan_ui_contract.py
```

### W10 — Visual regression и release gates

**Приоритет:** обязательное завершение программы.

**Статус runtime:** **pending** — следующая волна после W1–W9. Код волн 1–9
в main tree; полный screenshot/DOM gate по матрице viewport’ов и критическим
сценариям ещё не закрыт как release package.

**Зависимости:** W1–W9 (runtime done).

**Write-set:**

- существующие screenshot/e2e scripts в `scripts/` после отдельной
  инвентаризации;
- `docs/screenshots/final/*` только для реально перегенерированных сценариев;
- UI invariant tests;
- `docs/user_guide.md`, `docs/quickstart.md`, `docs/index.md`.

**Матрица:**

| Viewport | Modes |
|---|---|
| 1366×768 | light, spatial-dark; full dark условно после W3 gate |
| 1440×900 | light; full dark условно после W3 gate |
| 1920×1080 | light; full dark условно после W3 gate |
| 768×1024 | portrait tablet |
| 390×844 | touch/mobile |

Для критических поверхностей дополнительно:

- reduced-motion;
- 200% zoom;
- keyboard-only;
- screen-reader smoke audit;
- empty/loading/error/degraded/offline states.

**Обязательные сценарии:**

1. Mission Control cold/returning;
2. Mnemo route/constellation/memory;
3. Living current/next;
4. Flashcard front/back/rating;
5. Quiz unanswered/submitted/result;
6. Tutor answer/sources/next action;
7. Library catalog/transfers/route;
8. Onboarding activation flow.

**DoD:**

- pixel/DOM acceptance обновлены осознанно, не blanket overwrite;
- нет horizontal overflow;
- focus не перекрывается sticky surfaces;
- normal text проходит AA;
- primary controls соответствуют целевому sizing;
- reduced-motion не содержит scale/rotation/z-camera;
- документация описывает фактическое runtime-поведение.

## 6. Общие компоненты и владельцы контрактов

| Компонент | Потребители | Контракт |
|---|---|---|
| `SourceAddress` | Library, Tutor, Konspekt, Plan, Mnemo | курс · урок · раздел · time/source |
| `MasterySignal` | Mnemo, Flashcards, Plan, Progress | value + label + non-color status |
| `NextStep` | Mission Control, Plan, Tutor, Mnemo | action + reason + destination |
| `SegmentedControl` | Mnemo, Flashcards, Konspekt | role/state/keyboard/reduced-motion |
| `InlineReceipt` | все mutation surfaces | persistent result + optional toast |
| `ExpertDisclosure` | Tutor, Plan, sidebar, diagnostics | technical data вне normal layer |
| `ReadingRail` | Living Konspekt, Lecture Route | current + next + progress |

Компонент создаётся только тогда, когда минимум два потребителя действительно
используют одинаковый semantic contract. Не вводить абстракцию ради будущего.

## 7. Правила Figma и design QA

### Figma Variables

- `Color/Surface/Canvas`;
- `Color/Surface/Raised`;
- `Color/Text/Primary`;
- `Color/Text/Muted`;
- `Color/Status/Mastered`;
- `Color/Status/Due`;
- `Color/Status/Gap`;
- `Type/UI/Body`;
- `Type/UI/Label`;
- `Type/UI/Metadata`;
- `Effect/Elevation/Contextual`;
- `Motion/Duration/State`.

Modes: `Light`, `Spatial Dark`; `Dark` добавляется только при решении
`full dark: approved` по итогам W3 portal gate.

### Component properties

- state: default/hover/focus/pressed/disabled/loading/error;
- input: pointer/coarse pointer/keyboard;
- density: default/compact только там, где compact не является primary action;
- motion: standard/reduced;
- status: neutral/mastered/due/frontier/gap.

### Review checklist

1. Что является главным действием?
2. На каких данных основан visual signal?
3. Можно ли выполнить сценарий keyboard-only?
4. Что объявит screen reader?
5. Что произойдёт при 200% zoom и 390 px?
6. Что останется при reduced-motion?
7. Есть ли empty/loading/error state?
8. Не создаёт ли поверхность новый hardcoded token?

## 8. Риски и способы контроля

| Риск | Контроль |
|---|---|
| Streamlit rerun ломает focus | хранить logical focus target и восстанавливать после rerun |
| Custom HTML расходится с host theme | передавать только semantic tokens и motion mode |
| Navigation rewrite ломает deep links | полный `ALL_VIEWS` остаётся source of truth; отдельные tests |
| Full dark повторяет Base Web portal regression | `base = "light"` до W3 gate; отдельные portal screenshots и явное решение approved/rejected/deferred |
| Accessibility исправляется визуально, но не семантически | HTML contract tests + ручной keyboard/screen-reader gate |
| Большой UI rewrite нарушает write-set | одна волна — один ограниченный набор файлов |
| Reference начинает диктовать fake data | data-honesty invariant выше visual parity |
| Celebration обесценивает результат | threshold и neutral recovery states |

## 9. Порядок проверки и сдачи каждой волны

1. Зафиксировать точный write-set.
2. Добавить или обновить targeted contract tests.
3. Реализовать минимальное изменение.
4. Запустить только затронутые тесты через
   `.\.venv\Scripts\python.exe -m pytest ...`.
5. Проверить 1366×768 и 390×844; для spatial/desktop дополнительно 1920×1080.
6. Проверить keyboard, reduced-motion и 200% zoom для изменённой поверхности.
7. Обновить `docs/user_guide.md` / `docs/quickstart.md`, если изменилось
   пользовательское поведение.
8. Не закрывать волну при известном contrast, overflow или focus blocker.

Полный pytest suite не является частью каждой волны и запускается только по
отдельному решению перед релизом.

## 10. Итоговый Definition of Done программы

### 10.1 Runtime-код и contract tests (W1–W9) — закрыто

- [x] Correct answer никогда не раскрывается до submit. *(W1)*
- [x] First-run activation выполним за 7–10 минут без blocking tour. *(W2)*
- [x] Mission Control остаётся home; Мнемополис — ceremonial hub. *(инвариант + W5/W6)*
- [x] В Mnemo один mode cluster и один dominant CTA (chrome сведён в utility). *(W5)*
- [x] Meaningful text не меньше 12 px; primary touch targets 40/44 px (foundation + surfaces). *(W3–W5)*
- [x] Flashcard flip и spatial summary доступны screen reader. *(W4 flip; W5 scene summary)*
- [x] Global navigation имеет четыре устойчивых destinations и сохраняет доступ
      ко всем views. *(W6)*
- [x] Living Konspekt открывается как reader, а не список закрытых expanders. *(W7)*
- [x] Library использует 3→2→1 и единый source-address contract. *(W8)*
- [x] Tutor и Plan не показывают normal user внутренние JSON/UUID/enums. *(W9)*
- [x] Light и spatial-dark используют общие semantic tokens; full dark **deferred**
      без смены Streamlit `base` (W3 decision). *(W3)*
- [x] Reduced-motion на ключевых custom animations (tokens, flashcards, mnemo,
      tutor fade, library motion hooks). *(W3–W5, W9; полный аудит — W10)*
- [x] Runtime-документация по затронутому поведению синхронизирована
      (`user_guide`, `quickstart`, статусы волн в этом файле). *(W1–W9)*

### 10.2 Release / visual gates (W10) — открыто

- [ ] Критические сценарии имеют screenshot/DOM regression на целевой матрице
      viewport’ов (раздел W10).
- [ ] Полный pass: horizontal overflow, focus vs sticky, AA contrast, 200% zoom,
      keyboard-only smoke, empty/loading/error/offline на матрице.
- [ ] Reduced-motion audit по **всем** custom surfaces (не только затронутым
      волнами W3–W9).
- [ ] Studio-канбан / product sign-off (вне runtime; `hometutor-studio`) при
      необходимости владельца.

**Итог:** runtime-программа UI/UX-ревью по волнам **W1–W9 завершена** в коде;
закрытие **программы как release** = **W10**.
