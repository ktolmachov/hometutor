# План реализации системного UI/UX-ревью

**Статус runtime (этот репозиторий):** **W1–W9 implemented** (2026-07-18);
**W10 (release gates / visual regression) — partially done** (2026-07-18):
automated static + pure-HTML Playwright gates + bugfix **закрыты**;
live Streamlit e2e scaffold + Mission Control cold smoke **закрыты (W10.F1)**;
Mission Control returning-state + spawned-stack live smoke **закрыты (W10.F2)**;
Mission Control focus-vs-sticky + keyboard CTA smoke **закрыты (W10.F3)**;
full-app pixel baseline / SR audit / remaining focus-vs-sticky / full-app keyboard-only / studio sign-off — **open**.

Исходный продуктовый статус документа: кандидат-программа к утверждению
владельцем. Studio-канбан (`hometutor-studio`) может отставать; ниже — факт
runtime-кода и targeted tests в `hometutor`.

Подготовлено: 2026-07-18.  
Актуализация runtime-статусов: 2026-07-18 (после W1–W9 + residual fixes).  
W10 preflight / inventory / static gates / pure-HTML visual matrix / bugfix:
2026-07-18 (см. §W10 и §10.2).  
W10.F1 live e2e scaffold + Mission Control cold smoke + main.py blocker-fix:
2026-07-18 (см. §W10.F1).  
W10.F2 spawned-stack + Mission Control returning-state live smoke:
2026-07-18 (см. §W10.F2).  
W10.F3 Mission Control focus-vs-sticky + keyboard CTA live smoke:
2026-07-19 (см. §W10.F3).

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
                   W10 Release gates  (partially done)
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
| **W10** | Visual regression / release gates | **partially done** | auto gates + bugfix ✓; live e2e scaffold + Mission Control cold smoke ✓ (W10.F1); spawned-stack + returning-state ✓ (W10.F2); Mission Control focus/keyboard CTA ✓ (W10.F3); pixel baseline / SR / remaining focus-vs-sticky / full-app keyboard-only / studio open |

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

**Статус runtime:** **partially done** (2026-07-18).

| Слой | Статус |
|---|---|
| Preflight + inventory scripts/tests/gates | **done** |
| Static contract / AA / reduced-motion audit | **done** |
| Pure-HTML Playwright visual matrix | **done** |
| Bugfix (contrast, motion, D3 mobile overflow, tokens) | **done** |
| Doc evidence в этом файле | **done** |
| Live Streamlit e2e scaffold (`tests/e2e`) + Mission Control cold/returning smoke | **scaffold landed (W10.F1)**; returning + spawned-stack **landed (W10.F2)**; pixel baseline/diff + остальные surfaces **open** |
| Full Streamlit app pixel screenshots / DOM regression | **open** (artifacts — inventory only) |
| Focus vs sticky / full-app keyboard / SR smoke | **Mission Control focus smoke landed (W10.F3)**; remaining surfaces / full-app keyboard / SR **open** |
| Empty/loading/error/offline **visual** pass | **open** (hooks only) |
| Studio product sign-off | **open** (вне runtime) |

Не помечать всю программу release-done без open-строк выше.  
`tests/e2e` создан в W10.F1; spawned-stack mode добавлен в W10.F2; blanket overwrite
`docs/screenshots/final` **запрещён**.

**Зависимости:** W1–W9 (runtime done).

#### W10.A — Done checklist (runtime)

- [x] Preflight: clean worktree policy, no merge of addendum-candidates, no full dark.
- [x] Inventory: scripts / tests / demo screenshots. `tests/e2e` завёлся в W10.F1
      (Mission Control cold smoke; pixel regression и пр. — open).
- [x] Static gates module `tests/test_w10_release_gates.py`:
  - viewport matrix constants (1366×768, 1920×1080, 390×844, 1440×900);
  - foundation 12/16/40/44; full dark deferred + `base = light`;
  - spatial-dark + status-token AA helpers;
  - reduced-motion declared on custom surfaces;
  - host reduce kills card hover transforms;
  - SSR kicker/toggle AA + type floor;
  - library overflow-safe columns; focus-visible foundation;
  - critical surface modules + empty/offline hooks presence;
  - honesty gates (screenshots inventory-only, no root e2e).
