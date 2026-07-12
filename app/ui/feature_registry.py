"""Реестр фич UI: уровни опыта и правила видимости (аддитивный слой)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.ui.constants import ALL_VIEWS, HOME_VIEW


@dataclass(frozen=True)
class FeatureSpec:
    id: str
    title_ru: str
    tier: int
    surface: str
    view_name: str | None = None
    requires: tuple[str, ...] = ()
    fallback_hint_ru: str | None = None
    group_ru: str = "Разделы"


FEATURES: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec("view:mission_control", "Главная - Mission Control", 1, "nav", HOME_VIEW),
    FeatureSpec("view:quick_answer", "Быстрый ответ с источниками", 1, "nav", "Быстрый ответ"),
    FeatureSpec("view:search", "Поиск по материалам", 1, "nav", "Найти материалы"),
    FeatureSpec("view:explain_file", "Объяснить файл", 1, "nav", "Объяснить файл"),
    FeatureSpec("view:tutor", "Чат с тьютором", 2, "nav", "Чат с тьютором"),
    FeatureSpec("view:quiz", "Интерактивный Quiz", 2, "nav", "Интерактивный Quiz"),
    FeatureSpec("view:flashcards", "Flashcards и повторения", 2, "nav", "Flashcards"),
    FeatureSpec("view:progress", "Прогресс обучения", 2, "nav", "Прогресс обучения"),
    FeatureSpec("view:topics", "Темы и каталог", 2, "nav", "Темы"),
    FeatureSpec(
        "view:course",
        "Курс и Course Cockpit",
        3,
        "nav",
        "Курс",
        requires=("active_course",),
        fallback_hint_ru="Активируйте курс на Mission Control или во вкладке «Темы».",
    ),
    FeatureSpec("view:adaptive_plan", "Адаптивный план", 3, "nav", "Адаптивный план"),
    FeatureSpec("view:knowledge_graph", "Граф знаний", 3, "nav", "Knowledge Graph"),
    FeatureSpec("view:living_konspekt", "Живой конспект", 3, "nav", "Живой конспект"),
    FeatureSpec("view:history", "История запросов", 3, "nav", "История"),
    FeatureSpec("view:metrics", "Метрики качества и стоимости", 4, "nav", "Метрики"),
    FeatureSpec("view:print", "Чистый вид (печать)", 4, "nav", "Чистый вид"),
    FeatureSpec("page:analytics", "Страница «Аналитика»", 4, "page", group_ru="Страницы"),
    FeatureSpec(
        "sidebar:sync_backup",
        "Backup, QR-перенос и восстановление",
        4,
        "sidebar",
        group_ru="Сайдбар",
    ),
    FeatureSpec(
        "sidebar:expert_filters",
        "Фильтры области поиска Q&A",
        4,
        "sidebar",
        group_ru="Сайдбар",
    ),
    FeatureSpec("panel:voice", "Голосовой ввод и озвучка", 4, "panel", group_ru="Панели"),
    FeatureSpec(
        "sidebar:research_sessions",
        "Research-сессии",
        3,
        "sidebar",
        group_ru="Сайдбар",
    ),
    FeatureSpec(
        "panel:expert_controls",
        "Экспертные панели в учебных режимах",
        5,
        "panel",
        group_ru="Панели",
    ),
    FeatureSpec(
        "panel:debug_summary",
        "Debug: маршрутизация, trace, стоимость",
        5,
        "panel",
        requires=("has_debug_payload",),
        group_ru="Панели",
    ),
    FeatureSpec(
        "panel:index_freshness",
        "Версия и поколение индекса",
        5,
        "panel",
        group_ru="Панели",
    ),
    FeatureSpec(
        "view:agent_session",
        "Собрать учебную сессию (агент)",
        3,
        "nav",
        "Собрать учебную сессию",
        requires=("agent_enabled",),
        fallback_hint_ru="Включите AGENT_ENABLED в .env для доступа к агентному режиму.",
    ),
)

TILE_FEATURE_IDS: Final[dict[str, str]] = {
    "tutor": "view:tutor",
    "quiz": "view:quiz",
    "flashcards": "view:flashcards",
    "quick_question": "view:quick_answer",
    "topics": "view:topics",
    "course": "view:course",
    "adaptive_plan": "view:adaptive_plan",
    "agent_session": "view:agent_session",
}

VIEW_FEATURE_IDS: Final[dict[str, str]] = {
    spec.view_name: spec.id
    for spec in FEATURES
    if spec.surface == "nav" and spec.view_name
}


def feature_by_id(feature_id: str) -> FeatureSpec | None:
    target = str(feature_id or "").strip()
    for spec in FEATURES:
        if spec.id == target:
            return spec
    return None


def feature_for_view(view_name: str) -> FeatureSpec | None:
    return feature_by_id(VIEW_FEATURE_IDS.get(str(view_name or "").strip(), ""))


def features_for_surface(surface: str) -> tuple[FeatureSpec, ...]:
    target = str(surface or "").strip()
    return tuple(spec for spec in FEATURES if spec.surface == target)


def requirement_context_ok(requires: tuple[str, ...]) -> bool:
    for requirement in requires:
        if requirement == "active_course":
            try:
                from app.ui.study_scope import get_active_scope

                if get_active_scope() is None:
                    return False
            except Exception:  # noqa: BLE001 - UI visibility must degrade gracefully.
                return False
        elif requirement == "has_debug_payload":
            try:
                import streamlit as st

                if not st.session_state.get("last_debug"):
                    return False
            except Exception:  # noqa: BLE001
                return False
        elif requirement == "auth_enabled":
            try:
                from app.config import get_settings

                if not get_settings().auth_enabled:
                    return False
            except Exception:  # noqa: BLE001
                return False
        elif requirement == "agent_enabled":
            try:
                from app.config import get_settings

                if not get_settings().agent_enabled:
                    return False
            except Exception:  # noqa: BLE001
                return False
        else:
            return False
    return True


def context_ok_for_feature(spec: FeatureSpec) -> bool:
    return requirement_context_ok(spec.requires)


def validate_registry() -> None:
    ids = [spec.id for spec in FEATURES]
    if len(ids) != len(set(ids)):
        raise AssertionError("Feature ids must be unique")
    for spec in FEATURES:
        if spec.tier < 1 or spec.tier > 5:
            raise AssertionError(f"Invalid tier for {spec.id}: {spec.tier}")
        if spec.surface == "nav":
            if not spec.view_name:
                raise AssertionError(f"Nav feature has no view_name: {spec.id}")
            if spec.view_name not in ALL_VIEWS:
                raise AssertionError(f"Unknown nav view for {spec.id}: {spec.view_name!r}")
