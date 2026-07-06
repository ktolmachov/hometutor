"""Mission Control home screen for the Streamlit UI."""
from __future__ import annotations

import html
import math
import random
from dataclasses import dataclass
from typing import Any, Final, get_args

import streamlit as st

from app.config import get_settings
from app import user_state
from app.course_cache import build_mission_control_course_options
from app.smart_study_router import (
    SmartStudyRecommendation,
    SmartStudyRouterHintKind,
    build_smart_study_evidence_ledger_lines,
    build_smart_study_recommendation,
    smart_study_contrastive_explanation,
    smart_study_why_not_others_ru,
)
from app.ui.adaptive_plan_card import apply_smart_study_primary_navigation
from app.ui.breadcrumb import HOME_VIEW
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.mission_control_first_session import (
    clear_first_session_session_cache,
    load_first_session_artifact_cached_for_scope,
    render_first_session_block as _render_first_session_block,
    render_first_session_hero,
)
from app.ui.first_run import render_demo_sandbox_banner, render_empty_index_hero
from app.ui.preflight import render_preflight_card
from app.ui.reindex_poll import poll_reindex_status
from app.ui.seed_questions import render_seed_question_chips
from app.ui.study_scope import activate_scope, deactivate_scope, get_active_scope
from app.ui_preferences import feature_visible, get_overrides, get_ui_level


HINT_TO_TILE: Final[dict[str, str]] = {
    "cards_due": "flashcards",
    "sm2_due": "flashcards",
    "quiz_failed": "quiz",
    "tutor_resume": "tutor",
    "answer_ready": "quick_question",
    "mastery_stale": "topics",
    "adaptive_plan": "adaptive_plan",
    "safe_default": "tutor",
}


MORE_TOOLS: Final[tuple[tuple[str, str, str], ...]] = (
    ("Knowledge Graph", "Knowledge Graph", ":material/account_tree:"),
    ("История", "История", ":material/history:"),
    ("Поиск материалов", "Найти материалы", ":material/search:"),
    ("Метрики", "Метрики", ":material/analytics:"),
    ("Объяснить файл", "Объяснить файл", ":material/description:"),
    ("Чистый вид", "Чистый вид", ":material/print:"),
)


@dataclass(frozen=True)
class MissionTile:
    tile_id: str
    title: str
    description: str
    best_for: str
    icon: str  # Material Symbols Outlined ligature name (e.g. school), not Streamlit :material_* markdown.
    target_view: str
    button_label: str
    slot_hint: str


@dataclass(frozen=True)
class CourseOption:
    folder_rel: str
    title: str
    source_paths: tuple[str, ...]

    @property
    def label(self) -> str:
        suffix = f" · {len(self.source_paths)} док." if self.source_paths else ""
        return f"{self.title}{suffix}"


def _navigate_to(view: str, *, slot_hint: str | None = None) -> None:
    _set_navigation_state(view, slot_hint=slot_hint)
    st.rerun()


def _set_navigation_state(view: str, *, slot_hint: str | None = None) -> None:
    """Запросить переход на ``view`` через отложенный ключ.

    ``current_view`` — ключ виджета ``st.selectbox`` в ``main.py`` (инстанцируется до
    вызова любого view-рендерера); прямая запись в него ПОСЛЕ инстанцирования кидает
    ``StreamlitAPIException``. ``PENDING_CURRENT_VIEW_KEY`` — единственный безопасный
    путь: main.py читает и применяет его ДО ``st.selectbox(..., key="current_view")``
    на следующем прогоне (см. ``app/ui/session_state.py``). Безопасно и для synchronous
    вызовов внутри тела кнопки (rerun сразу следом), и для ``on_click=`` колбэков.
    """
    st.session_state[PENDING_CURRENT_VIEW_KEY] = view
    st.session_state["home_breadcrumb_origin"] = HOME_VIEW
    if slot_hint:
        st.session_state["home_last_primary_mode_slot"] = slot_hint


def _apply_primary_navigation(rec: SmartStudyRecommendation) -> None:
    st.session_state["home_breadcrumb_origin"] = HOME_VIEW
    apply_smart_study_primary_navigation(rec)


def _safe(text: object) -> str:
    return html.escape(str(text or ""))


def _material_glyph_html(ligature: str) -> str:
    """Material icon inside raw HTML; Streamlit shortcodes only work in markdown, not unsafe_allow_html."""
    leaf = str(ligature or "").strip()
    if not leaf:
        return ""
    return f'<span class="material-symbols-outlined" aria-hidden="true">{html.escape(leaf)}</span>'


