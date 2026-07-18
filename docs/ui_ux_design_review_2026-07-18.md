# Системное UI/UX-ревью hometutor

Статус: baseline-аудит текущего runtime-продукта.

Дата: 2026-07-18.

Связанный план реализации: [ui_ux_design_review_implementation_plan.md](ui_ux_design_review_implementation_plan.md).

## 1. Область и метод ревью

Цель ревью — оценить hometutor как цельный учебный продукт, а не как набор
Streamlit-экранов. Главный критерий: может ли пользователь за пять секунд понять,
где он, что изменилось в его знании, куда идти дальше и почему.

Проверены:

- Mission Control;
- Knowledge Graph / Мнемополис и 3D-зал;
- Living Konspekt и Lecture Route;
- Flashcards / spaced repetition;
- Quiz и Adaptive Plan;
- Tutor Chat;
- Library / Mega-bundle catalog;
- onboarding и первые десять минут;
- global navigation, sidebar, toast, modal и embedded-поверхности;
- тема, `--kgx-*`-токены, типографика, motion, accessibility и responsive.

Аудит включал:

1. Чтение runtime-кода и CSS в `app/ui/*`, `app/ui_theme.css` и
   `app/ui/assets/*`.
2. Сопоставление production с vision и reference-материалами, которые находятся
   в отдельном репозитории `hometutor-studio`, а не в runtime-репозитории:
   `knowledge_graph_3d_world_vision.md` v3.2,
   `knowledge_graph_3d_game_plan.md`,
   `knowledge_graph_3d_reorientation_plan.md`,
   `mega_bundle_catalog_plan.md`, три состояния
   `18_kg_3d_hall_*.html`, `21_mega_bundle_catalog.html`,
   `notebook_deck_guide.md` и `notebook_template.html`.
3. Визуальную проверку reference и сгенерированного production 3D fixture на
   1366×768 и 390×844.
4. Проверку DOM-размеров, accessible markup, motion contracts и контрастов.

Ограничение: полный Streamlit-продукт со всеми пользовательскими данными не
прогонялся как end-to-end visual regression. Все выводы о 3D-зале подтверждены
визуально и кодом; выводы об остальных разделах — runtime-разметкой, стилями и
существующими screenshot-сценариями.

## 2. Главный вывод: Мнемополис

**Оценка: 7,4/10.** Мнемополис — самая сильная и наиболее отличимая часть
hometutor. Его ценность не в «3D ради 3D», а в честной семантике мира:

- туман — `1 - retention`;
- рассвет — завершённый путь;
- фонарь — quiz-сигнал;
- ромб — workbench;
- разлом — реальный prerequisite gap;
- маршрут — вычисленный следующий путь, а не декоративная линия.

Reference route/constellation/memory уже воспринимается как самостоятельный
продукт. Production уступает ему не концепцией, а редактурой: мелкая
типографика, повторяющиеся режимы и избыток controls превращают церемониальный
зал в cockpit.

### 2.1 Что работает отлично

- `route | local | all` являются взаимоисключающими сценами, а Memory —
  ортогональный overlay. Этот контракт не следует размывать новым набором
  равноправных режимов.
- Маршрут визуально доминирует над полным графом и отвечает на вопрос
  «я здесь → дальше сюда → потому что».
- Production не использует бессмысленный непрерывный animation loop:
  перерисовка в основном событийная, camera transitions вызываются по действию.
- Canvas имеет `role="img"` и название (`app/ui/assets/kg_3d_template.html:626`),
  а остановки продублированы доступными кнопками с `aria-current`.
- Есть focus-visible rules (`kg_3d_template.html:467`) и частичная поддержка
  `prefers-reduced-motion` (`kg_3d_template.html:586`, JS около строки 951).
- Breakpoints 860/560 структурно правильные: панель уходит под сцену, primary
  actions становятся одноколоночными.
- Bridge `app/ui/assets/kg_3d_component/index.html` валидирует action envelope,
  различает parent/child source и использует Streamlit component value как
  основной канал вместо хрупкой навигации через `top.location`.

### 2.2 Критические проблемы

#### Повтор одного и того же управления

Topbar уже содержит «Маршрут / Созвездие / След памяти»
(`kg_3d_template.html:603-607`), но внутри сцены снова показаны presentation
presets (`:635-640`). Две системы меняют одно состояние, увеличивают cognitive
load и затрудняют объяснение различий между scene mode и overlay.

#### Слишком мелкий production UI