- [x] Playwright HTML matrix `tests/test_w10_visual_matrix.py`
  (opt-out `HT_SKIP_W10_VISUAL=1` / `HT_SKIP_KG_3D_VISUAL=1`):
  - flashcard: no overflowX, chips ≥44px, Space flip, reduced-motion no 3D;
  - host chrome (SSR + lib-card + mission + home-dash): overflow, SSR contrast ≥4.5,
    200% zoom no overflow, hover transform off under reduce;
  - D3 template: reduced-motion + mobile overflow.
- [x] Existing auto retained: W1–W9 contracts; KG 3D Playwright
  (`test_knowledge_graph_counters`); design tokens / portals / theme_presets.
- [x] Bugfix (W10, waves W1–W9 not reopened):
  1. `.home-dash-card` / `.mode-card` hover transform under reduced-motion;
  2. D3 infinite pulse/decay reduced-motion media;
  3. SSR kicker/toggle AA (`#1f6a9a`) + ≥12px type;
  4. Tutor Q&A handoff reduced-motion;
  5. foundation `--status-warn` `#b9770e` → `#92600a` (CSS + `design_tokens.py`);
  6. D3 390×844 scrollWidth (panel `translateX(100%)`, `#wrap` clip, tools wrap,
     fluid search/panels, mobile `@media`);
  7. reduced-motion no longer un-hides closed `.panel`;
  8. `test_theme_presets` parse: no trailing comment on `--status-warn` line.
- [x] Write-set landed:
  - `app/ui_theme.css`
  - `app/ui/design_tokens.py`
  - `app/ui/assets/knowledge_graph_d3_template.html`
  - `app/ui/tutor_chat_session.py`
  - `tests/test_w10_release_gates.py` *(new)*
  - `tests/test_w10_visual_matrix.py` *(new)*
  - `docs/ui_ux_design_review_implementation_plan.md` (this file)
- [x] Targeted tests green (W10 bundle): release_gates + visual_matrix +
  design_tokens + portals + theme_presets + flashcards + tutor + library
  contracts. User suite also reported theme_presets regression fixed after #8.

#### W10.B — Inventory (sources of truth)

| Источник | Что есть | Gate coverage |
|---|---|---|
| `tests/test_w10_release_gates.py` | inventory, reduced-motion audit, AA, surfaces | **auto · done** |
| `tests/test_w10_visual_matrix.py` | Playwright HTML matrix | **auto · done** |
| `tests/test_ui_design_tokens.py`, `test_theme_portals_contract.py`, `test_theme_presets.py` | foundation / portals / :root parity | **auto · done** |
| `tests/test_flashcards_interactive_card.py` (+ keyboard) | flip a11y, 44px, ResizeObserver | **auto · done** |
| `tests/test_knowledge_graph_counters.py` | 3D Memory Run Playwright viewport | **auto · done** (opt-out) |
| W1–W9 `test_*_ui_contract.py` / surface smokes | quiz, nav, library, tutor, plan, living, onboarding | **auto · done** (contract) |
| `docs/screenshots/final/scenario_*` | historical demo frames | **inventory only** |
| `scripts/` | product/integration gates; **no** UI screenshot runner | n/a visual |
| `tests/e2e/` | W10.F1/F2/F3: live Streamlit smoke; spawned FastAPI+Streamlit by default; Mission Control cold/returning/focus на 1366/1920/390 | **auto · scaffold + returning + focus landed** (opt-out `HT_SKIP_E2E_LIVE=1`); pixel baseline + остальные surfaces **open** |

#### W10.C — Critical surfaces (auto vs remaining live)

| Поверхность | Auto done | Still open (live Streamlit) |
|---|---|---|
| Mission Control / home | progressive/nav; SSR AA; host-chrome Playwright overflow/200% zoom | cold/returning full-app screenshots |
| Global nav + sidebar | navigation contracts | full chrome keyboard-only |
| Mnemo / 3D hall | KG 3D Playwright; D3 reduce + mobile overflow | spatial full interaction; SR smoke |
| Flashcards review | W4 + Playwright viewport/touch/keyboard/reduce | iframe-in-Streamlit screenshots |
| Quiz | W1 integrity | unanswered/submitted/result frames |
| Living Konspekt | reader smoke / layout | reading-route zoom + sticky focus |
| Library | 3→2→1 + address + lib-card fixture overflow | catalog/transfers full app |
| Tutor Chat | W9 contracts + handoff reduce | answer/sources/next-action frames |
| Adaptive Plan | hub/detail contracts | hub/detail visual pass |
| Onboarding | activation flow tests | first-ten-minutes visual journey |

#### W10.D — Viewport matrix

