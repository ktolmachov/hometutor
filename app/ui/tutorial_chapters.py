"""Контент интерактивного chaptered guide (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TutorialStep:
    id: str
    title_ru: str
    body_ru: str
    target_view: str | None
    target_anchor: str | None
    cta_label_ru: str
    us_refs: list[str]
    wow: bool = False


@dataclass(frozen=True)
class TutorialChapter:
    id: str
    title_ru: str
    summary_ru: str
    level: Literal["beginner", "intermediate", "advanced", "expert"]
    estimated_minutes: int
    steps: list[TutorialStep]
    cjm_stages: list[str]


CHAPTERS: list[TutorialChapter] = [
    TutorialChapter(
        id="ch1_first_answer",
        title_ru="Глава 1. Первый ответ",
        summary_ru="Discover → Install → Ingest → First Answer → Trust",
        level="beginner",
        estimated_minutes=3,
        cjm_stages=["Discover", "Install", "Ingest", "First Answer", "Trust"],
        steps=[
            TutorialStep(
                id="welcome",
                title_ru="Добро пожаловать в интерактивный тур",
                body_ru="Пройдём 5 глав от первого ответа до expert-режима. Начнём с быстрого ответа по вашим материалам.",
                target_view="Быстрый ответ",
                target_anchor=None,
                cta_label_ru="Начать",
                us_refs=["US-1.1", "US-1.2", "US-1.3"],
            ),
            TutorialStep(
                id="try_examples",
                title_ru="Попробуйте пример вопроса",
                body_ru="Откройте «Быстрый ответ» и задайте вопрос. Это создаст основу для перехода в Tutor.",
                target_view="Быстрый ответ",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-2.1", "US-3.1", "US-3.2"],
            ),
            TutorialStep(
                id="trust_panel",
                title_ru="Проверьте источники и доверие",
                body_ru="Раскройте карточки источников и confidence-панель: это база explainability.",
                target_view="Быстрый ответ",
                target_anchor=None,
                cta_label_ru="К главе 2",
                us_refs=["US-3.3", "US-3.4", "US-11.1"],
                wow=True,
            ),
        ],
    ),
    TutorialChapter(
        id="ch2_answer_to_learning",
        title_ru="Глава 2. От ответа к обучению",
        summary_ru="Switch to Tutor → Tutor Session → Micro-quiz",
        level="beginner",
        estimated_minutes=5,
        cjm_stages=["Switch to Tutor", "Tutor session", "Micro-quiz"],
        steps=[
            TutorialStep(
                id="handoff_to_tutor",
                title_ru="Переключение в Tutor",
                body_ru="Нажмите CTA перехода к тьютору: контекст вопроса должен сохраниться автоматически.",
                target_view="Чат с тьютором",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-4.1", "US-4.2"],
            ),
            TutorialStep(
                id="micro_quiz",
                title_ru="Мини-квиз внутри сессии",
                body_ru="Запустите микро-квиз и проверьте адаптацию сложности к вашему уровню.",
                target_view="Интерактивный Quiz",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-5.1", "US-5.2", "US-13.1"],
            ),
            TutorialStep(
                id="hint_loop",
                title_ru="Подсказка вместо тупика",
                body_ru="При ошибке система даёт подсказку и сохраняет учебный темп без жёсткого fail-state.",
                target_view="Чат с тьютором",
                target_anchor=None,
                cta_label_ru="К главе 3",
                us_refs=["US-14.1", "US-14.4"],
                wow=True,
            ),
        ],
    ),
    TutorialChapter(
        id="ch3_return_tomorrow",
        title_ru="Глава 3. Возвращаюсь завтра",
        summary_ru="Adaptive Plan → Resume → Интервальные повторения",
        level="intermediate",
        estimated_minutes=4,
        cjm_stages=["Adaptive Plan", "Resume", "Интервальные повторения"],
        steps=[
            TutorialStep(
                id="resume_cards",
                title_ru="Resume и план дня",
                body_ru="Оцените resume-карточки на главном экране и план на сегодня в прогрессе.",
                target_view="Прогресс обучения",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-6.1", "US-6.2", "US-6.3", "US-7.1"],
            ),
            TutorialStep(
                id="soft_recovery",
                title_ru="Soft-recovery после паузы",
                body_ru="Очередь due-повторений распределяется мягко, без лавины просроченных карточек.",
                target_view="Прогресс обучения",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-7.2", "US-7.3", "US-7.4"],
                wow=True,
            ),
            TutorialStep(
                id="reindex_resilience",
                title_ru="Устойчивость после reindex",
                body_ru="Проверьте, что профиль обучения и следующий шаг сохраняются после обновления индекса.",
                target_view="Прогресс обучения",
                target_anchor=None,
                cta_label_ru="К главе 4",
                us_refs=["US-8.1", "US-8.2"],
            ),
        ],
    ),
    TutorialChapter(
        id="ch4_flashcards_memory",
        title_ru="Глава 4. Flashcards и долгая память",
        summary_ru="Flashcards Gen → Review → Progress",
        level="advanced",
        estimated_minutes=6,
        cjm_stages=["Flashcards Gen", "Flashcards Review", "Progress"],
        steps=[
            TutorialStep(
                id="generate_deck",
                title_ru="Создайте колоду",
                body_ru="Сгенерируйте карточки из документа или загрузки, затем отредактируйте перед сохранением.",
                target_view="Flashcards",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-15.1", "US-15.2", "US-15.3", "US-15.5"],
            ),
            TutorialStep(
                id="review_sm2",
                title_ru="Пройдите due-review",
                body_ru="Повторите карточки в режиме Again/Hard/Good/Easy и посмотрите session summary.",
                target_view="Flashcards",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-9.1", "US-15.6"],
            ),
            TutorialStep(
                id="anki_and_graduation",
                title_ru="Экспорт и graduation",
                body_ru="Проверьте экспорт в Anki и сигнал graduation, когда концепт закреплён.",
                target_view="Прогресс обучения",
                target_anchor=None,
                cta_label_ru="К главе 5",
                us_refs=["US-15.4", "US-9.2"],
                wow=True,
            ),
        ],
    ),
    TutorialChapter(
        id="ch5_course_workspace",
        title_ru="Глава 5. Курс под ключ",
        summary_ru="Course Mode → Master → Export/Sync → Expert Controls",
        level="expert",
        estimated_minutes=8,
        cjm_stages=["Course Mode", "Master", "Export/Sync", "Expert Controls"],
        steps=[
            TutorialStep(
                id="activate_course",
                title_ru="Активируйте Course Workspace",
                body_ru="Включите курс в «Темах»: дальше запросы и план работают в пределах выбранной области.",
                target_view="Темы",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-16.0", "US-16.1", "US-16.2"],
            ),
            TutorialStep(
                id="course_loop",
                title_ru="Пройдите учебный цикл курса",
                body_ru="Сделайте связку scoped QA → flashcards → tutor и закрепите mastery по курсу.",
                target_view="Чат с тьютором",
                target_anchor=None,
                cta_label_ru="Дальше",
                us_refs=["US-16.3", "US-16.4", "US-16.5", "US-16.6"],
                wow=True,
            ),
            TutorialStep(
                id="expert_sync",
                title_ru="Expert controls и полный sync",
                body_ru="Откройте advanced control и проверьте export/import полного sync-пакета.",
                target_view="Прогресс обучения",
                target_anchor=None,
                cta_label_ru="Завершить тур",
                us_refs=["US-14.3", "US-10.1", "US-10.2", "US-10.3"],
            ),
        ],
    ),
]