В production fixture на 1366×768 получены ориентировочные фактические размеры:

| Элемент | Размер |
|---|---:|
| top scene modes | около 24 px высотой |
| scene presets | около 26 px |
| photo/help | около 28 px |
| route arrows | 36 px |
| primary CTA | 40 px |
| служебный текст | 9,9–11,5 px |

Источники плотности видны в CSS: `.kgx-mode` использует `0.72rem`
(`kg_3d_template.html:70-78`), многие подписи — `0.62-0.72rem`, а mobile icons
уменьшаются до 34 px (`:582`). Для ключевого spatial-интерфейса целевой размер
основных controls должен быть 40 px на desktop и 44 px на coarse pointer.

#### Неполная доступная проекция

Canvas сообщает о наличии 3D-графа, но не передаёт screen reader:

- текущий scene mode;
- видимые связи constellation/all;
- fog/retention;
- причины разломов;
- изменение состояния после camera transition.

Route list покрывает основной маршрут, но не является эквивалентом всей сцены.

#### Слишком много live regions

Одновременно используются progress, stats, architect, chronicle, action status,
hidden stop info и toast (`kg_3d_template.html:611-649`, `:749-789`). Одно
действие может вызвать несколько последовательных объявлений.

#### Перегруз первого кадра

На первом уровне конкурируют topbar, modes, calm, photo, rules, status, presets,
chronicle, compass, replay, arrows, more menu, stop dock и route list. Canvas
может соблюдать лимит до восьми labels, но chrome вокруг него этот лимит
фактически отменяет.

### 2.3 Рекомендации

На первом уровне оставить:

1. `Маршрут / Созвездие`;
2. сцену;
3. current stop card;
4. один primary CTA.

Memory оставить toggle в utility zone. `Вся карта`, photo, replay, camera reset и
presentation presets перенести в `…` или contextual sheet.

```css
.kgx-mode {
  min-height: 36px;
  padding-inline: 14px;
  font-size: 13px;
}

.kgx-icon-btn {
  width: 40px;
  height: 40px;
}

@media (pointer: coarse) {
  .kgx-mode,
  .kgx-icon-btn,
  .kgx-action {
    min-height: 44px;
  }
}
```

Дополнительно:

- meaningful text не меньше 12 px;
- route reason — минимум 14 px/1.45;
- один скрытый `#kgx-announcer` вместо набора competing live regions;
- скрытая структурированная альтернатива canvas: mode, stop, connections,
  retention и reason;
- reduced-motion меняет z-camera/rotation на мгновенное состояние или fade;
- route glow остаётся data signal, glass/blur используется только для HUD.

### 2.4 Visual QA reference

- Reference на 1366×768 сохранил сильную иерархию маршрута, но имел около 17 px
  лишнего vertical overflow и частично обрезанный второй CTA. Reference следует
  считать interaction/visual contract, но не безусловным pixel-perfect gold.
- Production fixture точно помещался в 1366×768 без horizontal overflow, но
  достигал этого слишком мелкими controls.
- На 390×844 layout становился одноколоночным без horizontal overflow, однако
  третья mode-кнопка переносилась, а touch targets оставались недостаточно
  комфортными.

## 3. Общая оценка продукта

| Критерий | Оценка | Диагноз |
|---|---:|---|
| Cohesion / Brand consistency | 6,2 | Мнемополис, Streamlit UI и notebook/export живут в трёх системах |
| Modernity & delight | 7,0 | 3D-зал и Memory Run сильны; shell часто выглядит как dashboard |
| Clarity & hierarchy | 5,7 | Mission Control улучшен, но navigation, Reader, Quiz и sidebar перегружены |
| Accessibility & inclusivity | 5,4 | Native widgets помогают, custom HTML имеет semantic, contrast и motion gaps |
| Performance feel | 6,3 | 3D event-driven; iframe sizing, rerun-переходы и несистемный motion мешают |
| **Итог** | **6,1/10** | Сильная продуктовая идея опережает качество общей оболочки |

## 4. Mission Control

**Оценка: 6,8/10.**

### Работает отлично

- Mission Control закреплён как home, Мнемополис — ceremonial hub.
- Returning user получает SSR и не более двух resume surfaces; остальные
  режимы находятся под «Ещё режимы» (`app/ui/mission_control.py:1113-1179`).
- SSR объясняет причину следующего шага, а не только рекомендует действие.
- Cold-start и returning-user состояния различаются.

### Проблемы