| Viewport | Modes | Fixture coverage |
|---|---|---|
| 1366×768 | light, spatial-dark; full dark deferred | **done** (HTML matrix + KG 3D) |
| 1440×900 | light | **done** (HTML matrix) |
| 1920×1080 | light | **done** (HTML matrix + KG 3D) |
| 768×1024 | portrait tablet | partial (KG 1024 in 3D tests; not full host fixture) |
| 390×844 | touch/mobile | **done** (HTML matrix + D3 overflow fix + KG 3D) |

Additional axes:

| Axis | Status |
|---|---|
| reduced-motion | **done** static + HTML fixtures (flashcard, host, D3, kg_3d); full Streamlit optional |
| 200% zoom | **done** host chrome fixture; full Streamlit **open** |
| keyboard-only | **done** flashcard Space; full-app **open** |
| screen-reader smoke | **open** |
| empty/loading/error/offline visuals | hooks **done**; visual pass **open** |

#### W10.E — Open (required for full W10 / release close)

- [ ] **[W10-PIXEL-OPEN]** Full Streamlit app pixel/DOM baseline + diff на матрице
      — **open** (live artifacts в `tests/e2e/_artifacts/` — inventory only;
      baseline/diff pipeline не реализован; W10.F1/F2/F3 закрыли только Mission Control smoke).
- [~] Full Streamlit app screenshot/DOM regression на matrix — `tests/e2e`
      harness scaffold **landed (W10.F1)** + returning-state **landed (W10.F2)**;
      pixel baseline/diff → см. `[W10-PIXEL-OPEN]`.
- [~] Live focus vs sticky surfaces in Streamlit chrome — Mission Control
      matrix smoke **landed (W10.F3)**; remaining critical surfaces **open**.
- [ ] Full-app keyboard-only smoke (all critical destinations).
- [ ] Empty/loading/error/offline **visual** pass on matrix.
- [ ] Screen-reader smoke audit.
- [ ] Studio-канбан / product sign-off (`hometutor-studio`) if required by owner.
- [ ] Optional: tablet 768×1024 host-chrome fixture parity.

**Обязательные сценарии (product list; fixture ≠ full-app screenshot):**

1. Mission Control cold/returning — contract/fixture partial;
   **cold live smoke landed (W10.F1)**; **returning-state live smoke landed (W10.F2)**;
   pixel baseline **open**;
2. Mnemo route/constellation/memory — 3D Playwright **done**; full interaction **open**;
3. Living current/next — reader contracts **done**; full-app frames **open**;
4. Flashcard front/back/rating — HTML Playwright **done**; Streamlit host **open**;
5. Quiz unanswered/submitted/result — integrity **done**; frames **open**;
6. Tutor answer/sources/next action — contracts **done**; frames **open**;
7. Library catalog/transfers/route — 3→2→1 + fixture **done**; full-app **open**;
8. Onboarding activation flow — flow tests **done**; visual journey **open**.

**DoD (release package):**

| Criterion | Status |
|---|---|
| pixel/DOM acceptance without blanket overwrite | **policy held**; live e2e scaffold **landed (W10.F1/F2)**; pixel baseline/diff **open** |
| no horizontal overflow | **done** on HTML fixtures + D3 mobile fix + live Mission Control cold/returning smoke (W10.F1/F2); remaining live surfaces **open** |
| focus not covered by sticky | **partial**: Mission Control matrix smoke **landed (W10.F3)**; remaining live surfaces **open** |
| normal text AA | **done** (SSR + tokens + spatial-dark checks) |
| primary control sizing 40/44 | **done** foundation + flashcard fixture |
| reduced-motion no scale/rotation/z-camera on custom surfaces | **done** audit + fixtures |
| docs match runtime | **done** (this plan); user_guide/quickstart N/A for a11y-only fixes |

#### W10.F — Live Streamlit e2e waves

W10.F — это инкрементальное закрытие open-пунктов W10.E через live Streamlit
harness в `tests/e2e/` (spawned-stack default + external URL override; см.
`tests/e2e/README.md`).

##### W10.F1 — Mission Control cold-state live smoke (2026-07-18)

**Статус:** **scaffold landed** (не release-close).

- [x] `tests/e2e/` создан: `__init__.py`, `conftest.py` (fixtures + health-gated
      skip + artifacts dir), `test_mission_control_live.py`, `README.md`.
- [x] External-stack mode: подключается к запущенному
      `scripts/run_local_stack.ps1` (backend :8000 + Streamlit :8501);
      env `HT_E2E_STREAMLIT_URL`, opt-out `HT_SKIP_E2E_LIVE=1`.