def _flashcards_due_count() -> int | None:
    try:
        return int(user_state.count_due_flashcards())
    except Exception as exc:  # noqa: BLE001 - UI badge must degrade gracefully.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("mission control due count: %s", exc)
        return None


_COLD_USER_TILE_IDS: Final[frozenset[str]] = frozenset({
    "quick_question",
    "tutor",
    "quiz",
})


def _has_indexed_materials(index_stats: dict | None) -> bool:
    """True when the knowledge base already has indexed content to study.

    Indexing materials is itself meaningful intent: such a user needs the full
    Mission Control (Темы / Курс / Flashcards / Адаптивный план), not the
    cold-start 3-tile view. Tolerant of the several shapes ``index_stats`` takes.
    """
    if not isinstance(index_stats, dict):
        return False
    if str(index_stats.get("status") or "") == "ok":
        return True
    try:
        if int(index_stats.get("nodes_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return any(str(f).strip() for f in index_stats.get("files") or [])


def _is_cold_user(due_count: int | None, index_stats: dict | None = None) -> bool:
    """True when the learner has no meaningful activity yet.

    A cold user sees a focused Mission Control: Quick Answer as the primary
    entry, plus Tutor and Quiz.  Everything else appears after first activity.
    An already-indexed knowledge base counts as activity — otherwise a fresh
    user with a ready base loses every entry point into their materials.
    """
    if _has_indexed_materials(index_stats):
        return False
    if due_count and due_count > 0:
        return False
    try:
        from app.history_service import get_history

        if get_history(limit=1)["total"] > 0:
            return False
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.user_state_flashcards import list_flashcard_decks

        if list_flashcard_decks():
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


def _course_options_from_index_stats(index_stats: dict | None) -> tuple[CourseOption, ...]:
    if not isinstance(index_stats, dict):
        return ()
    folders = [str(x).strip() for x in index_stats.get("folder_rel_options") or [] if str(x).strip()]
    files = [str(x).strip() for x in index_stats.get("files") or [] if str(x).strip()]
    if not folders:
        inferred = sorted({path.split("/", 1)[0].split("\\", 1)[0] for path in files if path})
        folders = [folder for folder in inferred if folder and folder != "."]
    options: list[CourseOption] = []
    for folder in folders:
        prefix_slash = f"{folder}/"
        prefix_backslash = f"{folder}\\"
        source_paths = tuple(
            path for path in files if path == folder or path.startswith(prefix_slash) or path.startswith(prefix_backslash)
        )
        options.append(
            CourseOption(
                folder_rel=folder,
                title=f"Курс: {folder}",
                source_paths=source_paths,
            )
        )
    return tuple(options)


def _build_recommendation(index_stats: dict | None) -> SmartStudyRecommendation:
    try:
        from app.ui.resume_cards import gather_smart_study_router_session_context
        from app.ui.resume_cards_smart_study import (
            ladder_kwargs_for_build,
            remember_ssr_primary_nav,
        )

        ctx = gather_smart_study_router_session_context(
            index_stats=index_stats if isinstance(index_stats, dict) else None,
        )
        qf_status: str | None = None
        if ctx.effective_tutor_snap:
            qfx = ctx.effective_tutor_snap.get("quiz_feedback")
            if isinstance(qfx, dict):
                qf_status = str(qfx.get("status") or "").strip() or None
        rec = build_smart_study_recommendation(
            surface="home",
            flashcard_due_n=ctx.flashcard_due_n,
            sm2_due_n=ctx.sm2_due_n,
            quiz_feedback_status=qf_status,
            has_tutor_resume=bool(ctx.effective_tutor_snap and ctx.tutor_topic),
            tutor_topic=ctx.tutor_topic,
            has_last_answer_qa=ctx.has_last_answer_qa,
            has_reading_resume=ctx.has_reading,
            first_weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
            plan_primary_block=None,
            **ladder_kwargs_for_build(
                current_anchor=ctx.tutor_topic,
                quiz_feedback_status=qf_status,
            ),
        )
        remember_ssr_primary_nav(rec.primary_nav)
        return rec
    except Exception as exc:  # noqa: BLE001 - home screen should never go blank.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("mission control SSR fallback: %s", exc)
        try:
            from app.ui.resume_cards_smart_study import ladder_kwargs_for_build

            return build_smart_study_recommendation(
                surface="home",
                **ladder_kwargs_for_build(),
            )
        except Exception:  # noqa: BLE001 - last-resort home SSR without ladder resolver.
            return build_smart_study_recommendation(surface="home")


def _tile_definitions(*, due_count: int | None) -> tuple[MissionTile, ...]:
    due_suffix = "К повторению: ..." if due_count is None else f"К повторению: {due_count}"
    course_scope = get_active_scope()
    course_title = "Активируй курс"
    course_desc = "Выбери папку и собери учебный контур"
    if course_scope:
        course_title = str(course_scope.get("title") or course_scope.get("folder_rel") or "Курс")
        course_desc = "Кокпит курса для активного учебного контура"
    return (
        MissionTile("tutor", "Тьютор", "Разобрать тему, ошибку или следующий шаг", "объяснить", "school", "Чат с тьютором", "Начать", "tutor"),
        MissionTile("quiz", "Quiz", "Проверка знаний по теме или документу", "проверить", "quiz", "Интерактивный Quiz", "Пройти", "quiz"),
        MissionTile("flashcards", "Flashcards", due_suffix, "закрепить", "style", "Flashcards", "Повторить", "flashcards"),
        MissionTile("quick_question", "Быстрый ответ", "Ответ по базе знаний с источниками", "уточнить", "help", "Быстрый ответ", "Спросить", "qa"),
        MissionTile("topics", "Темы", "Каталог тем, пробелы и маршруты", "сориентироваться", "folder_open", "Темы", "Открыть", "topics"),
        MissionTile("course", course_title, course_desc, "курс", "map", "Курс", "Открыть", "course"),
        MissionTile("adaptive_plan", "Адаптивный план", "Дневной маршрут с приоритетами", "спланировать", "route", "Адаптивный план", "Собрать", "adaptive_plan"),
    )


def _render_ssr_banner(rec: SmartStudyRecommendation, *, index_stats: dict | None = None) -> None:
    """Home Mission Control: объяснимый SSR без полной карточки `e2e-smart-study-next-step`."""
    contrast = smart_study_contrastive_explanation(rec)
    defer_modes = smart_study_why_not_others_ru(rec)
    hint_attr = _safe(str(rec.hint_kind))
    title_id = "mc_ssr_heading"

    pedagogy_line = str(rec.route_pedagogy_ru or "").strip()

    ledger_lines = list(build_ssr_evidence_for_banner(index_stats))
    audit_tail = str(rec.ml_audit_ru or "").strip()
    if audit_tail:
        ledger_lines.append(audit_tail)
    ledger_section = ""
    if ledger_lines:
        items_li = "".join(f"<li>{_safe(line)}</li>" for line in ledger_lines)
        ledger_section = (
            '<div class="ssr-section" data-testid="e2e-ssr-evidence">'
            '<span class="ssr-chip ssr-chip--signals">📊 Локальные сигналы</span>'
            "<p>это устройство и индекс; не облачный скоринг и не внешний профиль:</p>"
            f"<ul>{items_li}</ul>"
            "</div>"
        )

    # Короткая причина всегда видна строкой под заголовком (inline)
    why_now_inline = _safe(rec.why_now_ru)

    # Детальные секции — скрыты в <details>, раскрываются по запросу
    whynot_section = (
        '<div class="ssr-section" data-testid="e2e-ssr-why-not-others">'
        '<span class="ssr-chip ssr-chip--defer">↔ Другие варианты</span>'
        f"<p><strong>Что с другими режимами:</strong> {_safe(defer_modes)}</p>"
        "</div>"
    )
    contrast_section = (
        '<div class="ssr-section" data-testid="e2e-ssr-contrast">'
        '<span class="ssr-chip ssr-chip--contrast">⚡ Если выбрать иначе:</span>'
        f"<p>{_safe(contrast)}</p>"
        "</div>"
    )
    pedagogy_section = ""
    if pedagogy_line:
        pedagogy_section = (
            '<div class="ssr-section">'
            '<span class="ssr-chip ssr-chip--route">📚 Маршрут</span>'
            f'<p data-testid="e2e-ssr-route-pedagogy">{_safe(pedagogy_line)}</p>'
            "</div>"
        )

    primary_label = _safe(rec.primary_label_ru)

    banner_html = (
        f'<section class="ssr-banner" data-testid="mission-control-ssr-banner" '
        f'data-router-hint="{hint_attr}" role="region" aria-labelledby="{title_id}">'
        # ── Hero: всегда видимая часть ──
        f'<div class="ssr-hero">'
        f'<div class="ssr-kicker">🧭 Подсказка по учебному маршруту</div>'
        f'<h2 id="{title_id}">С чего можно продолжить</h2>'
        f'<p class="ssr-primary-label">{primary_label}</p>'
        f'<p class="ssr-why-inline"><span class="ssr-why-label">Почему это подходит:</span> {why_now_inline}</p>'
        f"</div>"
        # ── Детали: раскрываются по клику (нативный <details>) ──
        f'<details class="ssr-details">'
        f'<summary class="ssr-details-toggle">Как выбрана подсказка</summary>'
        f'<div class="ssr-sections">'
        f"{whynot_section}{contrast_section}{pedagogy_section}{ledger_section}"
        f"</div>"
        f"</details>"
        f"</section>"
    )
    st.html(banner_html)

    btn_label = str(rec.primary_label_ru or "").strip() or "Продолжить обучение"
    st.button(
        btn_label,
        key="mission_control_ssr_primary",
        type="primary",
        on_click=_apply_primary_navigation,
        args=(rec,),
    )
    st.caption(
        "Можно выбрать и другой режим: быстрый ответ, тьютор, quiz, flashcards и прогресс остаются рядом."
    )


def _render_tile(tile: MissionTile, *, recommended_tile: str, due_count: int | None) -> None:
    classes = ["mode-card", "mission-tile"]
    if tile.tile_id == recommended_tile:
        classes.append("smart-recommended")
    badge = ""
    if tile.tile_id == "flashcards":
        if due_count is None:
            badge = '<span class="mode-badge skeleton">...</span>'
        elif due_count > 0:
            badge = f'<span class="mode-badge">{due_count}</span>'
    class_attr = " ".join(classes)
    st.markdown(
        f"""
        <div class="{class_attr}" data-mission-tile="{_safe(tile.tile_id)}" data-testid="mission-tile-{_safe(tile.tile_id)}">
          {badge}
          <div class="mode-icon">{_material_glyph_html(tile.icon)}</div>
          <div class="mode-title">{_safe(tile.title)}</div>
          <div class="mode-desc">{_safe(tile.description)}</div>
          <div class="mode-best-for">{_safe(tile.best_for)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if tile.tile_id == "course" and not get_active_scope():
        st.button(tile.button_label, key=f"mission_tile_{tile.tile_id}", width="stretch", on_click=_course_picker_dialog)
        return
    st.button(
        tile.button_label,
        key=f"mission_tile_{tile.tile_id}",
        width="stretch",
        on_click=_set_navigation_state,
        args=(tile.target_view,),
        kwargs={"slot_hint": tile.slot_hint},
    )
    if tile.tile_id == "course" and get_active_scope():
        st.button("×", key="mission_tile_course_deactivate", help="Деактивировать курс", on_click=_course_deactivate_dialog)


def tile_feature_visible(tile_id: str, *, level: str | None = None, overrides: dict[str, bool] | None = None) -> bool:
    from app.ui.feature_registry import TILE_FEATURE_IDS, feature_by_id

    feature_id = TILE_FEATURE_IDS.get(tile_id)
    if not feature_id:
        return True
    spec = feature_by_id(feature_id)
    if spec is None:
        return True
    return feature_visible(spec, level=level or get_ui_level(), overrides=overrides if overrides is not None else get_overrides())


def _render_tile_grid(
    *,
    rec: SmartStudyRecommendation,
    due_count: int | None,
    cold_user: bool = False,
) -> None:
    all_tiles = _tile_definitions(due_count=due_count)
    recommended_tile = HINT_TO_TILE.get(str(rec.hint_kind), "tutor")
    level = get_ui_level()
    overrides = get_overrides()
    if cold_user:
        tiles = tuple(t for t in all_tiles if t.tile_id in _COLD_USER_TILE_IDS)
        tiles = tuple(t for t in tiles if tile_feature_visible(t.tile_id, level=level, overrides=overrides))
        if not tiles:
            st.caption("Все плитки этого уровня скрыты точными настройками интерфейса.")
            return
        recommended_tile = "quick_question"
        st.markdown('<div class="hero-grid hero-grid--3">', unsafe_allow_html=True)
        cols = st.columns(len(tiles), gap="medium")
        for col, tile in zip(cols, tiles):
            with col:
                _render_tile(tile, recommended_tile=recommended_tile, due_count=due_count)
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        tiles = tuple(t for t in all_tiles if tile_feature_visible(t.tile_id, level=level, overrides=overrides))
        if not tiles:
            st.caption("Все плитки скрыты точными настройками интерфейса.")
            return
        st.markdown('<div class="hero-grid hero-grid--4-3">', unsafe_allow_html=True)
        row1 = st.columns(4, gap="medium")
        for col, tile in zip(row1, tiles[:4]):
            with col:
                _render_tile(tile, recommended_tile=recommended_tile, due_count=due_count)
        row2 = st.columns(3, gap="medium")
        for col, tile in zip(row2, tiles[4:]):
            with col:
                _render_tile(tile, recommended_tile=recommended_tile, due_count=due_count)
        st.markdown("</div>", unsafe_allow_html=True)


@st.dialog("Выбери курс")
def _course_picker_dialog() -> None:
    _render_course_picker_dialog_body()


def _render_course_picker_dialog_body() -> None:
    raw_options = st.session_state.get("mission_control_course_options") or []
    options = [
        CourseOption(
            folder_rel=str(item.get("folder_rel") or "").strip(),
            title=str(item.get("title") or item.get("folder_rel") or "").strip(),
            source_paths=tuple(str(path) for path in item.get("source_paths") or []),
        )
        for item in raw_options
        if isinstance(item, dict) and str(item.get("folder_rel") or "").strip()
    ]
    if not options:
        st.caption("Папки курса пока не найдены в индексе.")
        st.caption("Откройте «Темы» или обновите индекс, чтобы активировать курс по папке.")
        return
    st.caption("Курс ограничивает Q&A, flashcards и прогресс выбранной папкой.")
    labels = [option.label for option in options]
    choice = st.selectbox("Папка", labels, key="mission_control_course_choice")
    selected = options[labels.index(choice)]
    selected_raw = next(
        (
            item
            for item in raw_options
            if isinstance(item, dict)
            and str(item.get("folder_rel") or "").strip() == selected.folder_rel
        ),
        None,
    )
    if isinstance(selected_raw, dict) and selected_raw.get("needs_reindex"):
        st.caption("Папка на диске (≥3 файлов), сначала обновите индекс")
    if selected.source_paths:
        with st.expander("Документы курса", expanded=False):
            for path in selected.source_paths[:8]:
                st.caption(path)
            overflow = len(selected.source_paths) - 8
            if overflow > 0:
                st.caption(f"И ещё {overflow} док.")
    if st.button(
        "Активировать курс",
        type="primary",
        key="mission_control_course_activate",
    ):
        if _activate_course_and_go_topics(selected):
            st.rerun()


def _activate_course_and_go_topics(selected: CourseOption) -> bool:
    try:
        activate_scope(
            folder_rel=selected.folder_rel,
            title=selected.title,
            source_paths=list(selected.source_paths),
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось активировать курс: {exc}")
        return False
    else:
        _set_navigation_state("Темы", slot_hint="course")
        return True


@st.dialog("Деактивировать курс?")
def _course_deactivate_dialog() -> None:
    _render_course_deactivate_dialog_body()


def _render_course_deactivate_dialog_body() -> None:
    scope = get_active_scope() or {}
    title = str(scope.get("title") or scope.get("folder_rel") or "курс")
    st.caption(f"Отключится активная область «{title}». Прогресс и карточки сохраняются.")
    if st.button(
        "Деактивировать",
        type="primary",
        key="mission_control_course_deactivate_confirm",
    ):
        if _deactivate_course_and_go_home():
            st.rerun()


def _deactivate_course_and_go_home() -> bool:
    try:
        deactivate_scope()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось деактивировать курс: {exc}")
        return False
    else:
        clear_first_session_session_cache()
        st.session_state["current_view"] = HOME_VIEW
        return True


def _prefill_and_navigate_to_quick_answer(question: str) -> None:
    q = str(question or "").strip()
    if not q:
        return
    st.session_state["first_session_selected_seed_q"] = q
    st.session_state["question_draft"] = q
    _navigate_to("Быстрый ответ")


def render_first_session_block(
    artifact: dict[str, Any], *, key_prefix: str, folder_rel: str, compact: bool = False
) -> None:
    """Compatibility wrapper for callers outside Mission Control."""
    _render_first_session_block(
        artifact,
        key_prefix=key_prefix,
        folder_rel=folder_rel,
        compact=compact,
        navigate_to_question=_prefill_and_navigate_to_quick_answer,
    )


def _build_kg_mini_svg(concepts: dict, mastery_vector: dict) -> str:
    """Deterministic mini SVG preview of the knowledge graph nodes + sampled edges."""
    _LEVEL_COLORS: dict[str, str] = {
        "lesson":       "#fbbf24",
        "beginner":     "#38bdf8",
        "intermediate": "#a78bfa",
        "advanced":     "#fb7185",
        "unknown":      "#94a3b8",
    }
    valid = [(cid, data) for cid, data in concepts.items() if isinstance(data, dict)]
    valid.sort(key=lambda x: (
        0 if str(x[1].get("level") or "").strip() == "lesson" else 1,
        -mastery_vector.get(x[0], 0.0),
    ))
    sample = valid[:30]
    n = len(sample)
    if not n:
        return ""

    W, H = 500, 160
    cx, cy = W / 2, H / 2
    rng = random.Random(42)

    # Compute positions
    positions: list[tuple[float, float]] = []
    for i in range(n):
        angle = (i / n) * 2 * math.pi + rng.uniform(-0.6, 0.6)
        spread = rng.uniform(38, 66)
        x = max(14.0, min(W - 14.0, cx + spread * math.cos(angle)))
        y = max(12.0, min(H - 12.0, cy * 0.85 + spread * 0.62 * math.sin(angle)))
        positions.append((x, y))

    # Draw a sparse web of edges (every 3rd node connects to the next, plus a few cross-links)
    edge_parts: list[str] = []
    for i in range(n):
        j = (i + 1) % n
        x1, y1 = positions[i]
        x2, y2 = positions[j]
        edge_parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#ffffff" stroke-width="0.6" opacity="0.12"/>'
        )
    for k in range(0, n - 3, 4):
        x1, y1 = positions[k]
        x2, y2 = positions[(k + 3) % n]
        edge_parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#ffffff" stroke-width="0.5" opacity="0.09"/>'
        )

    # Draw nodes on top of edges
    node_parts: list[str] = []
    for i, (cid, data) in enumerate(sample):
        x, y = positions[i]
        level = str(data.get("level") or "").strip().lower()
        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["unknown"])
        mastery = float(mastery_vector.get(cid, 0.0))
        is_lesson = level == "lesson"
        r = 10.0 if is_lesson else max(5.0, 5.0 + mastery * 5.0)
        if data.get("frontier"):
            node_parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 4.5:.1f}" '
                f'fill="none" stroke="{color}" stroke-width="1.5" opacity="0.45"/>'
            )
        # Glow halo
        node_parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 1.5:.1f}" '
            f'fill="{color}" opacity="0.18"/>'
        )
        node_parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}" opacity="0.92"/>'
        )

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="display:block;width:100%;height:auto;" aria-hidden="true">'
        + "".join(edge_parts)
        + "".join(node_parts)
        + "</svg>"
    )


def render_kg_mission_card() -> None:
    """Compact Knowledge Graph teaser card for Mission Control."""
    from app.ui.feature_registry import feature_by_id

    spec = feature_by_id("view:knowledge_graph")
    if spec and not feature_visible(spec, level=get_ui_level(), overrides=get_overrides()):
        return
    try:
        from app.knowledge_service import knowledge_graph, get_mastery_vector
        concepts = knowledge_graph.get_concepts()
        if not concepts:
            return
    except Exception:  # noqa: BLE001 - optional card, must never crash Mission Control
        return

    try:
        mastery_vector = get_mastery_vector()
    except Exception:  # noqa: BLE001
        mastery_vector = {}

    valid = {cid: data for cid, data in concepts.items() if isinstance(data, dict)}
    total = len(valid)
    lessons = sum(1 for d in valid.values() if str(d.get("level") or "").strip() == "lesson")
    frontier = sum(1 for d in valid.values() if d.get("frontier"))
    avg_mastery = round(
        sum(mastery_vector.get(cid, 0.0) for cid in valid) / max(total, 1) * 100
    )
    concept_nodes = total - lessons

    mini_svg = _build_kg_mini_svg(valid, mastery_vector)
    st.html(
        f'<div class="kg-mc-card" data-testid="mc-kg-card">'
        f'<div class="kg-mc-header">'
        f'<span class="kg-mc-icon">🕸</span>'
        f'<div class="kg-mc-titles">'
        f'<div class="kg-mc-title">Knowledge Graph</div>'
        f'<div class="kg-mc-subtitle">Визуальная карта знаний курса — клик по узлу открывает детали</div>'
        f'</div></div>'
        f'<div class="kg-mc-preview">{mini_svg}</div>'
        f'<div class="kg-mc-stats">'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{concept_nodes}</span>'
        f'<span class="kg-mc-lbl">концептов</span></div>'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{lessons}</span>'
        f'<span class="kg-mc-lbl">лекций</span></div>'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{frontier}</span>'
        f'<span class="kg-mc-lbl">готово учить</span></div>'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{avg_mastery}%</span>'
        f'<span class="kg-mc-lbl">mastery</span></div>'
        f'</div></div>'
    )
    st.button(
        "Открыть Knowledge Graph →",
        key="mc_kg_open_btn",
        width="stretch",
        on_click=_set_navigation_state,
        args=("Knowledge Graph",),
    )


def build_living_konspekt_card_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Чистая сводка корзины «Живого конспекта» для resume-карточки (тестируется отдельно)."""
    documents = {str(row.get("konspekt_md_abs") or "") for row in rows if row.get("konspekt_md_abs")}
    concepts = [
        concept
        for concept in dict.fromkeys(str(row.get("concept") or "").strip() for row in rows)
        if concept
    ]
    recent_headings = [
        heading
        for heading in (str(row.get("heading_text") or "").strip() for row in reversed(rows))
        if heading
    ][:2]
    return {
        "sections": len(rows),
        "documents": len(documents),
        "concepts": len(concepts),
        "recent_headings": recent_headings,
    }


def render_living_konspekt_mission_card() -> None:
    """Resume-карточка «Живой конспект»: продолжить сборку с того места, где остановился.

    Показывается только при непустой корзине (для новых пользователей — ноль шума).
    Корзина автосохраняется в app_kv, поэтому карточка переживает перезапуск приложения.
    """
    from app.ui.feature_registry import feature_by_id

    spec = feature_by_id("view:living_konspekt")
    if spec and not feature_visible(spec, level=get_ui_level(), overrides=get_overrides()):
        return
    try:
        from app import workbench_service

        if workbench_service.WORKBENCH_SECTIONS_KEY not in st.session_state:
            st.session_state[workbench_service.WORKBENCH_SECTIONS_KEY] = workbench_service.load_rows()
        rows = workbench_service.normalize_runtime_rows(
            list(st.session_state.get(workbench_service.WORKBENCH_SECTIONS_KEY) or [])
        )
    except Exception:  # noqa: BLE001 - optional card, must never crash Mission Control
        return
    if not rows:
        return

    stats = build_living_konspekt_card_stats(rows)
    recent = " · ".join(html.escape(heading) for heading in stats["recent_headings"])
    subtitle = f"Последние разделы: {recent}" if recent else "Сборка рабочего конспекта из разделов лекций"
    st.html(
        f'<div class="kg-mc-card" data-testid="mc-living-konspekt-card">'
        f'<div class="kg-mc-header">'
        f'<span class="kg-mc-icon">📚</span>'
        f'<div class="kg-mc-titles">'
        f'<div class="kg-mc-title">Живой конспект — сборка не закончена</div>'
        f'<div class="kg-mc-subtitle">{subtitle}</div>'
        f'</div></div>'
        f'<div class="kg-mc-stats">'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{stats["sections"]}</span>'
        f'<span class="kg-mc-lbl">разделов</span></div>'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{stats["documents"]}</span>'
        f'<span class="kg-mc-lbl">лекций</span></div>'
        f'<div class="kg-mc-stat"><span class="kg-mc-num">{stats["concepts"]}</span>'
        f'<span class="kg-mc-lbl">концептов</span></div>'
        f'</div></div>'
    )
    st.button(
        "Продолжить сборку →",
        key="mc_living_konspekt_open_btn",
        width="stretch",
        on_click=_set_navigation_state,
        args=("Живой конспект",),
    )


def render_mission_control(index_stats: dict | None = None) -> None:
    """Render the single home hero with SSR and seven destination tiles."""
    poll_reindex_status()
    preflight_status = render_preflight_card()
    if preflight_status == "api_down":
        return
    if render_empty_index_hero(index_stats):
        return
    render_demo_sandbox_banner(index_stats)
    settings = get_settings()
    if settings.session_tape_full_events_enabled and not st.session_state.get("_mission_loaded_emitted"):
        try:
            from app.session_tape import append_event

            session_id = str(st.session_state.get("_session_tape_id") or "").strip()
            if session_id:
                append_event(
                    session_id,
                    "mission_loaded",
                    {
                        "status": "ready" if index_stats else "empty",
                        "variant": "cockpit_v2" if settings.rag_course_cockpit_v2 else "classic",
                    },
                    surface="mission_control",
                )
                st.session_state["_mission_loaded_emitted"] = True
        except Exception as exc:  # noqa: BLE001 - Mission Control must keep rendering
            import logging

            logging.getLogger(__name__).debug("mission_loaded tape event skipped: %s", exc)
    st.session_state["mission_control_course_options"] = build_mission_control_course_options(
        index_stats
    )
    rec = _build_recommendation(index_stats)
    due_count = _flashcards_due_count()
    cold = _is_cold_user(due_count, index_stats)
    first_session_rendered = render_first_session_hero(
        index_stats,
        navigate_to_question=_prefill_and_navigate_to_quick_answer,
    )
    if not first_session_rendered:
        render_seed_question_chips(
            key_prefix="mission_control",
            navigate_to_question=_prefill_and_navigate_to_quick_answer,
            index_stats=index_stats,
            topics_catalog=st.session_state.get("topics_catalog"),
            first_session_artifact=None,
        )
    _apply_e2e_delight_completion()
    render_delight_progress_rail(st.session_state.get("delight_loop_completed_steps"))
    if not cold:
        _render_ssr_banner(rec, index_stats=index_stats)
    _render_tile_grid(rec=rec, due_count=due_count, cold_user=cold)
    if st.button("⚙️ Настроить интерфейс", key="mission_control_configure_ui"):
        from app.ui.control_panel import render_control_panel_dialog

        render_control_panel_dialog()
    if not cold:
        render_kg_mission_card()
        render_living_konspekt_mission_card()


def assert_hint_mapping_complete() -> None:
    """Test helper: every SmartStudyRouter hint must map to a tile."""
    missing = set(get_args(SmartStudyRouterHintKind)) - set(HINT_TO_TILE)
    if missing:
        raise AssertionError(f"Missing Mission Control tile mapping: {sorted(missing)}")


DELIGHT_LOOP_STEPS: list[str] = [
    "Q&A",
    "Tutor",
    "Quiz",
    "Card",
    "Review",
    "Graduation",
]


def _apply_e2e_delight_completion() -> None:
    """Seed and persist Golden-loop completion only in the offline E2E stack."""
    settings = get_settings()
    complete = str(st.query_params.get("e2e_delight_complete") or "").lower()
    if not settings.home_rag_e2e_offline or complete not in {"1", "true", "yes"}:
        return

    from app.course_graduation import emit_e2e_graduation_event

    st.session_state["delight_loop_completed_steps"] = list(DELIGHT_LOOP_STEPS)
    graduation_metadata = {
        "llm_model": str(settings.llm_model),
        "llm_source": "local",
        "fallback_used": False,
    }
    st.session_state["delight_loop_graduation_metadata"] = graduation_metadata
    if st.session_state.get("e2e_delight_graduation_emitted"):
        return

    session_id = str(st.query_params.get("e2e_delight_session") or "golden-e2e-graduation")
    course_id = str(st.query_params.get("e2e_scope_folder") or "") or None
    emit_e2e_graduation_event(
        session_id,
        course_id=course_id,
        **graduation_metadata,
    )
    st.session_state["e2e_delight_graduation_emitted"] = True


def render_delight_progress_rail(completed_steps: list[str] | None = None) -> None:
    """Render guided delight loop progress rail with step labels and completion state.

    completed_steps: list of step names that are already done (subset of DELIGHT_LOOP_STEPS).
    """
    import streamlit as st

    done = set(completed_steps or [])
    cols = st.columns(len(DELIGHT_LOOP_STEPS))
    for col, step in zip(cols, DELIGHT_LOOP_STEPS):
        step_testid = "".join(char.lower() if char.isalnum() else "-" for char in step).strip("-")
        with col:
            if step in done:
                st.markdown(
                    f'<div data-testid="delight-step-{step_testid}" data-status="complete" '
                    f'style="text-align:center;color:#22c55e;font-weight:bold;">✓ {step}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div data-testid="delight-step-{step_testid}" data-status="pending" '
                    f'style="text-align:center;color:#94a3b8;">{step}</div>',
                    unsafe_allow_html=True,
                )

    graduation_metadata = st.session_state.get("delight_loop_graduation_metadata")
    if isinstance(graduation_metadata, dict):
        model = _safe(graduation_metadata.get("llm_model"))
        source = _safe(graduation_metadata.get("llm_source"))
        fallback = str(bool(graduation_metadata.get("fallback_used"))).lower()
        st.markdown(
            f'<div data-testid="e2e-graduation-metadata" data-llm-model="{model}" '
            f'data-llm-source="{source}" data-fallback-used="{fallback}" '
            'style="display:none"></div>',
            unsafe_allow_html=True,
        )


def build_ssr_evidence_for_banner(index_stats: dict | None = None) -> list[str]:
    """Tiny public helper for tests and future diagnostics."""
    try:
        from app.ui.resume_cards import gather_smart_study_router_session_context

        ctx = gather_smart_study_router_session_context(index_stats=index_stats)
        qf_status: str | None = None
        if ctx.effective_tutor_snap:
            qfx = ctx.effective_tutor_snap.get("quiz_feedback")
            if isinstance(qfx, dict):
                qf_status = str(qfx.get("status") or "").strip() or None
        return build_smart_study_evidence_ledger_lines(
            flashcard_due_n=ctx.flashcard_due_n,
            sm2_due_n=ctx.sm2_due_n,
            quiz_feedback_status=qf_status,
            has_last_answer_qa=ctx.has_last_answer_qa,
            last_answer=ctx.last_answer if isinstance(ctx.last_answer, dict) else None,
            tutor_trust=None,
            include_all=True,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics only.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("mission control evidence fallback: %s", exc)
        return []