- `_render_tile()` рисует custom visual card и отдельную Streamlit-кнопку
  (`mission_control.py:435-485`). Карточка выглядит кликабельной, но её поверхность
  не является интерактивной.
- Grid открывается одним `st.markdown('<div>')`, widgets выводятся отдельными
  Streamlit blocks, div закрывается другим markdown-вызовом (`:541-558`). Такой
  wrapper не является надёжным DOM-родителем widgets; descendant CSS и
  reduced-motion selectors могут не применяться.
- SSR использует собственную cool-blue mini-theme
  (`app/ui_theme.css:999-1010`) вместо product semantic tokens.
- `#4a9fd4` на приблизительном `#ebf5ff` даёт около 2,65:1. Этот цвет используется
  для маленького uppercase-текста (`ui_theme.css:1052`) и не проходит AA для
  обычного текста.

### Рекомендации

- Вся learning card — один semantic button/link.
- Отказаться от split-markdown wrapper pattern.
- Перекрасить SSR через semantic tokens.
- Убрать transform у `.home-dash-card:hover` в reduced-motion; текущий блок не
  покрывает все cards (`ui_theme.css:713`, `:1323-1349`).
- Перенести из Memory Run структуру «одна остановка, одна причина, одно действие»,
  а не его neon-стилистику.

## 5. Living Konspekt и Lecture Route

**Оценка: 5,9/10.**

### Работает отлично

- Понятен lifecycle: sections → read → memory → save → next.
- Readiness, questions, consumed/understood и связь с планом основаны на данных.
- Persistence и источники объясняются честно.

### Проблемы

- «Режим чтения» скрывает каждый раздел в закрытом expander
  (`app/ui/living_konspekt_reader.py:180`). Это outline browser, а не reader.
- Пять действий «Понял / Сомневаюсь / Не понял / Прочитано / Сохранить мысль»
  выводятся одной строкой (`:270`) и плохо масштабируются на mobile.
- Пять top-level tabs (`app/ui/living_konspekt_view.py:513`) создают второй слой
  навигации поверх global navigation.
- Lecture Route не имеет выраженного текущего положения, next stop и reason.

### Рекомендации

- По умолчанию открыт текущий раздел, рядом sticky reading rail и previous/next.
- Понимание — один segmented control из трёх состояний.
- «Прочитано» фиксируется явным Next, а «Сохранить мысль» становится contextual
  action.
- Metadata скрывается в disclosure; в потоке остаются source address и один
  memory signal.
- Route использует ту же грамматику, что Memory Run: current, next, because.

## 6. Flashcards / spaced repetition

**Оценка: 6,3/10.**

### Работает отлично

- Undo, interval forecast, memory signals, source links и Tutor handoff образуют
  зрелую learning loop.
- Review явно связан с retention/fog (`app/ui/flashcards_review_view.py:632`).
- Rating actions остаются native buttons и поддерживают shortcuts.

### Проблемы

- Навигация дублируется: horizontal radio и три кнопки «Колоды / Создать /
  Повторение» (`app/ui/flashcards_ui.py:286-308`).
- Flip surface — кликабельный `div` без `button`, `tabindex`, `aria-pressed` или
  доступного состояния стороны (`app/ui/flashcards_interactive_card.py:324`).
- Flip 0,5 s и pop animation не имеют reduced-motion (`:171`, `:243`).
- iframe height оценивается эвристически, а `scrolling=True` допускает ugly inner
  scrollbar (`app/ui/flashcards_review_view.py:1141-1147`).

### Рекомендации

- Один segmented navigation.
- Flip surface — `<button aria-pressed>`; стороны связаны через accessible name
  и description.
- Reduced-motion меняет content без 3D rotation.
- Четыре rating buttons по 44 px, interval — вторичной строкой.
- ResizeObserver подтверждает высоту; scrolling только у outer page.

## 7. Quiz и Adaptive Plan

**Оценка Quiz: 5,1/10. Оценка Adaptive Plan: 5,8/10.**

### Работает отлично

- Quiz поддерживает несколько типов и возвращает результат в graph.
- `quiz_panel.py` и `scoped_quiz.py` уже содержат правильный interaction pattern:
  явный «Ответить», затем feedback и разбор
  (`app/ui/scoped_quiz.py:138-197`).
- Adaptive Plan показывает причину выбора и расчёт нагрузки.

### Критические проблемы Quiz

1. До submit доступен expander «Проверка вопроса», который при пустом ответе
   показывает «Неверно. Правильно: …»
   (`app/ui/interactive_quiz.py:563-567`). Это ломает assessment integrity.