- [x] Mission Control cold-state smoke на матрице `1366×768`, `1920×1080`,
      `390×844`: HTTP 200 + `stMain` present, no `stException`, реальные DOM-
      селекторы Mission Control через `querySelectorAll`
      (`[data-testid="mission-control-ssr-banner"]` ≥1,
      `[data-testid^="mission-tile-"]` ≥3 — не CSS-подстроки в `body_html`),
      no horizontal overflow, no Playwright `pageerror`,
      artifact screenshot в `_artifacts/` (inventory).
- [x] Blocker-fix в этой же волне: leftover-вызов `_render_hidden_nav_expander()`
      в `app/ui/main.py` (regression из коммита 322) — app падал на главной;
      теперь Mission Control рендерится чисто на всех 3 viewports.
- [x] Honesty gate усилен: `tests/test_w10_release_gates.py` теперь требует
      `tests/e2e/test_mission_control_live.py` + structured anchor
      `[W10-PIXEL-OPEN]` в §W10.E (открытый `[ ]` checkbox; flip в `[x]` —
      единственный способ пометить pixel done, и это review-checkpoint).
- [x] Live markers проверяются через реальные DOM-селекторы Mission Control
      (`[data-testid="mission-control-ssr-banner"]`, `[data-testid^="mission-tile-"]`),
      не через подстроки CSS-классов в `body_html`.

**Write-set:**
- `app/ui/main.py` *(blocker fix)*
- `tests/e2e/__init__.py`, `tests/e2e/conftest.py`, `tests/e2e/test_mission_control_live.py`,
  `tests/e2e/README.md` *(new)*
- `tests/test_w10_release_gates.py` *(honesty gate усилен)*
- `.gitignore` *(артефакты e2e)*
- `docs/ui_ux_design_review_implementation_plan.md` *(этот §W10.F1 + §W10.E/DoD)*

**Targeted tests (W10.F1):**

```powershell
# Live stack должен быть запущен: .\scripts\run_local_stack.ps1 -SkipPip
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
.\.venv\Scripts\python.exe -m pytest tests/test_w10_release_gates.py -q
```

**Visual DoD (W10.F1):** live Playwright открывает Mission Control на
`1366×768` / `1920×1080` / `390×844`; для каждого viewport — нет `stException`,
нет горизонтального overflow, `querySelectorAll` находит
`[data-testid="mission-control-ssr-banner"]` (≥1) и
`[data-testid^="mission-tile-"]` (≥3); screenshot сохранён в
`tests/e2e/_artifacts/` (inventory, не baseline).

**Что осталось open после W10.F1 (не помечать W10 fully done):**
- pixel/DOM baseline + diff на live app (артефакты — inventory-only);
- Mission Control returning-state (warm session) + SSR actionable body;
- live focus-vs-sticky; full-app keyboard-only; SR smoke;
- empty/loading/error/offline visuals на live app;
- spawned/self-contained stack mode (сейчас external-stack);
- остальные critical surfaces (mnemo / flashcards / quiz / tutor / library /
  konspekt / adaptive plan / onboarding) — live smoke пока не написан.

**Можно ли менять статус W10?** **Нет.** W10 остаётся **partially done**.
W10.F1 закрывает один live-gate (Mission Control cold smoke) + чинит
runtime-блокер; но open-пункты W10.E (pixel regression, focus-vs-sticky,
keyboard-only full-app, SR smoke, empty/loading/error/offline visuals) требуют
отдельных волн. До их закрытия переводить W10 в «fully done» запрещено
(см. принцип «Не помечать W10 fully done без full Streamlit visual/a11y pass»).

##### W10.F2 — Mission Control returning-state + spawned-stack live smoke (2026-07-18)

**Статус:** **done for W10.F2** (не release-close).

- [x] `tests/e2e/conftest.py` теперь по умолчанию поднимает self-contained
      real stack через subprocess: `uvicorn app.api:app` + `streamlit run
      app/ui/main.py` на свободных портах. External-stack override
      `HT_E2E_STREAMLIT_URL` сохранён.
- [x] Spawned stack использует временный seeded `HOME_RAG_HOME`:
      `HOME_RAG_DATA_DIR`, `HOME_RAG_INDEX_DIR`, Chroma collection,
      `index_registry.json`, `index_meta.json`; включён
      `HOME_RAG_E2E_OFFLINE=1`, чтобы live smoke не зависел от LM Studio/cloud.
