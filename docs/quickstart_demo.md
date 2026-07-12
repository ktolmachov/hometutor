# Smart Demo — автоматически снятые кадры сценариев

> **Freshness:** снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · freshness gap `206` коммитов.

> Документ собран из YAML-манифестов `doc/scenarios/*.yaml` и скриншотов из `doc/screenshots/final/<scenario_id>/` после `npm run test:e2e:demo` (съём в `doc/screenshots/<RUN>/`; перед этим генератор пересобирает `doc/screenshots/final/`, **ссылки ведут в `final/`**). Не правь вручную — манифесты и `python scripts/generate_demo_doc.py`.

## О чём этот документ

Каждый сценарий здесь — это последовательность **реальных кадров** из Streamlit UI, снятых Playwright'ом в ходе demo-теста. Это доказательство, что продукт делает то, что обещано в [user_scenarios.md](user_scenarios.md) и [quickstart.md](quickstart.md), — не рендеры, не мокапы.

## 🎓 Интерактивный тур внутри приложения — 5 глав

Новый формат Smart Demo доступен прямо в UI: на главном экране нажмите **«Пройти интерактивный тур (5 глав)»**.

- Глава 1: Первый ответ (~3 мин)
- Глава 2: От ответа к обучению (~5 мин)
- Глава 3: Возвращаюсь завтра (~4 мин)
- Глава 4: Flashcards и долгая память (~6 мин)
- Глава 5: Курс под ключ (~8 мин)

Overlay тура показывает текущую главу/шаг, ведёт по экранам и сохраняет прогресс между сессиями.

![Interactive Guide Overlay](screenshots/final/scenario_10/01_home_resume_card.png)

## 🧭 Demo lane — Умный Маршрутизатор

Сценарии 21–22 раскрывают слайды 6–7 защиты как demo-путь: **Умный Маршрутизатор сейчас** показывает один лучший следующий шаг с объяснением, а **Умный Маршрутизатор с ИИ** показывает AI Vision из 5 уровней поверх той же local-first логики.

![Smart Study Router: когнитивный автопилот и логика маршрутизации](screenshots/mastery_engine/mastery_engine_slide_06.png)

<sub>Существующие сценарии ниже сохранены как PR-витрина для внешнего просмотра.</sub>

## Quality gate

Для публикации демо считается готовым только сценарий со статусом `✅ полностью снят`: все slug-и из YAML имеют PNG в `final/`, а прогон оставил `meta.json`. Перед внешним показом запускай:

```bash
npm run demo:validate -- --screenshots-dir doc/screenshots/final --require-screenshots --strict-captures --require-unique-shots
```

Статус `🟡 частично снят` означает, что ссылки есть только на найденные кадры; отсутствующие кадры перечислены прямо в разделе сценария. Статус `⚠️ ещё не снят` означает, что ссылок нет, потому что в `final/` нет PNG-артефактов для этого сценария.

## Оглавление