2. Пользователь видит developer enums `multiple_choice`, `true_false`,
   `fill_blank`, `ordering` (`:388`), raw question type и session diagnostics.
3. True/False остаётся на английском.
4. Ordering требует ввода пунктов через запятую вместо reorder UI.
5. `st.balloons()` запускается после завершения независимо от качества
   результата (`:647`), что нарушает честность feedback.

### Проблемы Adaptive Plan

- В одном view последовательно выводятся hub и полный daily plan
  (`app/ui/main.py:379-381`). Summary и detail дублируются.
- Повторяется ненадёжный `home-dash-card` wrapper
  (`app/ui/adaptive_plan_hub_layout.py:54`).
- Preview строит до четырёх равных колонок и показывает `XP auto`
  (`:223-243`).

### Рекомендации

- Основной Quiz перевести на модель `scoped_quiz`: question → answer → feedback
  → next.
- Correct answer не включать в DOM до submit.
- Ordering: drag-and-drop плюс кнопочная альтернатива вверх/вниз.
- Celebration только при осмысленном достижении.
- Adaptive Plan: hub или detail; desktop master/detail, mobile drill-down.
- XP/scoring — внутри Expert disclosure.

## 8. Tutor Chat

**Оценка: 6,4/10.**

### Работает отлично

- Sources, confidence, handoff, mini-quiz и next-best-action отличают продукт от
  generic AI messenger.
- Сохраняется continuity между вопросом, объяснением, quiz и планом.
- Есть focus mode и expert layer.

### Проблемы

- Постоянный `st.info` в начале становится onboarding chrome
  (`app/ui/tutor_chat_header.py:61`).
- Export выводится до истории разговора (`app/ui/tutor_chat_session.py:760`).
- Названия сессий основаны на коротком UUID и preview, а не на теме.
- Normal UI показывает «промпт + поле depth_level в JSON»
  (`app/ui/tutor_chat_controls.py:29`).
- Footer постоянно показывает session ID и технические счётчики
  (`app/ui/tutor_chat_footer.py:172`).
- Message fade не связан с reduced-motion.

### Рекомендации

- Свернуть intro после первого успешного ответа.
- Порядок: header → history → input → next actions → exports/expert.
- Именовать сессии по теме.
- Depth: «Кратко / С объяснением / Глубоко».
- Источник — общий address-chip `Курс · Урок · Раздел · 03:20`.
- Motion сообщения: 160–180 ms fade/translate 4 px; без translate при
  reduced-motion.

## 9. Library / Mega-bundle catalog

**Оценка: 5,8/10.**

### Работает отлично

- North star правильная: каталог — адресная система, не список файлов.
- Browse не меняет active course.
- Есть «Каталог / Пересадки / Маршрут», поиск и meaningful empty states.
- Reference в `hometutor-studio` использует tab semantics и responsive 3→2→1.

### Проблемы

- Runtime реализует single-column tile list
  (`app/ui/library_schedule.py:111`, `:206-210`), а не 3→2→1.
- Tile содержит inline hardcoded colors и размеры (`:121`), обходя tokens.
- Три action columns создаются даже при одном действии (`:139`).
- Без query Catalog показывает длинную иерархию; с query меняет визуальную модель
  на schedule tiles.
- `.panel` снова открывается отдельным markdown fragment (`:220`).

### Рекомендации

- Реализовать 3→2→1.
- Адрес всегда выше CTA и визуально стабильнее статуса.
- Одна карточка — одно primary action; secondary actions в menu.
- Search фильтрует ту же card model.
- Один `SourceAddress` для Library, Tutor, Konspekt, Plan и Mnemo.

## 10. Onboarding и первые десять минут

**Оценка: 4,7/10.**

### Работает отлично

- Сценарии охватывают продукт.
- Мнемополис имеет короткую one-line instruction.
- Tutorial progress сохраняется.

### Критические проблемы

- Tutorial построен как blocking `@st.dialog`
  (`app/ui/tutorial_guide.py:121`). Он просит выполнить действие, одновременно
  блокируя underlying UI.
- `target_anchor` есть в модели, но все главы передают `None`
  (`app/ui/tutorial_chapters.py:15-219`). Walkthrough не привязан к интерфейсу.
- Пользователь видит `US-*`, confidence-панель, SM2 и внутренний язык.
- Полный tutorial около 26 минут, поэтому не решает first-ten-minutes activation.

### Целевой activation journey