- [x] Mission Control returning/warm-state live smoke на `1366×768`,
      `1920×1080`, `390×844`: no `stException`, no page/console errors,
      no horizontal overflow, sidebar/main navigation present, SSR actionable
      body present (`e2e-ssr-why-not-others`, `e2e-ssr-contrast`),
      non-cold proof (`mission tile` >3, `Ещё режимы`, no empty-index hero),
      singular primary learning CTA in main flow.
- [x] Artifacts остаются inventory-only в `tests/e2e/_artifacts/`:
      `mission_control_returning_*.png`, `spawned_fastapi.log`,
      `spawned_streamlit.log`. Baseline/diff pipeline не добавлен.

**Write-set:**
- `tests/e2e/conftest.py`
- `tests/e2e/test_mission_control_live.py`
- `tests/e2e/README.md`
- `docs/ui_ux_design_review_implementation_plan.md`

**Targeted tests (W10.F2):**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
# 7 passed
```

**Visual DoD (W10.F2):** live Playwright открыл Mission Control returning-state
на `1366×768` / `1920×1080` / `390×844`; для каждого viewport есть SSR DOM,
расширенная non-cold сетка, основной CTA, no overflow, no page/console errors;
screenshot сохранён в `tests/e2e/_artifacts/` (inventory, не baseline).

**Что осталось open после W10.F2 (не помечать W10 fully done):**
- `[W10-PIXEL-OPEN]` live app pixel/DOM baseline + diff;
- live focus-vs-sticky; full-app keyboard-only; SR smoke;
- empty/loading/error/offline visuals на live app;
- остальные critical surfaces (mnemo / flashcards / quiz / tutor / library /
  konspekt / adaptive plan / onboarding) — full live smoke/pixel coverage open.

**Можно ли менять статус W10?** **Нет.** W10.F2 done, W10 still
**partially done**.

##### W10.F3 — Mission Control focus-vs-sticky + keyboard CTA live smoke (2026-07-19)

**Статус:** **done for W10.F3** (не release-close).

- [x] Mission Control focus-vs-sticky smoke на `1366×768`, `1920×1080`,
      `390×844`: Playwright проходит Tab по видимым focus stops, проверяет,
      что focused control находится во viewport и `elementFromPoint` не
      показывает fixed/sticky chrome поверх active element.
- [x] Mission Control primary learning/onboarding CTA keyboard activation smoke:
      CTA достигается через Tab, активируется Enter; после activation — no
      `stException`, no page/console errors, no horizontal overflow.
- [x] Artifacts остаются inventory-only в `tests/e2e/_artifacts/`:
      `mission_control_focus_*.png`, `mission_control_keyboard_cta_1366x768.png`.
      Baseline/diff pipeline не добавлен.

**Write-set:**
- `tests/e2e/test_mission_control_live.py`
- `tests/e2e/README.md`
- `tests/e2e/__init__.py`
- `docs/ui_ux_design_review_implementation_plan.md`

**Targeted tests (W10.F3):**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
# 11 passed
```

**Visual DoD (W10.F3):** live Playwright подтвердил, что видимые focused
controls Mission Control не перекрываются sticky/fixed chrome на release matrix;
основная CTA достигается и активируется с клавиатуры без runtime errors/overflow.
Это smoke, не полный keyboard-only сценарий всех разделов.

**Что осталось open после W10.F3 (не помечать W10 fully done):**
- `[W10-PIXEL-OPEN]` live app pixel/DOM baseline + diff;
- remaining focus-vs-sticky для других critical surfaces;
- full-app keyboard-only smoke (all critical destinations);
- SR smoke; empty/loading/error/offline visuals на live app;
- остальные critical surfaces (mnemo / flashcards / quiz / tutor / library /
  konspekt / adaptive plan / onboarding) — full live smoke/pixel coverage open.

**Можно ли менять статус W10?** **Нет.** W10.F3 done, W10 still
**partially done**.

**Targeted tests (W10 — run after touch):**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_w10_release_gates.py tests/test_w10_visual_matrix.py tests/test_ui_design_tokens.py tests/test_theme_portals_contract.py tests/test_theme_presets.py tests/test_flashcards_interactive_card.py tests/test_tutor_chat_ui_contract.py tests/test_library_schedule_ui_contract.py -q
```

Опционально (Playwright Chromium, 3D Memory Run visual matrix):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_graph_counters.py -k "visual_smoke or viewport" -q
```

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
      tutor fade, library motion hooks). *(W3–W5, W9)*
