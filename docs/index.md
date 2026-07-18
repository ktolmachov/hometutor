# Навигатор документации hometutor

Актуализировано: 2026-07-18.

`hometutor` — runtime-репозиторий локального учебного RAG-приложения. Здесь живут приложение, API, UI, запуск, deployment и эксплуатационная документация. Demo screenshots сохранены в `docs/screenshots/final/`; исходные сценарные манифесты, генератор demo-документа, backlog, user stories и процессные материалы вынесены в `hometutor-studio`.

## Быстрый старт по ролям

| Роль | Читать сначала |
|---|---|
| Пользователь | [user_guide.md](user_guide.md) -> [quickstart.md](quickstart.md) |
| Demo/pitch | [quickstart_demo.md](quickstart_demo.md) -> [user_guide.md](user_guide.md) |
| Backend/API | [api_reference.md](api_reference.md) -> [technical_specification.md](technical_specification.md) |
| Архитектор | [architecture.md](architecture.md) -> [conventions_architecture.md](conventions_architecture.md) |
| Разработчик | [conventions.md](conventions.md) -> [evolutionary_development.md](evolutionary_development.md) -> [conventions_reference.md](conventions_reference.md) |
| Product / UI/UX | [ui_ux_design_review_2026-07-18.md](ui_ux_design_review_2026-07-18.md) -> [ui_ux_design_review_implementation_plan.md](ui_ux_design_review_implementation_plan.md) |
| DevOps | [quickstart.md](quickstart.md) -> [../DOCKER_BUILD.md](../DOCKER_BUILD.md) -> [../deploy/hf-spaces/README.md](../deploy/hf-spaces/README.md) |

## Документы

| Документ | Назначение |
|---|---|
| [user_guide.md](user_guide.md) | главная карта продукта и пользовательских режимов |
| [quickstart.md](quickstart.md) | локальный запуск, индекс, первый учебный цикл |
| [quickstart_demo.md](quickstart_demo.md) | screenshot-витрина demo-сценариев и правила её обновления |
| [api_reference.md](api_reference.md) | актуальная карта HTTP endpoints |
| [architecture.md](architecture.md) | runtime-архитектура и границы хранилищ |
| [diagrams.md](diagrams.md) | автогенерируемые диаграммы (API, слои, ER, фичи UI) — обновлять `scripts/generate_diagrams.py` |
| [technical_specification.md](technical_specification.md) | техническая спецификация runtime-системы |
| [conventions.md](conventions.md) | короткие инженерные правила |
| [evolutionary_development.md](evolutionary_development.md) | инженерный стиль маленьких проверяемых волн и критерии завершения |
| [ui_ux_design_review_2026-07-18.md](ui_ux_design_review_2026-07-18.md) | системный UI/UX-аудит runtime-продукта: Мнемополис, основные учебные разделы, дизайн-система, accessibility и responsive |
| [ui_ux_design_review_implementation_plan.md](ui_ux_design_review_implementation_plan.md) | зафиксированный план реализации дизайн-ревью: P0/P1/P2, волны W1-W10, write-set, targeted tests и Definition of Done |
| [conventions_architecture.md](conventions_architecture.md) | архитектурные соглашения по слоям |
| [conventions_reference.md](conventions_reference.md) | справочник по API, ошибкам, тестам и документации |
| [AI_DEVELOPMENT.md](AI_DEVELOPMENT.md) | как ИИ использовался на этапах планирования/дизайна/разработки/деплоя, примеры промптов |
| [agent_roadmap.md](agent_roadmap.md) | архитектура и волновая дорожная карта внедрения AI-агента (tool-loop, stop controller, evals, HITL) |
| [multimodal_konspekt_plan.md](multimodal_konspekt_plan.md) | handoff-план мультимодального конспекта, ASR/VLM, sidecar, US/CJM и DoD |
| [living_konspekt_next_waves_plan.md](living_konspekt_next_waves_plan.md) | анализ упущений «Живого конспекта» и волны W4–W8 (сервис-слой, методология, жизненный цикл артефакта) |
| [adr/0001-multimodal-media-contract.md](adr/0001-multimodal-media-contract.md) | ADR по контракту multimodal sidecar и безопасным media paths |
| [adr/0002-asr-dependency-strategy.md](adr/0002-asr-dependency-strategy.md) | ADR по optional ASR backend (ffmpeg — только remux) и benchmark-spike |
| [adr/0003-workbench-row-contract.md](adr/0003-workbench-row-contract.md) | ADR по контракту workbench row v2: persisted (rel) vs runtime (abs), `row_version`, миграция abs→rel |
| [adr/0004-artifact-manifest.md](adr/0004-artifact-manifest.md) | ADR по `app/konspekt_artifact.py`: frontmatter-манифест Living Konspekt, round-trip в корзину, update по `artifact_id` |
| [schemas/media_sidecar_v1.schema.json](schemas/media_sidecar_v1.schema.json) | JSON Schema для `<konspekt>.media.json` |