1. Выбрать или подтвердить курс.
2. Задать один вопрос.
3. Открыть один источник.
4. Получить tutor explanation.
5. Ответить на один micro-quiz.
6. Увидеть изменение памяти и маршрута.
7. Вернуться на Mission Control с понятным next step.

Использовать nonmodal coach marks: один anchor за раз, Escape/Skip/Back,
persistent progress. Полный feature tour оставить отдельным путеводителем.

## 11. Global navigation, topbar, sidebar, toast и modal

**Оценка: 4,9/10.**

### Работает

- Views сгруппированы.
- Редкие разделы скрываются.
- Есть возврат home и visibility levels.

### Проблемы

- В `app/ui/constants.py:3-19` перечислено 19 views, а primary navigation — один
  selectbox со скрытым label (`app/ui/main.py:315`). Discoverability и sense of
  place недостаточны.
- Sidebar начинается с «Live метрики» и event log
  (`app/ui/sidebar.py:279-285`). Это operational console, а не learner navigation.
- В sidebar смешаны progress, scope, index, backup, tools, events, research,
  notes и expert filters.
- «Focus view» остаётся на английском (`sidebar.py:126`).
- Routing смешивает selectbox, sidebar buttons, session-state navigation и deep
  links.
- Важные mutations иногда подтверждаются только ephemeral toast.

### Рекомендация

Desktop shell:

- persistent rail: `Главная / Учиться / Память / Библиотека`;
- «Учиться»: Tutor, Quiz, Plan;
- «Память»: Mnemo, Konspekt, Flashcards;
- command palette для полного списка views;
- sidebar содержит только context текущего раздела;
- diagnostics доступны в Expert/Developer mode.

Mobile shell: четыре bottom destinations плюс `Ещё`.

## 12. Глобальные дизайн-темы

### 12.1 Палитра и dark mode

- Основной UI принудительно светлый (`.streamlit/config.toml:5`).
- Presets в `app/ui/theme_presets.py` меняют оттенки, но не создают настоящую
  dark semantic theme.
- Мнемополис использует `--kgx-*`, notebook/export —
  `paper/terra/forest/gold`, основной UI — третью систему.
- Переход из Mission Control в Mnemo создаёт резкий luminance cut.

Проверенные пары:

| Пара | Контраст | Вывод |
|---|---:|---|
| SSR `#4a9fd4` / `#ebf5ff` | 2,65:1 | fail для текста |
| notebook terra `#b95631` / `#f7f3ea` | 4,27:1 | fail для маленького текста |
| notebook gold `#c98a3d` / `#f7f3ea` | 2,64:1 | только decoration/large graphics |
| KG muted `#aeb5cf` / `#0e101b` | 9,30:1 | цвет хороший, размер мал |
| KG cyan `#42e8e0` / `#080812` | 13,14:1 | высокий контраст |

Нужны semantic modes `light | dark | spatial-dark`.

### 12.2 Типографика

Текущий UI чрезмерно зависит от `0.63-0.78rem`. Рекомендуемая шкала:

- Display 32/38;
- Page title 24/30;
- Section title 18/24;
- Body 16/24;
- Label 13/18;
- Metadata 12/16 — минимальный meaningful text.

Mastery, retention, XP и duration используют tabular numerals.

### 12.3 Motion language

- 120 ms — hover/focus;
- 180 ms — control/state;
- 240 ms — panel/route transition;
- easing `cubic-bezier(.2,.8,.2,1)`;
- spring только для direct manipulation;
- reduced-motion убирает scale, rotation, z-camera, shimmer и pulse.

### 12.4 Spatial design и depth

Большинство 2D-поверхностей используют одинаковую формулу: rounded card +
border + shadow + gradient. Когда всё поднято, глубина теряет смысл.

Оставить четыре elevation level:

1. canvas/background;
2. content surface;
3. contextual overlay;
4. modal/system interruption.

### 12.5 Consistency 2D / 3D / embedded / export

Объединять нужно семантику, а не буквальные цвета:

- один `SourceAddress`;
- один `MasterySignal`;
- один `NextStep`;
- один `StatusReceipt`;
- единые meanings mastered/due/frontier/gap;
- одинаковый action result в Streamlit и iframe.

Embedded wrappers получают tokens и motion preference от host.

### 12.6 Accessibility

Обязательные проверки:

- keyboard-only end-to-end;
- 200% zoom и reflow;
- screen-reader announcement audit;
- focus not obscured sticky HUD/modal;
- контраст на composited backgrounds;
- status не только цветом;
- touch target sizing;
- nonvisual alternative canvas.