- [x] Reduced-motion **full static + HTML-fixture audit** по custom surfaces
      (host CSS, flashcards, tutor header/handoff, kg_3d, d3, card hovers). *(W10)*
- [x] Runtime-документация по затронутому поведению синхронизирована
      (`user_guide`, `quickstart` для W1–W9; W10 evidence — этот файл).

### 10.2 Release / visual gates (W10) — partially done

#### Closed in runtime (2026-07-18)

- [x] Инвентаризация scripts/tests/gates и critical surfaces
      (`tests/test_w10_release_gates.py` + §W10.B).
- [x] Reduced-motion audit (static + Playwright fixtures) по host CSS + custom
      surfaces: `ui_theme.css`, flashcards, tutor header/handoff, kg_3d,
      **d3 template**, card hover transforms.
- [x] AA / type floor: SSR Mission Control kicker/toggle; foundation
      `status-warn`; spatial-dark text/surface; status tokens on white.
- [x] Pure-HTML Playwright matrix (`test_w10_visual_matrix.py`): viewports
      1366/1920/390/1440 — flashcard overflow/touch/keyboard; host chrome
      (SSR+lib+mission) overflow + SSR contrast sampling; host 200% zoom;
      D3 reduced-motion + mobile overflow.
- [x] Mnemo 3D: Playwright viewport/overflow smoke
      (`test_knowledge_graph_counters`).
- [x] D3 mobile horizontal overflow bugfix (390×844 scrollWidth).
- [x] Card hover reduced-motion + tutor handoff reduced-motion.
- [x] Theme :root / foundation parity (`test_theme_presets`) после status-warn.
- [x] Doc-sync evidence в §W10 / этом checklist (без false «W10 done»).
- [x] **W10.F1 (2026-07-18):** live Streamlit e2e scaffold `tests/e2e/`
      (external-stack mode) + Mission Control cold-state smoke на матрице
      1366/1920/390 (HTTP 200, no `stException`, DOM markers, no overflow,
      artifacts в `_artifacts/` — inventory). Blocker-fix: leftover-вызов
      `_render_hidden_nav_expander()` в `app/ui/main.py` (regression из
      коммита 322) — app падал на главной; теперь рендерится чисто.
- [x] **W10.F2 (2026-07-18):** default spawned-stack live e2e
      (`uvicorn` + `streamlit` subprocess на free ports, seeded temp
      `HOME_RAG_HOME`, `HOME_RAG_E2E_OFFLINE=1`) + Mission Control
      returning-state smoke на матрице 1366/1920/390 (SSR actionable body,
      non-cold tile inventory, singular primary learning CTA, no page/console
      errors, no overflow, screenshots inventory).
- [x] **W10.F3 (2026-07-19):** Mission Control focus-vs-sticky smoke на
      матрице 1366/1920/390 + keyboard activation smoke для primary
      learning/onboarding CTA (Tab → Enter, no `stException`, no page/console
      errors, no overflow, screenshots inventory). **Scope honesty:** remaining
      surfaces focus-vs-sticky + full-app keyboard-only — still open.
      **Honesty:** pixel baseline/diff, remaining focus-vs-sticky,
      keyboard-only full-app, SR smoke, empty/loading/error/offline visuals —
      **still open** (см. §W10.F3, §W10.E).

#### Still open (block full release close)

- [~] **Full Streamlit app** screenshot/DOM regression on matrix — live e2e
      scaffold + Mission Control cold/returning smoke **landed (W10.F1/F2)**;
      pixel baseline/diff + остальные critical surfaces **open**
      (demo PNG в `docs/screenshots/final` — inventory only).
- [~] Live pass: focus vs sticky in Streamlit chrome — Mission Control
      **landed (W10.F3)**; remaining critical surfaces **open**.
- [ ] Full-app keyboard-only smoke (all critical destinations).
- [ ] Empty/loading/error/offline **visuals** on matrix.
- [ ] Screen-reader smoke audit.
- [ ] Studio-канбан / product sign-off (вне runtime; `hometutor-studio`) при
      необходимости владельца.

**Итог:** runtime-программа UI/UX-ревью по волнам **W1–W9 завершена** в коде;
**W10 partially done** — automated static + pure-HTML Playwright gates + bugfix
**закрыты**; live Streamlit e2e scaffold + Mission Control cold/returning/focus smoke
**закрыты (W10.F1/F2/F3)**; закрытие **программы как release** требует оставшихся
open-пунктов выше (не помечать W10 fully done без full Streamlit
visual/a11y pass).
