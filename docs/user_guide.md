# hometutor — руководство пользователя

Актуализировано: 2026-06-24.

> Положите учебные материалы в `data/`, проиндексируйте их и получите локального учебного помощника: ответы с источниками, тьютора, quiz, flashcards, SM-2 повторения, прогресс и Smart Study Router.

Этот документ — главная карта продукта. Если [quickstart.md](quickstart.md) ведёт по командам запуска, то здесь ответ на вопрос: что умеет `hometutor` и куда идти в интерфейсе.

## Быстрая развилка

| Хочу | Открыть |
|---|---|
| запустить проект | [quickstart.md](quickstart.md) |
| пройти demo lane | [quickstart_demo.md](quickstart_demo.md) |
| посмотреть HTTP API | [api_reference.md](api_reference.md) |
| понять архитектуру | [architecture.md](architecture.md) |
| понять ограничения runtime-репозитория | [index.md](index.md) |

## Для кого это

`hometutor` полезен, если у вас есть лекции, конспекты, статьи, Obsidian vault или учебные PDF, и вы хотите не просто “поговорить с документом”, а пройти цикл обучения.

```text
data/ с материалами
  -> индекс
  -> ответ с источниками
  -> tutor-разбор
  -> quiz
  -> flashcards + SM-2
  -> progress + Smart Study Router
```

Проект local-first: материалы, индекс и учебное состояние находятся на вашей машине. По умолчанию `config.env` направляет LLM и embeddings на loopback endpoints (`127.0.0.1`). Если вы явно переопределяете `EMBED_API_BASE`, `LLM_API_BASE` или fallback-настройки на облачный provider, содержимое запросов может уходить внешнему провайдеру (см. [quickstart.md](quickstart.md)).

## Главная: Mission Control

Первый экран — не landing page, а рабочая панель. Она показывает:

- Smart Study Router: один рекомендуемый следующий шаг и объяснение “почему сейчас”;
- resume-карточки для тьютора, due-карточек и активного курса;
- быстрые плитки режимов;
- доступ к Knowledge Graph, истории, метрикам и explain-file.

Главная нужна для возврата: пользователь не вспоминает, где остановился, а продолжает с локального состояния.

## Быстрый ответ

Режим для вопроса “что говорится в моих материалах?”.

Вы получаете:

- ответ по индексу;
- список источников;
- confidence/trace сигналы;
- мост в tutor-режим;
- debug-информацию при включённых диагностических панелях.

HTTP-контракт: `POST /ask`.

## Чат с тьютором

Tutor работает через тот же endpoint `/ask`, но с `query_mode="tutor"` и learner context. Он может:

- объяснить тему проще;
- дать пример;
- встроить micro-quiz;
- продолжить multi-turn сессию по `session_id`;
- учитывать learner goal snapshot.

Важный принцип: переход из ответа в обучение не должен терять тему, источники и цель.

## Quiz

Quiz поддерживает генерацию и оценку вопросов по теме или документу.

Ключевые endpoints:

- `POST /quiz/generate`
- `POST /quiz/evaluate`

Оценка возвращает diagnostic feedback: `recognized`, `recalled`, `misconception`, `cannot_apply`. Эти сигналы участвуют в учебном контуре и могут влиять на следующий шаг.

## Flashcards и SM-2

Flashcards — это human-in-the-loop генерация:

1. выберите источник: документ, upload или active course;
2. сгенерируйте preview;
3. отредактируйте карточки;
4. сохраните колоду;
5. повторяйте по SM-2.

Поддерживается:

- due-очередь;
- оценки `Again / Hard / Good / Easy`;
- recovery tail для большой очереди;
- undo recovery для ещё не повторённых карточек;
- экспорт Anki `.apkg`;
- импорт карточек из quiz.

Ключевые endpoints: `/flashcards/*`.

## Темы и курс

Раздел `Темы` показывает каталог материалов, synthesis и learning plan. Если материалы организованы папками, активируйте папку как course scope и работайте с ней как с курсом.

Course Cockpit показывает daily briefing, pace mode, активность курса и прогресс до graduation.

## Прогресс обучения

Раздел `Прогресс обучения` отвечает на вопрос “что делать сегодня?”.

Там собраны:

- adaptive daily plan;
- mastery;
- analytics;
- weekly narrative;
- due/review состояние;
- Knowledge Graph и weak spots.

Локальное состояние хранится в `data/user_state.db`.

## Smart Study Router

Smart Study Router выбирает следующий шаг из локальных сигналов:

- due flashcards;
- concept-level SM-2;
- свежий ответ с источниками;
- ошибка в quiz;
- weak concept;
- tutor resume;
- active course/adaptive plan.

Результат: `hint_kind`, primary action, secondary actions и объяснение. Feedback `accept/reject/defer` сохраняется локально через `/ssr/recommendation-feedback`.

## Приватность и данные

| Данные | Где |
|---|---|
| исходные материалы | `data/` |
| прогресс, flashcards, mastery | `data/user_state.db` |
| индекс | `chroma_db/` |
| логи и SSR-профили | `logs/` |
| настройки по умолчанию | `config.env` |
| локальные секреты | `.env` |

По умолчанию `config.env` использует локальные LLM/embedding endpoints. Чтобы ни один фрагмент не покидал вашу машину, держите `EMBED_API_BASE`, `EMBED_MODEL`, `LLM_API_BASE` и `LLM_MODEL` направленными на локальные серверы. При использовании облачного LLM/embedding provider содержимое запросов уходит внешнему провайдеру.

## Каналы

| Канал | Когда использовать |
|---|---|
| Streamlit UI | основной пользовательский интерфейс |
| FastAPI | интеграции, автоматизация, OpenAPI |
| Telegram bot | быстрый мобильный клиент |
| Docker | переносимый локальный deployment |

## Что читать дальше

| Цель | Документ |
|---|---|
| старт с нуля | [quickstart.md](quickstart.md) |
| ручной demo lane | [quickstart_demo.md](quickstart_demo.md) |
| API endpoints | [api_reference.md](api_reference.md) |
| системные границы | [architecture.md](architecture.md) |
| инженерные правила | [conventions.md](conventions.md) |