## Источники истины

| Вопрос | Источник |
|---|---|
| OpenAPI и реальные маршруты | `app/api.py`, `app/routers/*`, `/docs` |
| конфигурация | `app/config.py`, `config.env`, `.env` |
| LLM/embeddings | `app/provider.py` |
| Streamlit UI | `app/ui/main.py`, `app/ui/*` |
| user state | `app/user_state*.py`, `data/user_state.db` (или `data/users/<user_id>/user_state.db` при `AUTH_ENABLED=true`) |
| уровни видимости UI | `app/ui/feature_registry.py`, `app/ui_preferences.py`, `app/ui/navigation_visibility.py` |
| flashcards | `app/flashcard_service.py`, `app/routers/flashcards.py` |
| Smart Study Router | `app/smart_study_*.py`, `app/ssr_*.py` |
| AI Agent Coach | `app/agent/*`, `app/prompts/_impl.py`, [agent_roadmap.md](agent_roadmap.md) |
| аутентификация | `app/auth_*.py`, `app/routers/auth.py`, `app/api_auth.py::auth_scope`, `data/auth.db` |
| CI/CD | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |

## Что было исправлено при актуализации

- 2026-07-18: добавлены системное UI/UX-ревью всего runtime-продукта и план его реализации. Зафиксированы baseline-оценки, P0/P1/P2, semantic design tokens, accessibility/responsive gates и независимые волны W1-W10 с write-set и targeted tests. Vision/reference-материалы Мнемополиса и mega-bundle остаются в отдельном репозитории `hometutor-studio`; runtime-выводы и handoff сохранены здесь.
- 2026-07-03: добавлена модель видимости UI по уровням опыта, панель управления
  интерфейсом, онбординг-выбор режима и sync-перенос настроек через `app_kv`.
- 2026-07-12: полное закрытие плана "Agent as One Button" (A1: UI-дверь + префилл темы из MC; A2: read-only `/agent/runs` + `/agent/runs/{run_id}`; B1: golden расширен до 8 study_session; B2: кнопки сохранения карточек-кандидатов (user-initiated); C1: история агента в Прогрессе). Обновлены: api_reference.md (новые эндпоинты), architecture.md, user_guide.md, agent_roadmap.md, docs/index.md, quickstart.md. Добавлены/усилены targeted тесты на префилл, save cards, C1, A2 positive cases.
- 2026-07-13: Audio Podcasts (P0): sibling `.m4a` discovery (`app/media_audio.py`), `st.audio` в Живом конспекте + «Скачать выпуск (m4a)» (A1+A2), оффлайн-экстракция в `transcribe_media.py` + `Run-MediaKonspektPipeline.ps1`. Обновлены: user_guide.md, quickstart.md, multimodal_konspekt_plan.md, architecture.md, technical_specification.md, adr/0002, CI (реальный PS-тест на windows). Добавлены регрессионные пины и интеграционный тест пайплайна.
- 2026-06-30: синхронизация после добавления опциональной аутентификации (JWT + bcrypt,
  per-user state isolation), CI/CD (`.github/workflows/`), Яндекс.Метрики и opt-in
  `RAG_CONTEXT_TOKEN_BUDGET`. Обновлены `api_reference.md`, `architecture.md`,
  `technical_specification.md`. Снято ложное утверждение об отсутствии `tests/` —
  каталог существует и используется в CI (`pytest`).
- Убраны ссылки на отсутствующие `docs/scenarios/*`, `user_scenarios.md`, `user_guide_details.md`, `prompts_catalog.md`, `personalized_learner_model.md`; demo screenshots оставлены как локальные артефакты `docs/screenshots/final/*`.
- Уточнено, что `config.env` является tracked defaults, а `.env` — локальным override.
- Убраны упоминания несуществующих entrypoints вроде `ask.py` и `run_eval.py`.
- Пользовательские `doc/`-ссылки заменены на `docs/`; оставшиеся `doc/*` в коде относятся к legacy/process prompt paths и требуют отдельной миграции, если эти сценарии снова станут runtime-критичными.
- API reference синхронизирован с `app/api.py` и `app/routers/*` на дату актуализации.

## Политика документации

- Runtime-документы не должны ссылаться на локальные файлы, которых нет в этом репозитории.
- Если ссылка ведёт в `hometutor-studio`, это нужно писать явно.
- При изменении маршрутов обновляйте [api_reference.md](api_reference.md).
- При изменении пользовательского поведения обновляйте [user_guide.md](user_guide.md) и [quickstart.md](quickstart.md).