В качестве внешнего стандарта использован WCAG 2.2:
https://www.w3.org/TR/WCAG22/. Для primary controls целевой стандарт продукта —
44×44, хотя Level AA допускает 24×24 с условиями spacing.

### 12.7 Responsive

- KG имеет хорошую структурную основу, но mobile controls малы.
- Основной CSS почти не различает 1366 и 1920; `max-width: 1380px` оставляет
  большие пустые поля на wide display.
- Five-column controls и динамические `st.columns(len(preview))` требуют
  отдельных mobile compositions.
- Library не реализует 3→2→1.

Regression matrix: 1366×768, 1440×900, 1920×1080, 768×1024, 390×844;
light/dark, reduced-motion, 200% zoom и keyboard.

## 13. Приоритеты

### P0 — release blockers

1. Quiz correct-answer leakage.
2. Blocking onboarding без рабочих anchors.
3. AA+ gate: contrast failures, semantic flashcard flip, доступная spatial
   projection.
4. Автоматический keyboard/focus/status audit для custom iframe components.

### P1 — высокий impact

1. Упростить production Mnemo и увеличить controls/type.
2. Заменить global selectbox устойчивой information architecture.
3. Переделать Living Konspekt в reading route.
4. Удалить duplicate Flashcards navigation и iframe scrollbar.
5. Перенести `interactive_quiz` на interaction model `scoped_quiz`.
6. Разделить Adaptive hub и daily detail.
7. Реализовать Library 3→2→1 и общий address component.
8. Разгрузить sidebar и убрать developer language.
9. Ввести настоящий dark mode и semantic bridge к `--kgx-*`.

### P2 — polish

- единые easing/durations;
- меньше pills и декоративных radii;
- icon + accessible label вместо cryptic glyph;
- human-readable chat session names;
- persistent receipts вместо toast-only feedback;
- threshold-based celebration;
- wide-screen composition;
- единая empty/loading/error anatomy.

## 14. Целевая дизайн-система

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

  --control-compact: 32px;
  --control-default: 40px;
  --control-touch: 44px;

  --motion-fast: 120ms;
  --motion-default: 180ms;
  --motion-panel: 240ms;
  --ease-standard: cubic-bezier(.2, .8, .2, 1);
  --focus-ring: 0 0 0 3px var(--color-focus);
}
```

Semantic colors:

```css
--color-canvas;
--color-surface-1;
--color-surface-2;
--color-overlay;
--color-text;
--color-text-muted;
--color-border;
--color-accent;
--color-focus;
--color-status-mastered;
--color-status-due;
--color-status-frontier;
--color-status-gap;
```

Обязательные компоненты:

- `AppShell`;
- `GlobalNav`;
- `PageHeader`;
- `SegmentedControl`;
- `LearningCard`;
- `RouteStopCard`;
- `SourceAddress`;
- `MasterySignal`;
- `QuestionCard`;
- `ReadingRail`;
- `InlineReceipt`;
- `EmptyState`;
- `ExpertDisclosure`.

Для каждого фиксируются default, hover, focus, pressed, disabled, loading,
error, light/dark/spatial, desktop/touch и reduced-motion.

Figma Variables / Styles:

- `Color/Surface/Canvas`;
- `Color/Text/Primary`;
- `Color/Status/Due`;
- `Type/UI/Body`;
- `Type/UI/Metadata`;
- `Effect/Elevation/Contextual`;
- `Motion/Duration/State`.

## 15. Как сохранять мировой уровень

Любая новая поверхность проходит пять gates:

1. data honesty;
2. one dominant next action;
3. accessibility;
4. responsive matrix;
5. motion/performance budget.

Дополнительно:

- screenshot regression для ключевых состояний, не только DOM tests;
- запрет новых hardcoded colors, radii и durations без token;
- каждый spatial signal имеет source и nonvisual representation;
- copy lint не допускает UUID, raw enums, JSON fields и user-story IDs вне
  Expert mode;
- design QA проверяет filled, empty, loading, error и degraded states.

## 16. Финальный вердикт

hometutor уже обладает ядром продукта мирового уровня: Мнемополисом как честной
пространственной моделью обучения. Главный риск — не нехватка идей, а нехватка
редакторской строгости. Сокращение chrome, единая semantic system и закрытие P0
могут поднять продукт примерно с 6,1 до 8+ без добавления новой крупной фичи.