- [scenario_01 — Первый запуск: от папки до первого ответа](#scenario-01-первый-запуск-от-папки-до-первого-ответа) — ✅
- [scenario_02 — Home Mode Selector: навигация за 30 секунд](#scenario-02-home-mode-selector-навигация-за-30-секунд) — ✅
- [scenario_03 — Ответ → Tutor за один клик](#scenario-03-ответ-→-tutor-за-один-клик) — ✅
- [scenario_04 — Мини-квиз: проверь понимание за 2 мин](#scenario-04-мини-квиз-проверь-понимание-за-2-мин) — ✅
- [scenario_05 — Flashcards: сгенерировать, отредактировать, сохранить](#scenario-05-flashcards-сгенерировать-отредактировать-сохранить) — ✅
- [scenario_06 — SRS: повторение по интервальному алгоритму](#scenario-06-srs-повторение-по-интервальному-алгоритму) — ✅
- [scenario_07 — Прогресс и слабые места](#scenario-07-прогресс-и-слабые-места) — ✅
- [scenario_08 — Доверие к ответу: источники и confidence](#scenario-08-доверие-к-ответу-источники-и-confidence) — ✅
- [scenario_09 — Персональный план обучения](#scenario-09-персональный-план-обучения) — ✅
- [scenario_10 — Возвращение на день 2: resume + soft-recovery](#scenario-10-возвращение-на-день-2-resume-+-soft-recovery) — ✅
- [scenario_11 — Flashcards → экспорт в Anki](#scenario-11-flashcards-→-экспорт-в-anki) — ✅
- [scenario_12 — Quiz → колода карточек](#scenario-12-quiz-→-колода-карточек) — ✅
- [scenario_13 — Course Workspace: полный цикл](#scenario-13-course-workspace-полный-цикл) — ✅
- [scenario_14 — Полный export/sync и восстановление](#scenario-14-полный-export/sync-и-восстановление) — ✅
- [scenario_15 — UX Breakthrough](#scenario-15-ux-breakthrough) — ✅
- [scenario_16 — Интерактивный тур: 5 глав и сохранение прогресса](#scenario-16-интерактивный-тур-5-глав-и-сохранение-прогресса) — ✅
- [scenario_17 — План на сегодня: что изменилось (diff)](#scenario-17-план-на-сегодня-что-изменилось-(diff)) — ✅
- [scenario_18 — Главная как карта возврата: режимы, due и следующий шаг](#scenario-18-главная-как-карта-возврата-режимы-due-и-следующий-шаг) — ✅
- [scenario_19 — Первая сессия: сайдбар, окружение и работоспособность UI](#scenario-19-первая-сессия-сайдбар-окружение-и-работоспособность-ui) — ✅
- [scenario_20 — Адаптивный маршрут тьютора](#scenario-20-адаптивный-маршрут-тьютора) — ✅
- [scenario_21 — Умный Маршрутизатор: один лучший следующий шаг](#scenario-21-умный-маршрутизатор-один-лучший-следующий-шаг) — ✅
- [scenario_22 — Умный Маршрутизатор с ИИ: 5 уровней AI Vision](#scenario-22-умный-маршрутизатор-с-ии-5-уровней-ai-vision) — ✅
- [scenario_23 — SSR Trust: Понятные доказательства маршрута](#scenario-23-ssr-trust-понятные-доказательства-маршрута) — ✅
- [scenario_24 — SSR Pedagogy: Управляемая педагогика](#scenario-24-ssr-pedagogy-управляемая-педагогика) — ✅
- [scenario_25 — Mastery и Graduation: карта освоения](#scenario-25-mastery-и-graduation-карта-освоения) — ✅
- [scenario_26 — Knowledge Graph: персональный подграф](#scenario-26-knowledge-graph-персональный-подграф) — ✅
- [scenario_27 — Incremental reindex: материалы без потери прогресса](#scenario-27-incremental-reindex-материалы-без-потери-прогресса) — ✅
- [scenario_28 — Course Cockpit v2: daily briefing курса](#scenario-28-course-cockpit-v2-daily-briefing-курса) — ✅
- [scenario_29 — Graduation celebration: ceremony overlay](#scenario-29-graduation-celebration-ceremony-overlay) — ✅
- [scenario_30 — SSR micro-outcome receipt: честный чек после шага](#scenario-30-ssr-micro-outcome-receipt-честный-чек-после-шага) — ✅
- [scenario_31 — Честный сбой LLM: circuit breaker и fallback](#scenario-31-честный-сбой-llm-circuit-breaker-и-fallback) — ⚠️
- [scenario_32 — Гость HF Spaces: запуск без установки и ключей](#scenario-32-гость-hf-spaces-запуск-без-установки-и-ключей) — ⚠️
- [scenario_33 — Экспорт живой карты: Knowledge Graph в Markdown](#scenario-33-экспорт-живой-карты-knowledge-graph-в-markdown) — ⚠️
- [scenario_34 — Возврат в таймкод видео: контекст без пересмотра](#scenario-34-возврат-в-таймкод-видео-контекст-без-пересмотра) — ⚠️
- [scenario_35 — Приватность и offline-проверка: данные не покидают устройство](#scenario-35-приватность-и-offline-проверка-данные-не-покидают-устройство) — ⚠️

## Покрытие

| ID | Название | Уровень | Кадров снято | LLM нужен | Статус |
|---|---|---|:---:|:---:|---|
| `scenario_01` | Первый запуск: от папки до первого ответа | 🟢 Первые шаги | 5/5 | нет | ✅ полностью снят |
| `scenario_02` | Home Mode Selector: навигация за 30 секунд | 🟢 Первые шаги | 5/5 | нет | ✅ полностью снят |
| `scenario_03` | Ответ → Tutor за один клик | 🟡 Learning loop | 5/5 | нет | ✅ полностью снят |
| `scenario_04` | Мини-квиз: проверь понимание за 2 мин | 🟡 Learning loop | 4/4 | нет | ✅ полностью снят |
| `scenario_05` | Flashcards: сгенерировать, отредактировать, сохранить | 🔵 Учебный ритм | 4/4 | нет | ✅ полностью снят |
| `scenario_06` | SRS: повторение по интервальному алгоритму | 🟠 Retention engine | 5/5 | нет | ✅ полностью снят |
| `scenario_07` | Прогресс и слабые места | 🟠 Retention engine | 4/4 | нет | ✅ полностью снят |
| `scenario_08` | Доверие к ответу: источники и confidence | 🔵 Trust drill-down | 4/4 | нет | ✅ полностью снят |
| `scenario_09` | Персональный план обучения | 🔴 Orchestration | 5/5 | нет | ✅ полностью снят |
| `scenario_10` | Возвращение на день 2: resume + soft-recovery | 🟠 Retention engine | 4/4 | нет | ✅ полностью снят |
| `scenario_11` | Flashcards → экспорт в Anki | 🔵 Учебный ритм | 3/3 | нет | ✅ полностью снят |
| `scenario_12` | Quiz → колода карточек | 🔵 Учебный ритм | 4/4 | нет | ✅ полностью снят |
| `scenario_13` | Course Workspace: полный цикл | 🔴 Orchestration | 6/6 | нет | ✅ полностью снят |
| `scenario_14` | Полный export/sync и восстановление | 🔴 Orchestration | 4/4 | нет | ✅ полностью снят |
| `scenario_15` | UX Breakthrough | 🟡 Perceived quality | 3/3 | нет | ✅ полностью снят |
| `scenario_16` | Интерактивный тур: 5 глав и сохранение прогресса | 🟢 Первые шаги | 5/5 | нет | ✅ полностью снят |
| `scenario_17` | План на сегодня: что изменилось (diff) | 🔴 Orchestration | 4/4 | нет | ✅ полностью снят |
| `scenario_18` | Главная как карта возврата: режимы, due и следующий шаг | 🟠 Retention engine | 4/4 | нет | ✅ полностью снят |
| `scenario_19` | Первая сессия: сайдбар, окружение и работоспособность UI | 🟢 Первые шаги | 3/3 | нет | ✅ полностью снят |
| `scenario_20` | Адаптивный маршрут тьютора | 🔴 Mastery | 3/3 | нет | ✅ полностью снят |
| `scenario_21` | Умный Маршрутизатор: один лучший следующий шаг | 🔴 Orchestration | 3/3 | нет | ✅ полностью снят |
| `scenario_22` | Умный Маршрутизатор с ИИ: 5 уровней AI Vision | 🧭 Vision | 4/4 | нет | ✅ полностью снят |
| `scenario_23` | SSR Trust: Понятные доказательства маршрута | 🔴 Orchestration | 3/3 | нет | ✅ полностью снят |
| `scenario_24` | SSR Pedagogy: Управляемая педагогика | 🔴 Orchestration | 3/3 | нет | ✅ полностью снят |
| `scenario_25` | Mastery и Graduation: карта освоения | 🔴 Mastery | 4/4 | нет | ✅ полностью снят |
| `scenario_26` | Knowledge Graph: персональный подграф | 🔴 Mastery | 4/4 | нет | ✅ полностью снят |
| `scenario_27` | Incremental reindex: материалы без потери прогресса | 🟠 Retention engine | 4/4 | нет | ✅ полностью снят |
| `scenario_28` | Course Cockpit v2: daily briefing курса | 🔴 Orchestration | 4/4 | нет | ✅ полностью снят |
| `scenario_29` | Graduation celebration: ceremony overlay | 🟡 Perceived quality | 3/3 | нет | ✅ полностью снят |
| `scenario_30` | SSR micro-outcome receipt: честный чек после шага | 🔴 Orchestration | 3/3 | нет | ✅ полностью снят |
| `scenario_31` | Честный сбой LLM: circuit breaker и fallback | 🔵 Trust drill-down | 0/3 | нет | ⚠️ ещё не снят |
| `scenario_32` | Гость HF Spaces: запуск без установки и ключей | 🟢 Первые шаги | 0/3 | нет | ⚠️ ещё не снят |
| `scenario_33` | Экспорт живой карты: Knowledge Graph в Markdown | 🔴 Mastery | 0/3 | нет | ⚠️ ещё не снят |
| `scenario_34` | Возврат в таймкод видео: контекст без пересмотра | 🟠 Retention engine | 0/4 | нет | ⚠️ ещё не снят |
| `scenario_35` | Приватность и offline-проверка: данные не покидают устройство | 🟢 Первые шаги | 0/4 | нет | ⚠️ ещё не снят |


## scenario_01 — Первый запуск: от папки до первого ответа

**🟢 Первые шаги** · ⏱ 5 мин · 👤 Аня, студентка. Скачала hometutor впервые.

**Зачем:** За 5 минут превратить папку с конспектами в поисковую систему по своим материалам
с источниками. Момент, ради которого пользователь решает остаться.

> 🔥 **Wow-момент:** Ответ с confidence 87% и тремя фрагментами из реальных файлов пользователя —
клик по фрагменту открывает подсветку в исходнике.

### Анимированный разбор

![Первый запуск: от папки до первого ответа](screenshots/final/scenario_01/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_01/demo.gif` · 785 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Home Mode Selector: 7 карточек режимов

![Home Mode Selector: 7 карточек режимов](screenshots/final/scenario_01/01_home_mode_selector.png)

_UI встречает семью режимами, а не пустым чатом._

<sub>файл: `doc/screenshots/final/scenario_01/01_home_mode_selector.png` · ⏱ 3s</sub>

#### Шаг 2 — Быстрый ответ: готов принять вопрос

![Быстрый ответ: готов принять вопрос](screenshots/final/scenario_01/02_quick_answer_empty.png)

_Аня спрашивает как есть — без магических промптов._

<sub>файл: `doc/screenshots/final/scenario_01/02_quick_answer_empty.png` · ⏱ 3s</sub>

#### Шаг 3 — Ответ получен: confidence + источники

![Ответ получен: confidence + источники](screenshots/final/scenario_01/03_quick_answer_with_sources.png)

_Ответ — с confidence-оценкой и точными фрагментами из её лекций._

<sub>файл: `doc/screenshots/final/scenario_01/03_quick_answer_with_sources.png` · ⏱ 5s</sub>

#### Шаг 4 — Раскрытые источники с превью

![Раскрытые источники с превью](screenshots/final/scenario_01/04_sources_expanded.png)

_Никаких галлюцинаций: каждый тезис подкреплён фрагментом._

<sub>файл: `doc/screenshots/final/scenario_01/04_sources_expanded.png` · ⏱ 4s</sub>

#### Шаг 5 — Кнопка «Учить эту тему 5 минут»

![Кнопка «Учить эту тему 5 минут»](screenshots/final/scenario_01/05_learn_this_topic_cta.png)

_А если вдруг захотелось разобраться — одна кнопка превращает ответ в учебный разбор._

<sub>файл: `doc/screenshots/final/scenario_01/05_learn_this_topic_cta.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:07.521Z`
- Финиш: `2026-06-20T18:54:12.176Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Положил папку → через 5 минут получил поиск по своим материалам
с источниками. Локально. Бесплатно по privacy.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-1--первый-запуск-от-папки-до-первого-ответа)

---

## scenario_02 — Home Mode Selector: навигация за 30 секунд

**🟢 Первые шаги** · ⏱ 1 мин · 👤 Максим, пользователь второго дня. Проверяет, где что лежит.

**Зачем:** Показать, что главный экран — это сетка режимов с ясной навигацией, а не набор
виджетов-конкурентов.

> 🔥 **Wow-момент:** Два клика — и ты в нужном режиме.

### Анимированный разбор

![Home Mode Selector: навигация за 30 секунд](screenshots/final/scenario_02/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_02/demo.gif` · 658 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Главный экран: карточки режимов

![Главный экран: карточки режимов](screenshots/final/scenario_02/01_home_initial.png)

_Первое, что видит пользователь — основные режимы._

<sub>файл: `doc/screenshots/final/scenario_02/01_home_initial.png` · ⏱ 3s</sub>

#### Шаг 2 — Переход к разделу «Темы»

![Переход к разделу «Темы»](screenshots/final/scenario_02/02_click_topics.png)

_Один клик — одна цель._

<sub>файл: `doc/screenshots/final/scenario_02/02_click_topics.png` · ⏱ 3s</sub>

#### Шаг 3 — Возврат на Home

![Возврат на Home](screenshots/final/scenario_02/03_back_to_home.png)

_Переключение между режимами — через селектор разделов._

<sub>файл: `doc/screenshots/final/scenario_02/03_back_to_home.png` · ⏱ 2s</sub>

#### Шаг 4 — Переход в раздел «Прогресс обучения»

![Переход в раздел «Прогресс обучения»](screenshots/final/scenario_02/04_click_progress.png)

_Прогресс — в одном клике._

<sub>файл: `doc/screenshots/final/scenario_02/04_click_progress.png` · ⏱ 3s</sub>

#### Шаг 5 — SSR Banner на главном экране

![SSR Banner на главном экране](screenshots/final/scenario_02/05_ssr_banner.png)

_Главный экран также подсказывает следующий оптимальный шаг обучения._

<sub>файл: `doc/screenshots/final/scenario_02/05_ssr_banner.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:12.268Z`
- Финиш: `2026-06-20T18:54:16.850Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Home Mode Selector решает pain «10 равных действий вместо одного next step»
(см. CJM moment of truth #10 и #13).

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md)

---

## scenario_03 — Ответ → Tutor за один клик

**🟡 Learning loop** · ⏱ 5 мин · 👤 Аня после scenario_01. Хочет разобраться в теме глубже.

**Зачем:** Один клик превращает поисковый ответ в guided learning session без ручной
сборки промптов. Контекст (тема + исходный вопрос) передаётся автоматически.

> 🔥 **Wow-момент:** Один клик на «Учить эту тему 5 минут» — и Tutor уже знает вопрос,
тему и предлагает структурированный план разбора.

### Анимированный разбор

![Ответ → Tutor за один клик](screenshots/final/scenario_03/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_03/demo.gif` · 735 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Готовый ответ с кнопкой «Учить эту тему 5 минут»

![Готовый ответ с кнопкой «Учить эту тему 5 минут»](screenshots/final/scenario_03/01_answer_with_learn_cta.png)

_Аня видит ответ — и прямо здесь предложение перейти в режим обучения._

<sub>файл: `doc/screenshots/final/scenario_03/01_answer_with_learn_cta.png` · ⏱ 3s</sub>

#### Шаг 2 — Tutor открыт: контекст темы и вопроса сохранён

![Tutor открыт: контекст темы и вопроса сохранён](screenshots/final/scenario_03/02_tutor_context_handoff.png)

_Переход без потери контекста — тема и исходный вопрос уже в Tutor._

<sub>файл: `doc/screenshots/final/scenario_03/02_tutor_context_handoff.png` · ⏱ 4s</sub>

#### Шаг 3 — План разбора темы: 3 шага

![План разбора темы: 3 шага](screenshots/final/scenario_03/03_tutor_topic_plan.png)

_Система предлагает структуру: что объяснить и в каком порядке._

<sub>файл: `doc/screenshots/final/scenario_03/03_tutor_topic_plan.png` · ⏱ 4s</sub>

#### Шаг 4 — Объяснение простыми словами — шаг 1

![Объяснение простыми словами — шаг 1](screenshots/final/scenario_03/04_tutor_simple_explanation.png)

_Первый шаг плана: концепция объяснена без жаргона._

<sub>файл: `doc/screenshots/final/scenario_03/04_tutor_simple_explanation.png` · ⏱ 5s</sub>

#### Шаг 5 — CTA «Следующий шаг: проверь понимание»

![CTA «Следующий шаг: проверь понимание»](screenshots/final/scenario_03/05_tutor_next_step_cta.png)

_Tutor сам предлагает перейти к проверке — мост к мини-квизу._

<sub>файл: `doc/screenshots/final/scenario_03/05_tutor_next_step_cta.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:16.951Z`
- Финиш: `2026-06-20T18:54:24.523Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** RAG-ответ — не конец пути, а точка входа в обучение.
Система сама передаёт контекст, студент не теряет нить.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-3--ответ-tutor-за-один-клик)

---

## scenario_04 — Мини-квиз: проверь понимание за 2 мин

**🟡 Learning loop** · ⏱ 2 мин · 👤 Аня после scenario_03. Хочет убедиться, что поняла тему.

**Зачем:** После объяснения от Tutor — один клик запускает квиз.
Система генерирует вопрос по теме, показывает варианты и даёт
мгновенный feedback. Без переключения контекста.

> 🔥 **Wow-момент:** Вопрос уже по твоей теме — не надо ничего настраивать.
Выбрал ответ — сразу видишь ✅ или ❌ с объяснением.

### Анимированный разбор

![Мини-квиз: проверь понимание за 2 мин](screenshots/final/scenario_04/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_04/demo.gif` · 506 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Вопрос квиза: 3 варианта ответа

![Вопрос квиза: 3 варианта ответа](screenshots/final/scenario_04/01_quiz_question_presented.png)

_Система сформулировала вопрос по теме — Аня выбирает из трёх._

<sub>файл: `doc/screenshots/final/scenario_04/01_quiz_question_presented.png` · ⏱ 3s</sub>

#### Шаг 2 — Выбранный вариант подсвечен

![Выбранный вариант подсвечен](screenshots/final/scenario_04/02_quiz_answer_selected.png)

_Один клик — вариант зафиксирован, ожидание feedback._

<sub>файл: `doc/screenshots/final/scenario_04/02_quiz_answer_selected.png` · ⏱ 2s</sub>

#### Шаг 3 — Feedback: ✅ правильно или ❌ + подсказка

![Feedback: ✅ правильно или ❌ + подсказка](screenshots/final/scenario_04/03_quiz_feedback_correct_or_hint.png)

_Мгновенный ответ с объяснением — не просто «неверно»._

<sub>файл: `doc/screenshots/final/scenario_04/03_quiz_feedback_correct_or_hint.png` · ⏱ 4s</sub>

#### Шаг 4 — CTA: «Создать flashcard» / «Продолжить»

![CTA: «Создать flashcard» / «Продолжить»](screenshots/final/scenario_04/04_quiz_next_action_cta.png)

_Правильно? Идём дальше. Ошиблись? Карточка в SRS-очередь._

<sub>файл: `doc/screenshots/final/scenario_04/04_quiz_next_action_cta.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:24.616Z`
- Финиш: `2026-06-20T18:54:27.135Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Квиз встроен в поток: ответил → понял → проверил.
Нет отдельного «перейти в режим проверки».

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-4--мини-квиз)

---

## scenario_05 — Flashcards: сгенерировать, отредактировать, сохранить

**🔵 Учебный ритм** · ⏱ 5 мин · 👤 Аня, через неделю экзамен. Хочет колоду по главе 3.

**Зачем:** Показать, что hometutor заменяет ручное создание Anki-колод — с preview и редактированием.
Ни одна LLM-генерация не попадает в колоду без человеческой проверки.

> 🔥 **Wow-момент:** Редактируемый preview: правишь или удаляешь плохую карточку ДО сохранения.
Другие генераторы скидывают всё подряд.

### Анимированный разбор

![Flashcards: сгенерировать, отредактировать, сохранить](screenshots/final/scenario_05/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_05/demo.gif` · 529 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Раздел Flashcards: три подвкладки

![Раздел Flashcards: три подвкладки](screenshots/final/scenario_05/01_flashcards_section.png)

_Три зоны: что есть, что создать, что повторить._

<sub>файл: `doc/screenshots/final/scenario_05/01_flashcards_section.png` · ⏱ 3s</sub>

#### Шаг 2 — Создание карточек: загрузка файла

![Создание карточек: загрузка файла](screenshots/final/scenario_05/02_create_new_upload.png)

_5–20 карточек из любого документа._

<sub>файл: `doc/screenshots/final/scenario_05/02_create_new_upload.png` · ⏱ 3s</sub>

#### Шаг 3 — Preview сгенерированных карточек

![Preview сгенерированных карточек](screenshots/final/scenario_05/03_preview_generated.png)

_LLM даёт first draft — человек проверяет._

<sub>файл: `doc/screenshots/final/scenario_05/03_preview_generated.png` · ⏱ 5s</sub>

#### Шаг 4 — Сохранение колоды

![Сохранение колоды](screenshots/final/scenario_05/04_save_deck.png)

_Минимум 5 валидных карточек — колода в базе._

<sub>файл: `doc/screenshots/final/scenario_05/04_save_deck.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:27.229Z`
- Финиш: `2026-06-20T18:54:32.737Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Колода по главе — за минуту, не за час. И ты контролируешь каждую карточку.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-5--flashcards-генерация-и-сохранение)

---

## scenario_06 — SRS: повторение по интервальному алгоритму

**🟠 Retention engine** · ⏱ 4 мин · 👤 Аня через 3 дня. Получила напоминание — пора повторить.

**Зачем:** Система сама знает, когда карточки пора повторить (SM-2 алгоритм).
Аня видит бейдж «К повторению: 12», открывает очередь,
оценивает карточки — система обновляет расписание автоматически.

> 🔥 **Wow-момент:** Система сама отслеживает что и когда повторять.
Аня не думает «надо бы повторить» — бейдж говорит за неё.

### Анимированный разбор

![SRS: повторение по интервальному алгоритму](screenshots/final/scenario_06/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_06/demo.gif` · 770 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Бейдж «К повторению» на главном экране

![Бейдж «К повторению» на главном экране](screenshots/final/scenario_06/01_home_due_badge.png)

_Аня заходит — система уже знает: 12 карточек пора повторить._

<sub>файл: `doc/screenshots/final/scenario_06/01_home_due_badge.png` · ⏱ 3s</sub>

#### Шаг 2 — Очередь повторения открыта: верхняя карточка

![Очередь повторения открыта: верхняя карточка](screenshots/final/scenario_06/02_review_queue_opened.png)

_Одна карточка за раз — без перегрузки._

<sub>файл: `doc/screenshots/final/scenario_06/02_review_queue_opened.png` · ⏱ 3s</sub>

#### Шаг 3 — Карточка раскрыта: ответ + 4 кнопки SM-2

![Карточка раскрыта: ответ + 4 кнопки SM-2](screenshots/final/scenario_06/03_card_flipped_answer.png)

_Оцени насколько помнишь: от «Забыл» до «Легко»._

<sub>файл: `doc/screenshots/final/scenario_06/03_card_flipped_answer.png` · ⏱ 4s</sub>

#### Шаг 4 — Оценка выбрана — карточка уходит из очереди

![Оценка выбрана — карточка уходит из очереди](screenshots/final/scenario_06/04_grade_selected_state_update.png)

_Выбрал «Хорошо» — карточка переносится на +4 дня._

<sub>файл: `doc/screenshots/final/scenario_06/04_grade_selected_state_update.png` · ⏱ 3s</sub>

#### Шаг 5 — Прогресс очереди: «11 осталось, ~4 мин»

![Прогресс очереди: «11 осталось, ~4 мин»](screenshots/final/scenario_06/05_queue_progress.png)

_Видно сколько осталось и когда закончишь — не бесконечный список._

<sub>файл: `doc/screenshots/final/scenario_06/05_queue_progress.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:32.829Z`
- Финиш: `2026-06-20T18:54:37.772Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Не надо вспоминать, что учил. Система помнит и сама напоминает.

> **⚠️ Кадры сняты до Full Circle P0. После завершения P0 интервальный алгоритм получил UI/API-доработки, и часть кадров может не соответствовать текущему поведению. Требуется пересъёмка после Full Circle P0.**

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-6--srs-повторение)

---

## scenario_07 — Прогресс и слабые места

**🟠 Retention engine** · ⏱ 3 мин · 👤 Аня через неделю. Хочет понять, что усвоила, а что нет.

**Зачем:** Прогресс-дашборд показывает mastery по темам, streak и слабые места.
Аня видит не просто «сколько карточек сделано», а конкретные темы
с mastery < 50% и CTA «Разобрать» по каждой.

> 🔥 **Wow-момент:** Не надо гадать что учить дальше — система показывает три слабых темы
и предлагает разобрать прямо сейчас.

### Анимированный разбор

![Прогресс и слабые места](screenshots/final/scenario_07/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_07/demo.gif` · 614 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Полоса прогресса: тема / mastery% / due / streak

![Полоса прогресса: тема / mastery% / due / streak](screenshots/final/scenario_07/01_progress_unified_strip.png)

_Один взгляд — вся картина: что знаешь, что пора повторить._

<sub>файл: `doc/screenshots/final/scenario_07/01_progress_unified_strip.png` · ⏱ 3s</sub>

#### Шаг 2 — График mastery за 7 дней

![График mastery за 7 дней](screenshots/final/scenario_07/02_mastery_timeline.png)

_Кривая роста — видно, что знания накапливаются._

<sub>файл: `doc/screenshots/final/scenario_07/02_mastery_timeline.png` · ⏱ 4s</sub>

#### Шаг 3 — Слабые темы (mastery < 50%) + CTA «Разобрать»

![Слабые темы (mastery < 50%) + CTA «Разобрать»](screenshots/final/scenario_07/03_weak_spots_panel.png)

_Три темы, требующие внимания — система сама их нашла._

<sub>файл: `doc/screenshots/final/scenario_07/03_weak_spots_panel.png` · ⏱ 4s</sub>

#### Шаг 4 — Streak 5 дней + предложение на сегодня

![Streak 5 дней + предложение на сегодня](screenshots/final/scenario_07/04_streak_and_next_action.png)

_Серия не прерывается — система знает когда ты учился._

<sub>файл: `doc/screenshots/final/scenario_07/04_streak_and_next_action.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:37.858Z`
- Финиш: `2026-06-20T18:54:41.388Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Прогресс — это не счётчик карточек, а карта знаний.
Система ведёт к слабым местам сама.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-7--прогресс-и-слабые-места)

---

## scenario_08 — Доверие к ответу: источники и confidence

**🔵 Trust drill-down** · ⏱ 2 мин · 👤 Аня скептически смотрит на ответ. Хочет проверить источники.

**Зачем:** RAG-ответ без источников — это просто текст. С источниками — это документ
с доказательной базой. Аня видит confidence-чип, список источников
с match-score, и может раскрыть фрагмент прямо в интерфейсе.

> 🔥 **Wow-момент:** Нажала на источник — видит точный фрагмент из лекции.
Нет «AI сказал» — есть «профессор написал на стр. 12».

### Анимированный разбор

![Доверие к ответу: источники и confidence](screenshots/final/scenario_08/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_08/demo.gif` · 556 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Ответ + чип «Confidence 87%»

![Ответ + чип «Confidence 87%»](screenshots/final/scenario_08/01_answer_with_confidence_chip.png)

_Система сама показывает насколько уверена в ответе._

<sub>файл: `doc/screenshots/final/scenario_08/01_answer_with_confidence_chip.png` · ⏱ 3s</sub>

#### Шаг 2 — 3 источника с именами файлов и match-score

![3 источника с именами файлов и match-score](screenshots/final/scenario_08/02_three_sources_listed.png)

_Каждый источник — с весом релевантности, не просто список._

<sub>файл: `doc/screenshots/final/scenario_08/02_three_sources_listed.png` · ⏱ 4s</sub>

#### Шаг 3 — Фрагмент источника с подсвеченным текстом

![Фрагмент источника с подсвеченным текстом](screenshots/final/scenario_08/03_source_preview_expanded.png)

_Раскрыла источник — видит точный абзац из лекции._

<sub>файл: `doc/screenshots/final/scenario_08/03_source_preview_expanded.png` · ⏱ 4s</sub>

#### Шаг 4 — Deep link к строке в исходном файле

![Deep link к строке в исходном файле](screenshots/final/scenario_08/04_jump_to_file_at_line.png)

_Хочет читать полный контекст — один клик до файла._

<sub>файл: `doc/screenshots/final/scenario_08/04_jump_to_file_at_line.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:41.478Z`
- Финиш: `2026-06-20T18:54:44.195Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Confidence + источники превращают ответ в доверенный документ.
Галлюцинации проверяемы — это и есть доверие.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-8--доверие-к-ответу)

---

## scenario_09 — Персональный план обучения

**🔴 Orchestration** · ⏱ 5 мин · 👤 Аня в начале недели. Хочет понять что учить на этой неделе.

**Зачем:** Система строит персональный план на неделю на основе weak spots,
истории сессий и целей. Аня видит не просто список тем,
а приоритеты с объяснением «Почему здесь» и CTA на сегодня.

> 🔥 **Wow-момент:** «Сегодня: разобрать X (8 мин)» — система знает твой темп
и строит план под него, а не под идеального студента.

### Анимированный разбор

![Персональный план обучения](screenshots/final/scenario_09/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_09/demo.gif` · 763 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Обзор плана на неделю: 3 приоритетные темы

![Обзор плана на неделю: 3 приоритетные темы](screenshots/final/scenario_09/01_plan_overview.png)

_Система отобрала три темы — не весь учебник, а именно эти._

<sub>файл: `doc/screenshots/final/scenario_09/01_plan_overview.png` · ⏱ 4s</sub>

#### Шаг 2 — «Почему здесь»: weak spot по каждой теме

![«Почему здесь»: weak spot по каждой теме](screenshots/final/scenario_09/02_plan_derived_from_gaps.png)

_Не просто список — объяснение почему эта тема приоритетна._

<sub>файл: `doc/screenshots/final/scenario_09/02_plan_derived_from_gaps.png` · ⏱ 4s</sub>

#### Шаг 3 — Diff с прошлой сессией: что изменилось

![Diff с прошлой сессией: что изменилось](screenshots/final/scenario_09/03_plan_diff_since_last.png)

_План живёт вместе с прогрессом — обновился с последней сессии._

<sub>файл: `doc/screenshots/final/scenario_09/03_plan_diff_since_last.png` · ⏱ 3s</sub>

#### Шаг 4 — «Сегодня: разобрать X (8 мин)»

![«Сегодня: разобрать X (8 мин)»](screenshots/final/scenario_09/04_plan_today_action.png)

_Одно действие на сегодня — не список на неделю вперёд._

<sub>файл: `doc/screenshots/final/scenario_09/04_plan_today_action.png` · ⏱ 3s</sub>

#### Шаг 5 — Корректировка приоритета → пересчёт плана

![Корректировка приоритета → пересчёт плана](screenshots/final/scenario_09/05_plan_accepts_adjust.png)

_Сдвинула тему вниз — план пересчитался мгновенно._

<sub>файл: `doc/screenshots/final/scenario_09/05_plan_accepts_adjust.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:44.286Z`
- Финиш: `2026-06-20T18:54:48.358Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Персональный план — это не расписание, а живой маршрут.
Он меняется с твоим прогрессом, без ручной настройки.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-9--персональный-план)

---

## scenario_10 — Возвращение на день 2: resume + soft-recovery

**🟠 Retention engine** · ⏱ 4 мин · 👤 Аня после паузы. Хочет быстро восстановить ритм без перегруза.

**Зачем:** Показать, что после перерыва система даёт мягкий план возврата:
resume-карта, дозированная due-очередь и сохранённый прогресс после reindex.

> 🔥 **Wow-момент:** Просроченные повторения не обрушиваются сразу —
система распределяет нагрузку и сохраняет мотивацию.

### Анимированный разбор

![Возвращение на день 2: resume + soft-recovery](screenshots/final/scenario_10/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_10/demo.gif` · 586 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Resume-карта на главной

![Resume-карта на главной](screenshots/final/scenario_10/01_home_resume_card.png)

_Сразу видно, откуда продолжить и какой следующий шаг._

<sub>файл: `doc/screenshots/final/scenario_10/01_home_resume_card.png` · ⏱ 3s</sub>

#### Шаг 2 — План на сегодня с diff «что изменилось»

![План на сегодня с diff «что изменилось»](screenshots/final/scenario_10/02_plan_diff_today.png)

_План подстроился под паузу и текущий контекст._

<sub>файл: `doc/screenshots/final/scenario_10/02_plan_diff_today.png` · ⏱ 4s</sub>

#### Шаг 3 — Due-очередь после пропуска без перегруза

![Due-очередь после пропуска без перегруза](screenshots/final/scenario_10/03_due_queue_soft_recovery.png)

_Очередь распределена мягко, без лавины overdue._

<sub>файл: `doc/screenshots/final/scenario_10/03_due_queue_soft_recovery.png` · ⏱ 4s</sub>

#### Шаг 4 — Бейдж обновления профиля после reindex

![Бейдж обновления профиля после reindex](screenshots/final/scenario_10/04_reindex_profile_badge.png)

_Учебное состояние сохраняется после обновления индекса._

<sub>файл: `doc/screenshots/final/scenario_10/04_reindex_profile_badge.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:48.448Z`
- Финиш: `2026-06-20T18:54:52.860Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** На следующий день можно просто вернуться и продолжить с нужного шага.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-10--day-2-resume-и-soft-recovery)

---

## scenario_11 — Flashcards → экспорт в Anki

**🔵 Учебный ритм** · ⏱ 3 мин · 👤 Аня хочет забрать колоду в Anki для внешнего повторения.

**Зачем:** Показать end-to-end путь от локальной колоды к экспорту, без потери структуры карточек.

> 🔥 **Wow-момент:** Один клик формирует пакет экспорта, который готов к импорту в Anki.

### Анимированный разбор

![Flashcards → экспорт в Anki](screenshots/final/scenario_11/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_11/demo.gif` · 284 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Колода готова к экспорту

![Колода готова к экспорту](screenshots/final/scenario_11/01_flashcards_deck_ready.png)

_Карточки уже сохранены и доступны для выгрузки._

<sub>файл: `doc/screenshots/final/scenario_11/01_flashcards_deck_ready.png` · ⏱ 3s</sub>

#### Шаг 2 — Кнопка экспорта в Anki

![Кнопка экспорта в Anki](screenshots/final/scenario_11/02_export_button.png)

_Экспорт запускается из интерфейса без дополнительных шагов._

<sub>файл: `doc/screenshots/final/scenario_11/02_export_button.png` · ⏱ 3s</sub>

#### Шаг 3 — Подтверждение успешного экспорта

![Подтверждение успешного экспорта](screenshots/final/scenario_11/03_export_success.png)

_Система сообщает, что пакет для Anki сформирован._

<sub>файл: `doc/screenshots/final/scenario_11/03_export_success.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:52.960Z`
- Финиш: `2026-06-20T18:54:55.517Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Локальная практика и внешний инструмент повторения работают в одной цепочке.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-11--anki-export)

---

## scenario_12 — Quiz → колода карточек

**🔵 Учебный ритм** · ⏱ 4 мин · 👤 Аня хочет превратить ошибки из квиза в карточки на повторение.

**Зачем:** Показать цикл «проверка знаний → автоматическое усиление слабых мест».

> 🔥 **Wow-момент:** Результаты квиза сразу преобразуются в колоду для интервального повторения.

### Анимированный разбор

![Quiz → колода карточек](screenshots/final/scenario_12/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_12/demo.gif` · 427 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Итоги квиза по теме

![Итоги квиза по теме](screenshots/final/scenario_12/01_quiz_summary.png)

_Видны сильные и слабые концепты._

<sub>файл: `doc/screenshots/final/scenario_12/01_quiz_summary.png` · ⏱ 3s</sub>

#### Шаг 2 — CTA «Сделать колоду из квиза»

![CTA «Сделать колоду из квиза»](screenshots/final/scenario_12/02_convert_to_deck.png)

_Переход к карточкам запускается напрямую из summary._

<sub>файл: `doc/screenshots/final/scenario_12/02_convert_to_deck.png` · ⏱ 3s</sub>

#### Шаг 3 — Предпросмотр карточек из ошибок

![Предпросмотр карточек из ошибок](screenshots/final/scenario_12/03_generated_cards_preview.png)

_Можно проверить и отредактировать карточки перед сохранением._

<sub>файл: `doc/screenshots/final/scenario_12/03_generated_cards_preview.png` · ⏱ 4s</sub>

#### Шаг 4 — Колода сохранена и готова к review

![Колода сохранена и готова к review](screenshots/final/scenario_12/04_saved_deck_review_ready.png)

_Новая колода сразу попадает в цикл повторений._

<sub>файл: `doc/screenshots/final/scenario_12/04_saved_deck_review_ready.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:55.604Z`
- Финиш: `2026-06-20T18:54:58.490Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Ошибки становятся учебным активом, а не тупиком.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-12--quiz-в-деck)

---

## scenario_13 — Course Workspace: полный цикл

**🔴 Orchestration** · ⏱ 8 мин · 👤 Аня запускает обучение по целому курсу из папки.

**Зачем:** Показать весь pipeline курса: активация области, scoped-вопросы, план, карточки,
tutor-поддержка и сигнал mastery/graduation.

> 🔥 **Wow-момент:** За одну сессию проходит полный цикл «курс активирован → освоение подтверждено».

### Анимированный разбор

![Course Workspace: полный цикл](screenshots/final/scenario_13/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_13/demo.gif` · 875 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Активация папки как курса

![Активация папки как курса](screenshots/final/scenario_13/01_activate_course_scope.png)

_Курс выбирается в Темах и становится активной областью._

<sub>файл: `doc/screenshots/final/scenario_13/01_activate_course_scope.png` · ⏱ 4s</sub>

#### Шаг 2 — Scoped быстрый ответ внутри курса

![Scoped быстрый ответ внутри курса](screenshots/final/scenario_13/02_scoped_quick_answer.png)

_Запросы автоматически ограничены материалами курса._

<sub>файл: `doc/screenshots/final/scenario_13/02_scoped_quick_answer.png` · ⏱ 4s</sub>

#### Шаг 3 — План изучения курса

![План изучения курса](screenshots/final/scenario_13/03_course_plan.png)

_План формируется на основе структуры и текущего прогресса._

<sub>файл: `doc/screenshots/final/scenario_13/03_course_plan.png` · ⏱ 4s</sub>

#### Шаг 4 — Генерация карточек курса

![Генерация карточек курса](screenshots/final/scenario_13/04_course_flashcards.png)

_Карточки запускают закрепление ключевых концептов._

<sub>файл: `doc/screenshots/final/scenario_13/04_course_flashcards.png` · ⏱ 4s</sub>

#### Шаг 5 — Маршрут «Не знаю» через Tutor

![Маршрут «Не знаю» через Tutor](screenshots/final/scenario_13/05_tutor_unknown_recovery.png)

_Тьютор помогает пройти сложные места без срыва сессии._

<sub>файл: `doc/screenshots/final/scenario_13/05_tutor_unknown_recovery.png` · ⏱ 4s</sub>

#### Шаг 6 — Dashboard курса и mastery

![Dashboard курса и mastery](screenshots/final/scenario_13/06_course_mastery_dashboard.png)

_Видно рост mastery и сигнал graduation по курсу._

<sub>файл: `doc/screenshots/final/scenario_13/06_course_mastery_dashboard.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:54:58.580Z`
- Финиш: `2026-06-20T18:55:03.622Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Course Mode делает обучение управляемым и измеримым на уровне целой папки.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-13--course-workspace-цикл)

---

## scenario_14 — Полный export/sync и восстановление

**🔴 Orchestration** · ⏱ 5 мин · 👤 Аня переносит учебное состояние между устройствами.

**Зачем:** Проверить, что прогресс, карточки и профиль можно безопасно экспортировать и восстановить.

> 🔥 **Wow-момент:** Полный пакет sync восстанавливает состояние обучения без ручной сборки данных.

### Анимированный разбор

![Полный export/sync и восстановление](screenshots/final/scenario_14/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_14/demo.gif` · 542 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Открыты expert controls синхронизации

![Открыты expert controls синхронизации](screenshots/final/scenario_14/01_open_sync_controls.png)

_В одном месте собраны export/import действия._

<sub>файл: `doc/screenshots/final/scenario_14/01_open_sync_controls.png` · ⏱ 3s</sub>

#### Шаг 2 — Экспорт полного sync-bundle

![Экспорт полного sync-bundle](screenshots/final/scenario_14/02_export_bundle.png)

_Файл включает learner state, прогресс и учебные артефакты._

<sub>файл: `doc/screenshots/final/scenario_14/02_export_bundle.png` · ⏱ 3s</sub>

#### Шаг 3 — Импорт и восстановление

![Импорт и восстановление](screenshots/final/scenario_14/03_import_bundle.png)

_После импорта система подтверждает восстановление состояния._

<sub>файл: `doc/screenshots/final/scenario_14/03_import_bundle.png` · ⏱ 4s</sub>

#### Шаг 4 — Проверка после restore

![Проверка после restore](screenshots/final/scenario_14/04_post_restore_validation.png)

_Resume, due-очередь и прогресс доступны сразу._

<sub>файл: `doc/screenshots/final/scenario_14/04_post_restore_validation.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:55:03.712Z`
- Финиш: `2026-06-20T18:55:06.280Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Экосистема обучения переносима: можно продолжить с того же места на другом окружении.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-14--full-sync-export-import)

---

## scenario_15 — UX Breakthrough

**🟡 Perceived quality** · ⏱ 2 мин · 👤 Пользователь уже получил пользу от продукта и теперь оценивает скорость, плавность и мотивацию.

**Зачем:** Зафиксировать UX-wave как отдельный demo-пакет, чтобы сценарий 15 не был
потерян между пользовательскими историями и инженерными parser/property-test
артефактами.

> 🔥 **Wow-момент:** Продукт не просто работает: ожидание, handoff, celebration и аналитика сессии
ощущаются как цельный учебный ритм.

### Анимированный разбор

![UX Breakthrough](screenshots/final/scenario_15/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_15/demo.gif` · 435 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Skeleton/progressive reveal вместо немого ожидания

![Skeleton/progressive reveal вместо немого ожидания](screenshots/final/scenario_15/01_wait_ux.png)

_Пользователь видит первый полезный сигнал меньше чем за две секунды._

<sub>файл: `doc/screenshots/final/scenario_15/01_wait_ux.png` · ⏱ 4s</sub>

#### Шаг 2 — Переход Q&A → Tutor без потери контекста

![Переход Q&A → Tutor без потери контекста](screenshots/final/scenario_15/02_tutor_handoff.png)

_Тьютор знает вопрос, тему и источники, с которыми пришёл пользователь._

<sub>файл: `doc/screenshots/final/scenario_15/02_tutor_handoff.png` · ⏱ 4s</sub>

#### Шаг 3 — Мотивационный receipt после учебного шага

![Мотивационный receipt после учебного шага](screenshots/final/scenario_15/03_progress_receipt.png)

_Система показывает не только действие, но и образовательный результат._

<sub>файл: `doc/screenshots/final/scenario_15/03_progress_receipt.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:55:06.369Z`
- Финиш: `2026-06-20T18:56:02.871Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** UX Breakthrough — cross-feature слой качества, а не отдельный режим обучения.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-15--ux-breakthrough)

---

## scenario_16 — Интерактивный тур: 5 глав и сохранение прогресса

**🟢 Первые шаги** · ⏱ 4 мин · 👤 Аня в первый день — хочет понять продукт без длинного README.

**Зачем:** Показать guided onboarding: overlay с главами, шагами внутри главы и возобновление тура
после перезагрузки страницы.

> 🔥 **Wow-момент:** Лента «Тур: глава N из 5» и кнопка «Продолжить тур» после reload — доказательство persistence.

### Анимированный разбор

![Интерактивный тур: 5 глав и сохранение прогресса](screenshots/final/scenario_16/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_16/demo.gif` · 460 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Главная: лента тура и CTA «Пройти интерактивный тур»

![Главная: лента тура и CTA «Пройти интерактивный тур»](screenshots/final/scenario_16/01_home_tour_entry.png)

_Система сама предлагает структурированный путь из пяти глав._

<sub>файл: `doc/screenshots/final/scenario_16/01_home_tour_entry.png` · ⏱ 3s</sub>

#### Шаг 2 — Глава 1: пример вопроса в Quick Answer

![Глава 1: пример вопроса в Quick Answer](screenshots/final/scenario_16/02_chapter1_practice_step.png)

_Тур ведёт через реальный сценарий первого ответа, а не через текст инструкции._

<sub>файл: `doc/screenshots/final/scenario_16/02_chapter1_practice_step.png` · ⏱ 4s</sub>

#### Шаг 3 — Глава 1: шаг про источники и доверие

![Глава 1: шаг про источники и доверие](screenshots/final/scenario_16/03_chapter1_trust_step.png)

_Пользователь видит, что ответ нужно проверять по фрагментам и confidence._

<sub>файл: `doc/screenshots/final/scenario_16/03_chapter1_trust_step.png` · ⏱ 4s</sub>

#### Шаг 4 — Глава 2: переход к обучению с тьютором

![Глава 2: переход к обучению с тьютором](screenshots/final/scenario_16/04_chapter2_overlay.png)

_После первого ответа — логичный мост к учебному режиму._

<sub>файл: `doc/screenshots/final/scenario_16/04_chapter2_overlay.png` · ⏱ 4s</sub>

#### Шаг 5 — После перезагрузки: прогресс главы 2 сохранён

![После перезагрузки: прогресс главы 2 сохранён](screenshots/final/scenario_16/05_resume_after_reload.png)

_Продолжение тура с того же места — без потери контекста._

<sub>файл: `doc/screenshots/final/scenario_16/05_resume_after_reload.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:02.965Z`
- Финиш: `2026-06-20T18:56:08.773Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Онбординг не одноразовый экран: это сопровождение с прогрессом между сессиями.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-16--интерактивный-тур-5-глав)

---

## scenario_17 — План на сегодня: что изменилось (diff)

**🔴 Orchestration** · ⏱ 3 мин · 👤 Марк, вторая неделя — план перестроился после паузы и повторений.

**Зачем:** Показать прозрачность адаптивного плана: блок «Что изменилось в плане» с явными
добавленными и исчезнувшими концептами.

> 🔥 **Wow-момент:** Два списка — «появились» и «исчезли» — снимают тревогу «почему план другой».

### Анимированный разбор

![План на сегодня: что изменилось (diff)](screenshots/final/scenario_17/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_17/demo.gif` · 543 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Tutor: блок «Адаптивный план и прогноз»

![Tutor: блок «Адаптивный план и прогноз»](screenshots/final/scenario_17/01_tutor_plan_header.png)

_План на сегодня доступен рядом с основным учебным потоком._

<sub>файл: `doc/screenshots/final/scenario_17/01_tutor_plan_header.png` · ⏱ 3s</sub>

#### Шаг 2 — Развёрнутый Adaptive Daily Plan

![Развёрнутый Adaptive Daily Plan](screenshots/final/scenario_17/02_plan_detail_open.png)

_Видны шаги дня — не абстрактный todo, а привязка к обучению._

<sub>файл: `doc/screenshots/final/scenario_17/02_plan_detail_open.png` · ⏱ 3s</sub>

#### Шаг 3 — Раскрыт «Что изменилось в плане»

![Раскрыт «Что изменилось в плане»](screenshots/final/scenario_17/03_delta_expander.png)

_Один клик — и видна дельта относительно прошлой версии плана._

<sub>файл: `doc/screenshots/final/scenario_17/03_delta_expander.png` · ⏱ 3s</sub>

#### Шаг 4 — Списки «появились» и «исчезли из шагов»

![Списки «появились» и «исчезли из шагов»](screenshots/final/scenario_17/04_added_removed_lists.png)

_Конкретные концепты, а не общие слова о пересчёте._

<sub>файл: `doc/screenshots/final/scenario_17/04_added_removed_lists.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:08.872Z`
- Финиш: `2026-06-20T18:56:12.877Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Персонализация не чёрный ящик: дельта плана читается как changelog.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-17--что-изменилось-в-плане-diff)

---

## scenario_18 — Главная как карта возврата: режимы, due и следующий шаг

**🟠 Retention engine** · ⏱ 2 мин · 👤 Аня утром: нужен один экран, откуда видно «что сегодня» без рыскания по меню.

**Зачем:** Закрепить образ Home как хаба удержания: шесть режимов, вход к повторениям и экран
прогресса с явным следующим действием.

> 🔥 **Wow-момент:** С «главной» можно попасть и в очередь повторений, и в сводку дня без длинной навигации.

### Анимированный разбор

![Главная как карта возврата: режимы, due и следующий шаг](screenshots/final/scenario_18/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_18/demo.gif` · 572 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Шесть режимов на Home

![Шесть режимов на Home](screenshots/final/scenario_18/01_home_modes_hub.png)

_Не пустой чат — выбор траектории: ответ, тьютор, карточки, прогресс._

<sub>файл: `doc/screenshots/final/scenario_18/01_home_modes_hub.png` · ⏱ 3s</sub>

#### Шаг 2 — Flashcards: поверхность повторений

![Flashcards: поверхность повторений](screenshots/final/scenario_18/02_flashcards_due_surface.png)

_Очередь SM-2 — отдельный режим с понятным входом с главной._

<sub>файл: `doc/screenshots/final/scenario_18/02_flashcards_due_surface.png` · ⏱ 3s</sub>

#### Шаг 3 — Прогресс: снимок дня и CTA

![Прогресс: снимок дня и CTA](screenshots/final/scenario_18/03_progress_next_actions.png)

_Видно, что делать дальше после быстрого обзора метрик._

<sub>файл: `doc/screenshots/final/scenario_18/03_progress_next_actions.png` · ⏱ 3s</sub>

#### Шаг 4 — Возврат на Home

![Возврат на Home](screenshots/final/scenario_18/04_back_to_home_rhythm.png)

_Пользователь снова на хабе — цикл «узнал → сделал → вернулся» замыкается._

<sub>файл: `doc/screenshots/final/scenario_18/04_back_to_home_rhythm.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:12.966Z`
- Финиш: `2026-06-20T18:56:18.664Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Retention начинается с первого экрана: due, план и режимы — в одной картине.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-18--главная-карта-возврата)

---

## scenario_19 — Первая сессия: сайдбар, окружение и работоспособность UI

**🟢 Первые шаги** · ⏱ 1 мин · 👤 Максим после клонирования репо — проверяет, что UI живой и подсказки по .env на месте.

**Зачем:** Показать слой проверки окружения: при отсутствии ключей в .env может отображаться
предупреждение; при валидной конфигурации — чистый рабочий интерфейс.

> 🔥 **Wow-момент:** Пользователь не остаётся с пустым экраном: есть якорные виджеты и текст помощи по ключам.

### Анимированный разбор

![Первая сессия: сайдбар, окружение и работоспособность UI](screenshots/final/scenario_19/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_19/demo.gif` · 395 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Основной UI после онбординга

![Основной UI после онбординга](screenshots/final/scenario_19/01_main_view_ready.png)

_Приложение загрузилось; режимы и переключатель разделов доступны._

<sub>файл: `doc/screenshots/final/scenario_19/01_main_view_ready.png` · ⏱ 3s</sub>

#### Шаг 2 — Сайдбар: контекст конфигурации

![Сайдбар: контекст конфигурации](screenshots/final/scenario_19/02_sidebar_env_context.png)

_Здесь могут отображаться предупреждения о ключах API или статус провайдера._

<sub>файл: `doc/screenshots/final/scenario_19/02_sidebar_env_context.png` · ⏱ 3s</sub>

#### Шаг 3 — Home: карточки режимов

![Home: карточки режимов](screenshots/final/scenario_19/03_mode_cards_confirmed.png)

_Подтверждение, что стек поднят и главный сценарий можно начинать._

<sub>файл: `doc/screenshots/final/scenario_19/03_mode_cards_confirmed.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:18.763Z`
- Финиш: `2026-06-20T18:56:23.174Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Guided start дополняется явной диагностикой конфигурации в боковой панели.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-19--проверка-окружения-и-сайдбар)

---

## scenario_20 — Адаптивный маршрут тьютора

**🔴 Mastery** · ⏱ 3 мин · 👤 Аня в середине курса, уже с накопленным mastery и историей quiz.

**Зачем:** Показать отличие PedagogicalRouter от Smart Study Router: тьютор выбирает
следующий turn внутри сессии, а SSR выбирает следующий шаг между сессиями.

> 🔥 **Wow-момент:** После ошибки пользователь получает hint и следующий учебный ход, а не тупик
или случайное переключение режима.

### Анимированный разбор

![Адаптивный маршрут тьютора](screenshots/final/scenario_20/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_20/demo.gif` · 430 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Tutor открыт с активной темой

![Tutor открыт с активной темой](screenshots/final/scenario_20/01_open_tutor_with_topic.png)

_Пользователь приходит не в пустой чат, а в учебную сессию с контекстом._

<sub>файл: `doc/screenshots/final/scenario_20/01_open_tutor_with_topic.png` · ⏱ 4s</sub>

#### Шаг 2 — Педагогический роутер выбирает turn

![Педагогический роутер выбирает turn](screenshots/final/scenario_20/02_micro_quiz_or_explanation.png)

_Система предлагает объяснение, проверку или разбор в зависимости от состояния._

<sub>файл: `doc/screenshots/final/scenario_20/02_micro_quiz_or_explanation.png` · ⏱ 5s</sub>

#### Шаг 3 — После ответа есть следующий шаг

![После ответа есть следующий шаг](screenshots/final/scenario_20/03_after_answer_next_step.png)

_Ошибка ведёт к hint и recovery, а успех — к закреплению или новой теме._

<sub>файл: `doc/screenshots/final/scenario_20/03_after_answer_next_step.png` · ⏱ 5s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:23.265Z`
- Финиш: `2026-06-20T18:56:27.742Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Адаптивный тьютор удерживает учебную сессию в цикле explain → quiz → review,
не заставляя пользователя вручную выбирать педагогическую тактику.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-20--адаптивный-маршрут-тьютора)

---

## scenario_21 — Умный Маршрутизатор: один лучший следующий шаг

**🔴 Orchestration** · ⏱ 1 мин · 👤 Аня открыла приложение утром и хочет понять, что делать сейчас.

**Зачем:** Показать killer-фичу из слайда 6: система не оставляет пользователя перед
набором режимов, а предлагает один лучший следующий шаг, объясняет
«почему сейчас» и оставляет безопасные альтернативы.

> 🔥 **Wow-момент:** «Сейчас важнее...» — продукт превращается из набора вкладок в когнитивный
автопилот: следующий шаг виден сразу, причина читается человеческим языком.

### Анимированный разбор

![Умный Маршрутизатор: один лучший следующий шаг](screenshots/final/scenario_21/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_21/demo.gif` · 404 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Умный помощник: следующий шаг с объяснением

![Умный помощник: следующий шаг с объяснением](screenshots/final/scenario_21/01_smart_study_router_card.png)

_Система рекомендует один лучший следующий шаг и объясняет, почему именно сейчас._

<sub>файл: `doc/screenshots/final/scenario_21/01_smart_study_router_card.png` · ⏱ 4s</sub>

#### Шаг 2 — Почему сейчас + безопасные альтернативы

![Почему сейчас + безопасные альтернативы](screenshots/final/scenario_21/02_router_reason_and_alternatives.png)

_Главная CTA не прячет другие маршруты: быстрый ответ, тьютор, quiz и прогресс остаются рядом._

<sub>файл: `doc/screenshots/final/scenario_21/02_router_reason_and_alternatives.png` · ⏱ 4s</sub>

#### Шаг 3 — Краткий след решения роутера

![Краткий след решения роутера](screenshots/final/scenario_21/03_router_trace_open.png)

_Пользователь может раскрыть, какие локальные сигналы стояли за рекомендацией._

<sub>файл: `doc/screenshots/final/scenario_21/03_router_trace_open.png` · ⏱ 3s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:27.830Z`
- Финиш: `2026-06-20T18:56:32.081Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Умный Маршрутизатор снижает когнитивную нагрузку выбора: пользователь видит
маршрут, причину и CTA вместо ручного перебора режимов.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-21--умный-маршрутизатор-один-лучший-следующий-шаг)

---

## scenario_22 — Умный Маршрутизатор с ИИ: 5 уровней AI Vision

**🧭 Vision** · ⏱ 2 мин · 👤 Product demo: показать следующий уровень SSR без обещания, что все AI-уровни уже включены.

**Зачем:** Показать следующий ход из слайда 7: текущий deterministic router остаётся
надёжной базой, а поверх него постепенно включаются МО-персонализация,
LLM-объяснения, недельный план, граф prerequisites и feedback loop.

> 🔥 **Wow-момент:** Роутер перестаёт быть «умным будильником» и становится персональным учебным
проводником: он знает, что повторить сейчас, что отложить и почему следующая
тема зависит от предыдущей.

### Анимированный разбор

![Умный Маршрутизатор с ИИ: 5 уровней AI Vision](screenshots/final/scenario_22/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_22/demo.gif` · 801 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — AI Vision: от правил к персональному проводнику

![AI Vision: от правил к персональному проводнику](screenshots/final/scenario_22/01_ai_vision_overview.png)

_Базовый SSR остаётся страховочной сеткой, а AI-уровни добавляются поверх него._

<sub>файл: `doc/screenshots/final/scenario_22/01_ai_vision_overview.png` · ⏱ 4s</sub>

#### Шаг 2 — Уровни 1–2: локальная память + живое объяснение

![Уровни 1–2: локальная память + живое объяснение](screenshots/final/scenario_22/02_levels_1_2_personal_memory.png)

_ML меняет приоритеты по кривой забывания, LLM объясняет решение человеческим языком._

<sub>файл: `doc/screenshots/final/scenario_22/02_levels_1_2_personal_memory.png` · ⏱ 5s</sub>

#### Шаг 3 — Уровни 3–4: недельный план + граф prerequisites

![Уровни 3–4: недельный план + граф prerequisites](screenshots/final/scenario_22/03_levels_3_4_planner_graph.png)

_Система ведёт дальше одного клика и не предлагает сложную тему раньше базовой._

<sub>файл: `doc/screenshots/final/scenario_22/03_levels_3_4_planner_graph.png` · ⏱ 5s</sub>

#### Шаг 4 — Уровень 5: feedback loop

![Уровень 5: feedback loop](screenshots/final/scenario_22/04_level_5_feedback_loop.png)

_Если пользователь отклоняет рекомендации, стратегия меняется и остаётся объяснимой._

<sub>файл: `doc/screenshots/final/scenario_22/04_level_5_feedback_loop.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:32.175Z`
- Финиш: `2026-06-20T18:56:33.701Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** SSR AI Vision — это не отдельный чат-бот, а следующий слой над учебным циклом:
правила дают предсказуемость, МО даёт персонализацию, LLM даёт понятное объяснение.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-22--умный-маршрутизатор-с-ии-5-уровней-ai-vision)

---

## scenario_23 — SSR Trust: Понятные доказательства маршрута

**🔴 Orchestration** · ⏱ 2 мин · 👤 Марк хочет понимать, почему SSR выбрал именно этот следующий шаг.

**Зачем:** Показать trust-уровень Smart Study Router: рекомендация должна быть не
только полезной, но и объяснимой через локальные сигналы, альтернативы и
короткий evidence ledger.

> 🔥 **Wow-момент:** Пользователь видит не магический совет, а конкретную причину: какие сигналы
сработали, какие действия были альтернативами и почему они не выбраны сейчас.

### Анимированный разбор

![SSR Trust: Понятные доказательства маршрута](screenshots/final/scenario_23/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_23/demo.gif` · 404 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — SSR показывает следующий шаг и короткую причину

![SSR показывает следующий шаг и короткую причину](screenshots/final/scenario_23/01_recommendation_with_reason.png)

_Рекомендация начинается с простого объяснения, привязанного к локальному состоянию._

<sub>файл: `doc/screenshots/final/scenario_23/01_recommendation_with_reason.png` · ⏱ 4s</sub>

#### Шаг 2 — Evidence Panel: сигналы и альтернативы

![Evidence Panel: сигналы и альтернативы](screenshots/final/scenario_23/02_evidence_panel.png)

_Пользователь раскрывает доказательства и видит, почему выбрано именно это действие._

<sub>файл: `doc/screenshots/final/scenario_23/02_evidence_panel.png` · ⏱ 5s</sub>

#### Шаг 3 — Local-first доверие

![Local-first доверие](screenshots/final/scenario_23/03_local_first_trust.png)

_Все доказательства берутся из локального learner state, без облачного профиля._

<sub>файл: `doc/screenshots/final/scenario_23/03_local_first_trust.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:33.788Z`
- Финиш: `2026-06-20T18:56:38.056Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** SSR Trust превращает рекомендацию в проверяемое решение. Доверие строится на
локальных данных, прозрачных правилах и видимых tradeoffs.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-23--ssr-trust-понятные-доказательства-маршрута)

---

## scenario_24 — SSR Pedagogy: Управляемая педагогика

**🔴 Orchestration** · ⏱ 3 мин · 👤 Аня готовится к экзамену и хочет управлять балансом повторения, восстановления и нового материала.

**Зачем:** Показать педагогический слой Smart Study Router: пользователь должен видеть,
зачем система предлагает действие и какие последствия будут у смены
приоритетов.

> 🔥 **Wow-момент:** SSR объясняет не только «почему сейчас», но и «зачем педагогически»: закрепить
старое, восстановить пробел или начать новую тему.

### Анимированный разбор

![SSR Pedagogy: Управляемая педагогика](screenshots/final/scenario_24/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_24/demo.gif` · 402 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Педагогическая метка на SSR-карточке

![Педагогическая метка на SSR-карточке](screenshots/final/scenario_24/01_pedagogy_label.png)

_Рекомендация сразу показывает тип действия: retention, recovery или new learning._

<sub>файл: `doc/screenshots/final/scenario_24/01_pedagogy_label.png` · ⏱ 4s</sub>

#### Шаг 2 — Visible tradeoffs

![Visible tradeoffs](screenshots/final/scenario_24/02_tradeoff_explanation.png)

_Система объясняет, что произойдёт, если отложить повторение или выбрать новую тему._

<sub>файл: `doc/screenshots/final/scenario_24/02_tradeoff_explanation.png` · ⏱ 5s</sub>

#### Шаг 3 — Learner steering

![Learner steering](screenshots/final/scenario_24/03_learner_steering.png)

_Пользователь меняет приоритеты и видит обновлённую рекомендацию._

<sub>файл: `doc/screenshots/final/scenario_24/03_learner_steering.png` · ⏱ 5s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:38.151Z`
- Финиш: `2026-06-20T18:56:42.934Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** SSR Pedagogy делает маршрут управляемым: learner может сдвигать баланс
retention vs new learning и видеть tradeoffs до действия.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-24--ssr-pedagogy-управляемая-педагогика)

---

## scenario_25 — Mastery и Graduation: карта освоения

**🔴 Mastery** · ⏱ 4 мин · 👤 Аня перед экзаменом — хочет видеть, что уже освоено, а что ещё weak.

**Зачем:** Показать качественный прогресс: mastery vector, graduated vs weak концепты и CTA «Разобрать».

> 🔥 **Wow-момент:** Graduated-концепты исчезают из gap-плана — система знает, что уже освоено.

### Анимированный разбор

![Mastery и Graduation: карта освоения](screenshots/final/scenario_25/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_25/demo.gif` · 597 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Mastery vector: обзор по концептам

![Mastery vector: обзор по концептам](screenshots/final/scenario_25/01_mastery_vector_overview.png)

_Один экран показывает, что уже устойчиво, а что требует внимания._

<sub>файл: `doc/screenshots/final/scenario_25/01_mastery_vector_overview.png` · ⏱ 4s</sub>

#### Шаг 2 — Graduated: стабильно освоенные темы

![Graduated: стабильно освоенные темы](screenshots/final/scenario_25/02_graduated_concepts.png)

_Зелёные концепты можно не трогать перед экзаменом._

<sub>файл: `doc/screenshots/final/scenario_25/02_graduated_concepts.png` · ⏱ 4s</sub>

#### Шаг 3 — Weak spots: приоритет на последние дни

![Weak spots: приоритет на последние дни](screenshots/final/scenario_25/03_weak_concepts_priority.png)

_Система сама находит темы ниже порога mastery._

<sub>файл: `doc/screenshots/final/scenario_25/03_weak_concepts_priority.png` · ⏱ 5s</sub>

#### Шаг 4 — CTA «Разобрать» по weak-концепту

![CTA «Разобрать» по weak-концепту](screenshots/final/scenario_25/04_cta_to_tutor.png)

_Один клик — целевая tutor-сессия по слабому месту._

<sub>файл: `doc/screenshots/final/scenario_25/04_cta_to_tutor.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:43.025Z`
- Финиш: `2026-06-20T18:56:46.369Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Прогресс — не счётчик страниц, а карта знаний с уровнями recognized → graduated.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-25--mastery-и-graduation-карта-освоения)

---

## scenario_26 — Knowledge Graph: персональный подграф

**🔴 Mastery** · ⏱ 3 мин · 👤 Марк хочет увидеть связи между концептами и их mastery-статус.

**Зачем:** Визуализировать knowledge graph: узлы, prerequisites и переход от карты к деталям концепта.

> 🔥 **Wow-момент:** Клик по weak-узлу ведёт к tutor — граф не декорация, а навигация по знаниям.

### Анимированный разбор

![Knowledge Graph: персональный подграф](screenshots/final/scenario_26/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_26/demo.gif` · 504 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Mission Control: карточка Knowledge Graph

![Mission Control: карточка Knowledge Graph](screenshots/final/scenario_26/01_home_kg_card.png)

_Главный экран подсказывает открыть визуальную карту знаний._

<sub>файл: `doc/screenshots/final/scenario_26/01_home_kg_card.png` · ⏱ 4s</sub>

#### Шаг 2 — Раздел Knowledge Graph открыт

![Раздел Knowledge Graph открыт](screenshots/final/scenario_26/02_kg_view_open.png)

_Подграф показывает связи и уровень освоения по узлам._

<sub>файл: `doc/screenshots/final/scenario_26/02_kg_view_open.png` · ⏱ 5s</sub>

#### Шаг 3 — Персональный подграф + mastery

![Персональный подграф + mastery](screenshots/final/scenario_26/03_subgraph_mastery.png)

_Видно, какие концепты уже устойчивы, а какие на границе frontier._

<sub>файл: `doc/screenshots/final/scenario_26/03_subgraph_mastery.png` · ⏱ 5s</sub>

#### Шаг 4 — Рекомендация по слабому узлу

![Рекомендация по слабому узлу](screenshots/final/scenario_26/04_weak_node_cta.png)

_Система предлагает следующий шаг из топологии графа._

<sub>файл: `doc/screenshots/final/scenario_26/04_weak_node_cta.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:56:46.463Z`
- Финиш: `2026-06-20T18:57:17.172Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Knowledge Graph связывает retrieval, mastery и следующий учебный шаг.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-26--knowledge-graph-персональный-подграф)

---

## scenario_27 — Incremental reindex: материалы без потери прогресса

**🟠 Retention engine** · ⏱ 4 мин · 👤 Марк добавил новые лекции и боится потерять mastery после переиндексации.

**Зачем:** Показать, что reindex добавляет новые концепты, но learner profile и mastery сохраняются.

> 🔥 **Wow-момент:** Бейдж «Профиль обновлён после переиндексации» — прогресс на месте, база выросла.

### Анимированный разбор

![Incremental reindex: материалы без потери прогресса](screenshots/final/scenario_27/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_27/demo.gif` · 577 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Темы: каталог после добавления материалов

![Темы: каталог после добавления материалов](screenshots/final/scenario_27/01_topics_catalog_ready.png)

_Новые документы попадают в каталог тем без ручной разметки._

<sub>файл: `doc/screenshots/final/scenario_27/01_topics_catalog_ready.png` · ⏱ 4s</sub>

#### Шаг 2 — Бейдж: профиль обновлён после reindex

![Бейдж: профиль обновлён после reindex](screenshots/final/scenario_27/02_reindex_profile_badge.png)

_Mastery rehydrated — learner state сохранён поверх нового индекса._

<sub>файл: `doc/screenshots/final/scenario_27/02_reindex_profile_badge.png` · ⏱ 4s</sub>

#### Шаг 3 — Mastery vector без обнуления

![Mastery vector без обнуления](screenshots/final/scenario_27/03_mastery_preserved.png)

_Прежние концепты остаются на своих уровнях освоения._

<sub>файл: `doc/screenshots/final/scenario_27/03_mastery_preserved.png` · ⏱ 4s</sub>

#### Шаг 4 — Adaptive Plan: новые концепты в блоке New

![Adaptive Plan: новые концепты в блоке New](screenshots/final/scenario_27/04_new_concepts_in_plan.png)

_Система предлагает свежие темы из новых файлов отдельно от gap._

<sub>файл: `doc/screenshots/final/scenario_27/04_new_concepts_in_plan.png` · ⏱ 5s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:57:17.268Z`
- Финиш: `2026-06-20T18:57:21.749Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Новые файлы расширяют курс, а не обнуляют учебное состояние.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-27--incremental-reindex-материалы-без-потери-прогресса)

---

## scenario_28 — Course Cockpit v2: daily briefing курса

**🔴 Orchestration** · ⏱ 5 мин · 👤 Сергей проходит курс из папки и хочет один экран «что сегодня по курсу».

**Зачем:** Показать Course Cockpit: path map, rotator активностей и прогресс до graduation в одном режиме.

> 🔥 **Wow-момент:** Daily briefing + rotator — курс ощущается как управляемая сессия, а не набор вкладок.

### Анимированный разбор

![Course Cockpit v2: daily briefing курса](screenshots/final/scenario_28/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_28/demo.gif` · 623 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Course Cockpit: заголовок и pace mode

![Course Cockpit: заголовок и pace mode](screenshots/final/scenario_28/01_cockpit_header.png)

_Активный курс открывается в режиме v2-кабины._

<sub>файл: `doc/screenshots/final/scenario_28/01_cockpit_header.png` · ⏱ 4s</sub>

#### Шаг 2 — Daily briefing и активность

![Daily briefing и активность](screenshots/final/scenario_28/02_daily_briefing.png)

_Центральная колонка показывает обзор сессии и следующий блок._

<sub>файл: `doc/screenshots/final/scenario_28/02_daily_briefing.png` · ⏱ 5s</sub>

#### Шаг 3 — Rotator: карточки активностей курса

![Rotator: карточки активностей курса](screenshots/final/scenario_28/03_rotator_panel.png)

_Переключение между quiz, tutor и карточками без потери scope._

<sub>файл: `doc/screenshots/final/scenario_28/03_rotator_panel.png` · ⏱ 4s</sub>

#### Шаг 4 — Прогресс курса до graduation

![Прогресс курса до graduation](screenshots/final/scenario_28/04_graduation_progress.png)

_Видно, сколько осталось до завершения курса._

<sub>файл: `doc/screenshots/final/scenario_28/04_graduation_progress.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:57:21.847Z`
- Финиш: `2026-06-20T18:57:24.932Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Course Cockpit собирает scoped-обучение в single-pane маршрут.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-28--course-cockpit-v2-daily-briefing-курса)

---

## scenario_29 — Graduation celebration: ceremony overlay

**🟡 Perceived quality** · ⏱ 3 мин · 👤 Аня завершила тему — хочет почувствовать завершённость, а не просто цифру mastery.

**Зачем:** Показать celebration overlay и delight progress rail как завершение учебного цикла.

> 🔥 **Wow-момент:** «Поздравляем: концепт зафиксирован как освоенный» — не просто +1% в таблице.

### Анимированный разбор

![Graduation celebration: ceremony overlay](screenshots/final/scenario_29/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_29/demo.gif` · 442 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — Delight loop: progress rail на Home

![Delight loop: progress rail на Home](screenshots/final/scenario_29/01_delight_progress_rail.png)

_Виден путь Q&A → Tutor → Quiz → Card → Review → Graduation._

<sub>файл: `doc/screenshots/final/scenario_29/01_delight_progress_rail.png` · ⏱ 4s</sub>

#### Шаг 2 — Celebration overlay после mastery ≥ 80%

![Celebration overlay после mastery ≥ 80%](screenshots/final/scenario_29/02_celebration_overlay.png)

_Система поздравляет с освоением темы и показывает метрики сессии._

<sub>файл: `doc/screenshots/final/scenario_29/02_celebration_overlay.png` · ⏱ 5s</sub>

#### Шаг 3 — CTA: следующая тема / weak / home

![CTA: следующая тема / weak / home](screenshots/final/scenario_29/03_graduation_ctas.png)

_Три безопасных следующих шага после graduation._

<sub>файл: `doc/screenshots/final/scenario_29/03_graduation_ctas.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:57:25.019Z`
- Финиш: `2026-06-20T18:57:29.532Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** Graduation — эмоциональная точка опоры, которая мотивирует продолжать курс.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-29--graduation-celebration-ceremony-overlay)

---

## scenario_30 — SSR micro-outcome receipt: честный чек после шага

**🔴 Orchestration** · ⏱ 2 мин · 👤 Марк выполнил рекомендацию SSR и хочет увидеть, что изменилось локально.

**Зачем:** Показать micro-outcome receipt: локальные метрики до/после действия роутера без облачного профиля.

> 🔥 **Wow-момент:** «К повторению: было 12 → стало 8» — прогресс измерим и проверяем на машине пользователя.

### Анимированный разбор

![SSR micro-outcome receipt: честный чек после шага](screenshots/final/scenario_30/demo.gif)

<sub>файл: `doc/screenshots/final/scenario_30/demo.gif` · 404 KB · собран через `python scripts/make_demo_gifs.py`</sub>

<details><summary><b>Статичная раскадровка (кадр за кадром)</b></summary>

#### Шаг 1 — SSR: рекомендация следующего шага

![SSR: рекомендация следующего шага](screenshots/final/scenario_30/01_ssr_recommendation.png)

_Роутер предлагает одно действие с объяснением «почему сейчас»._

<sub>файл: `doc/screenshots/final/scenario_30/01_ssr_recommendation.png` · ⏱ 4s</sub>

#### Шаг 2 — Micro-outcome receipt после шага

![Micro-outcome receipt после шага](screenshots/final/scenario_30/02_after_action_receipt.png)

_После действия виден честный diff локальных метрик._

<sub>файл: `doc/screenshots/final/scenario_30/02_after_action_receipt.png` · ⏱ 5s</sub>

#### Шаг 3 — Локальные сигналы: due, weak, plan

![Локальные сигналы: due, weak, plan](screenshots/final/scenario_30/03_local_metrics_changed.png)

_Receipt строится из SQLite/SM-2, без облачного профиля._

<sub>файл: `doc/screenshots/final/scenario_30/03_local_metrics_changed.png` · ⏱ 4s</sub>

</details>


<details><summary>Технические метаданные прогона</summary>

- Старт: `2026-06-20T18:57:29.627Z`
- Финиш: `2026-06-20T18:57:34.287Z`
- Статус: `passed`
- Env: `HOME_RAG_E2E_OFFLINE=1, E2E_API_PORT=18000, E2E_STREAMLIT_PORT=18501`

</details>

**Takeaway:** SSR заканчивается не кликом, а receipt: learner видит эффект своего шага.

> **⚠️ Кадры сняты до Full Circle P0. SSR micro-outcome receipt расширен после съёмки; `03_local_metrics_changed` может не совпадать с текущим интерфейсом. Требуется пересъёмка после Full Circle P0.**

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-30--ssr-micro-outcome-receipt-честный-чек-после-шага)

---

## scenario_31 — Честный сбой LLM: circuit breaker и fallback

**🔵 Trust drill-down** · ⏱ 2 мин · 👤 Аня задаёт вопрос, а LLM-провайдер отвечает ошибкой.

**Зачем:** Показать, что hometutor не падает молча при сбое LLM: circuit breaker, fallback на
локальный провайдер, понятное сообщение пользователю без stacktrace.

> 🔥 **Wow-момент:** Вместо «500 Internal Server Error» пользователь видит: «Сервис временно недоступен.
Ответ подготовлен по локальным материалам» — деградация, а не падение.

> ⚠️ Кадры ещё не снимались. Запусти `npm run test:e2e:demo` и повтори генерацию документа.

> Причина отсутствия ссылок: Папка `doc/screenshots/final/scenario_31/` отсутствует.

**Takeaway:** LLM-сбой не равен сбою приложения: circuit breaker + fallback +
человечное сообщение = доверие к системе в неидеальных условиях.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-31--честный-сбой-llm-circuit-breaker-и-fallback)

---

## scenario_32 — Гость HF Spaces: запуск без установки и ключей

**🟢 Первые шаги** · ⏱ 2 мин · 👤 Лена зашла на Hugging Face Spaces, открыла hometutor без .env.

**Зачем:** Показать, что hometutor можно попробовать в один клик на HF Spaces без регистрации,
установки ключей и скачивания моделей. Guest mode с ограниченным, но рабочим UI.

> 🔥 **Wow-момент:** Лена нажала одну кнопку «Open in HF Spaces» и через 10 секунд видит
рабочий интерфейс с демо-данными, без регистрации и API-ключа.

> ⚠️ Кадры ещё не снимались. Запусти `npm run test:e2e:demo` и повтори генерацию документа.

> Причина отсутствия ссылок: Папка `doc/screenshots/final/scenario_32/` отсутствует.

**Takeaway:** HF Spaces guest mode — входной билет: попробовать можно за 10 секунд,
без установки, ключей и привязки карты.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-32--гость-hf-spaces)

---

## scenario_33 — Экспорт живой карты: Knowledge Graph в Markdown

**🔴 Mastery** · ⏱ 3 мин · 👤 Марк хочет сохранить карту знаний курса для внешнего использования.

**Зачем:** Показать, что Knowledge Graph не только визуальный виджет: его можно
экспортировать как Markdown/Mermaid-диаграмму для вставки в конспекты,
Notion или Obsidian.

> 🔥 **Wow-момент:** Клик «Экспорт» → готовый Markdown с Mermaid-блоком, описывающим подграф
пользователя с мастерой. Можно вставить в конспект одной вставкой.

> ⚠️ Кадры ещё не снимались. Запусти `npm run test:e2e:demo` и повтори генерацию документа.

> Причина отсутствия ссылок: Папка `doc/screenshots/final/scenario_33/` отсутствует.

**Takeaway:** Живая карта не запирается внутри UI: экспорт в Markdown/Mermaid
открывает данные для внешних инструментов.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-33--экспорт-живой-карты)

---

## scenario_34 — Возврат в таймкод видео: контекст без пересмотра

**🟠 Retention engine** · ⏱ 3 мин · 👤 Марк смотрел лекцию, прервался на 23:15. Хочет продолжить с того же места, но без перемотки всего видео.

**Зачем:** Учебное видео с таймкодами — частый формат. hometutor сохраняет позицию
последнего просмотра и предлагает продолжить с точного таймкода,
показывая конспект пройденного и ready-to-answer контекст.

> 🔥 **Wow-момент:** «Продолжить с 23:15» — не просто ссылка на видео, а конспект того,
что было до таймкода, и готовность ответить на вопросы по просмотренному.

> ⚠️ Кадры ещё не снимались. Запусти `npm run test:e2e:demo` и повтори генерацию документа.

> Причина отсутствия ссылок: Папка `doc/screenshots/final/scenario_34/` отсутствует.

**Takeaway:** Учебное видео не теряется в «посмотрю потом»: таймкод + конспект +
контекст вопросов = возврат без пересмотра.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-34--возврат-в-таймкод-видео)

---

## scenario_35 — Приватность и offline-проверка: данные не покидают устройство

**🟢 Первые шаги** · ⏱ 2 мин · 👤 Дима — privacy-ориентированный пользователь. Хочет убедиться, что его конспекты не уходят в облако.

**Зачем:** Ключевое обещание hometutor — local-first. Сценарий доказывает: без OPENAI_API_KEY
приложение работает полностью локально — Chroma, SQLite, LLM через LM Studio
(или fallback offline-режим). Ни один HTTP-запрос не уходит вовне.

> 🔥 **Wow-момент:** Отключил Wi-Fi, запустил hometutor — всё работает: поиск, flashcards,
knowledge graph. Ни одно действие не требует интернета.

> ⚠️ Кадры ещё не снимались. Запусти `npm run test:e2e:demo` и повтори генерацию документа.

> Причина отсутствия ссылок: Папка `doc/screenshots/final/scenario_35/` отсутствует.

**Takeaway:** Local-first — не маркетинг, а архитектура: Chroma + SQLite + LM Studio
= полная учебная среда без внешних зависимостей.

<sub>Freshness: снято на HEAD `56037776d` · текущий HEAD `2c1bc46c6` · gap `206` коммитов</sub>

[→ Полный сценарий в каталоге](user_scenarios.md#сценарий-35--приватность-и-offline-проверка)

---
_Документ сгенерирован `scripts/generate_demo_doc.py`. См. [scenarios/README.md](scenarios/README.md) — как добавить новый сценарий, и [screenshots/README.md](screenshots/README.md) — как устроены артефакты._
