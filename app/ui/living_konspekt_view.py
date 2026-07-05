"""«Живой конспект» — study-поверхность над Section Anchor Index.

Корзина (:data:`WORKBENCH_SECTIONS_KEY`) живёт в ``st.session_state`` и
**автосохраняется** в локальный профиль (``app_kv``, ключ
:data:`_WORKBENCH_KV_KEY`) при каждом изменении — переживает rerun, перезапуск
и закрытие вкладки. Гидрация из профиля — один раз за сессию
(:func:`ensure_workbench_hydrated`). Именованные research-сессии
(``save_research_session``/``apply_research_payload``) остаются как снимки-варианты.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, MutableMapping

import streamlit as st

from app.deep_study_prompt import build_deep_study_prompt
from app.section_index import IndexedSection, row_to_section, section_to_row
from app.study_web_queries import (
    build_query_from_rows,
    build_query_terms,
    build_web_search_links,
    harvest_links_from_rows,
)
from app.ui.helpers import format_request_error
from app.ui.widgets import render_panel_header

WORKBENCH_SECTIONS_KEY = "workbench_sections"
_WORKBENCH_KV_KEY = "living_konspekt_workbench_json"
_WORKBENCH_HYDRATED_KEY = "_workbench_hydrated"

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)


# ── Корзина (JSON-safe rows из app.section_index) ───────────────────────
# ``state`` — опциональный DI-параметр (по умолчанию ``st.session_state``): позволяет
# юнит-тестировать add/dedup/remove на обычном dict без запуска Streamlit runtime.
# Авто-персист в app_kv срабатывает ТОЛЬКО на реальном session_state (``state is None``) —
# инжектированный dict в тестах не должен писать в user_state.db.
def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    return state if state is not None else st.session_state


def _ensure_auth_context() -> None:
    from app.ui.auth_gate import ensure_streamlit_auth_context

    ensure_streamlit_auth_context()


def _persist_workbench(rows: list[dict[str, Any]]) -> None:
    """Best-effort автосохранение корзины в локальный профиль (``app_kv``)."""
    try:
        from app.user_state_core import set_kv

        _ensure_auth_context()
        set_kv(_WORKBENCH_KV_KEY, json.dumps(rows, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - авто-персист не должен ломать работу корзины
        pass


def ensure_workbench_hydrated(state: MutableMapping[str, Any] | None = None) -> None:
    """Один раз за сессию поднять корзину из локального профиля (``app_kv``).

    Если в session_state корзина уже есть (rerun, restore research-сессии) —
    профиль не читается: сессия свежее.
    """
    target = _state(state)
    if target.get(_WORKBENCH_HYDRATED_KEY):
        return
    target[_WORKBENCH_HYDRATED_KEY] = True
    if WORKBENCH_SECTIONS_KEY in target:
        return
    try:
        from app.user_state_core import get_kv

        _ensure_auth_context()
        raw = get_kv(_WORKBENCH_KV_KEY)
        rows = json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 - недоступный профиль → пустая корзина, не падение
        return
    if isinstance(rows, list) and rows:
        target[WORKBENCH_SECTIONS_KEY] = [row for row in rows if isinstance(row, dict)]


def set_workbench_rows(
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Заменить корзину целиком (restore research-сессии) + авто-персист."""
    target = _state(state)
    target[WORKBENCH_SECTIONS_KEY] = [row for row in rows if isinstance(row, dict)]
    target[_WORKBENCH_HYDRATED_KEY] = True
    if state is None:
        _persist_workbench(target[WORKBENCH_SECTIONS_KEY])


def get_workbench_rows(state: MutableMapping[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = _state(state).get(WORKBENCH_SECTIONS_KEY)
    return rows if isinstance(rows, list) else []


def add_section_to_workbench(
    section: IndexedSection,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Добавить раздел в корзину; дедуп по ``(konspekt_md_abs, line_start)``.

    Возвращает ``True``, если раздел был новым (добавлен), ``False`` — если уже был в корзине.
    """
    target = _state(state)
    rows = get_workbench_rows(target)
    dedup_key = (str(section.konspekt_md_abs), section.line_start)
    for row in rows:
        if (str(row.get("konspekt_md_abs") or ""), row.get("line_start")) == dedup_key:
            return False
    rows.append(section_to_row(section))
    target[WORKBENCH_SECTIONS_KEY] = rows
    if state is None:
        _persist_workbench(rows)
        try:
            # Funnel «чтение → обучение»: раздел добавлен (из графа/карточки/сбора по концепту).
            from app.ui_events import track_event

            track_event("living_konspekt_section_added")
        except Exception:  # noqa: BLE001 - аналитика не должна ломать корзину
            pass
    return True


def remove_section_from_workbench(
    konspekt_md_abs: str,
    line_start: int,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = get_workbench_rows(target)
    target[WORKBENCH_SECTIONS_KEY] = [
        row
        for row in rows
        if not (
            str(row.get("konspekt_md_abs") or "") == konspekt_md_abs
            and row.get("line_start") == line_start
        )
    ]
    if state is None:
        _persist_workbench(target[WORKBENCH_SECTIONS_KEY])


# ── Сборка рабочего конспекта ────────────────────────────────────────────
def _lecture_main_ideas(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """``[(имя конспекта, первый абзац главной мысли), ...]`` по уникальным документам корзины.

    «Дух лекции» едет в сам артефакт, а не только в deep-study промпт. Конспект без
    раздела-роли ``main_idea`` (или недоступный файл) молча пропускается.
    """
    try:
        from app.section_index import main_idea_section, sections_by_role, _cached_parse_sections
    except Exception:  # noqa: BLE001 - обогащение опционально
        return []

    md_paths: list[str] = []
    for row in rows:
        md = str(row.get("konspekt_md_abs") or "")
        if md and md not in md_paths:
            md_paths.append(md)

    out: list[tuple[str, str]] = []
    for md in md_paths:
        try:
            parsed = _cached_parse_sections(Path(md))
        except OSError:
            continue
        # Роль → эвристика main_idea_section (первая содержательная H2) — как в промпте.
        main_idea = sections_by_role(parsed).get("main_idea") or main_idea_section(parsed)
        if main_idea is None or not main_idea.text.strip():
            continue
        first_paragraph = main_idea.text.strip().split("\n\n", 1)[0].strip()
        if first_paragraph:
            out.append((Path(md).name, first_paragraph))
    return out


def _sources_footer(rows: list[dict[str, Any]]) -> str:
    """«## Источники» со списком ``файл:строки`` всех разделов — провенанс живёт в самом
    сохранённом файле, а не только в session_state. Пустая корзина → пустая строка."""
    source_lines = [
        f"- {Path(str(row.get('konspekt_md_abs') or '')).name}:{row.get('line_start')}-{row.get('line_end')}"
        f" — «{row.get('heading_text') or '—'}»"
        for row in rows
    ]
    return "## Источники\n\n" + "\n".join(source_lines) if source_lines else ""


_MAX_CHECK_QUESTIONS = 8


def _check_questions_block(rows: list[dict[str, Any]]) -> str:
    """«## ✅ Проверь себя» из роли ``check_questions`` конспектов корзины (дословно,
    вопросы лектора). Роли нет / файлы недоступны → пустая строка (честная деградация)."""
    try:
        from app.section_index import sections_by_role, _cached_parse_sections
    except Exception:  # noqa: BLE001 - обогащение опционально
        return ""

    md_paths: list[str] = []
    for row in rows:
        md = str(row.get("konspekt_md_abs") or "")
        if md and md not in md_paths:
            md_paths.append(md)

    questions: list[str] = []
    for md in md_paths:
        try:
            parsed = _cached_parse_sections(Path(md))
        except OSError:
            continue
        section = sections_by_role(parsed).get("check_questions")
        if section is None:
            continue
        for line in section.text.splitlines():
            line = line.strip()
            if line:
                questions.append(line)
            if len(questions) >= _MAX_CHECK_QUESTIONS:
                break
        if len(questions) >= _MAX_CHECK_QUESTIONS:
            break
    if not questions:
        return ""
    return "## ✅ Проверь себя\n\n" + "\n".join(questions)


def _study_pack_tail(rows: list[dict[str, Any]]) -> str:
    """Хвост Study Pack: «Проверь себя» + «Источники» — для ОБОИХ режимов сборки.

    LLM-синтез отдаёт только summary; без этого хвоста сохранённый файл терял провенанс
    (Findings по ``рабочий-конспект-лекция-2.md``: «Источники» — только имя файла).
    """
    blocks = [block for block in (_check_questions_block(rows), _sources_footer(rows)) if block]
    return "\n\n".join(blocks)


def _stitch_verbatim(rows: list[dict[str, Any]]) -> str:
    """Детерминированная склейка: главная мысль лекции + заголовки-источники + якоря + текст.

    В конец — «Проверь себя» (вопросы лектора) и «## Источники» (``файл:строки``).
    """
    header_parts = [
        f"> **Главная мысль исходной лекции ({doc_name}):** {idea}"
        for doc_name, idea in _lecture_main_ideas(rows)
    ]

    parts: list[str] = []
    for row in rows:
        heading = str(row.get("heading_text") or "Без названия")
        source_name = Path(str(row.get("konspekt_md_abs") or "")).name
        location = f"{source_name}:{row.get('line_start')}"
        parts.append(f"## {heading}\n\n*Источник: {location}*\n\n{row.get('text') or ''}")

    blocks: list[str] = []
    if header_parts:
        blocks.append("\n>\n".join(header_parts))
    blocks.append("\n\n---\n\n".join(parts))
    tail = _study_pack_tail(rows)
    if tail:
        blocks.append(tail)
    return "\n\n".join(blocks)


def _filename_slug(title: str) -> str:
    s = title.strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    return s or "konspekt"


def _unique_target_path(base_dir: Path, slug: str) -> Path:
    candidate = base_dir / f"{slug}.md"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"{slug}-{counter}.md"
        counter += 1
    return candidate


def _save_living_konspekt(title: str, body_markdown: str) -> Path:
    """Сохранить в ``vault_root()/"living-konspekt"/<slug>.md`` — НЕ ``vault_target()``.

    ``vault_target()`` требует ``source_abs`` и зеркалит путь исходника; у рабочего
    конспекта нет единого исходника (это сборка из нескольких документов).
    """
    from app.obsidian_export import vault_root

    target_dir = vault_root() / "living-konspekt"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = _unique_target_path(target_dir, _filename_slug(title))
    target_path.write_text(f"# {title}\n\n{body_markdown}\n", encoding="utf-8")
    return target_path


# ── UI ────────────────────────────────────────────────────────────────────
def _duplicate_heading_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """``(konspekt_md_abs, heading_text)`` с >1 разделом в корзине.

    Obsidian-якорь открывает **первый** одноимённый heading в файле — при дублях он может
    привести не туда, куда собрали раздел (см. план, «Тонкий риск — одинаковые заголовки»).
    """
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("konspekt_md_abs") or ""), str(row.get("heading_text") or ""))
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _heading_ambiguous(md_abs: str, heading_text: str) -> bool:
    """Дубль заголовка в самом ДОКУМЕНТЕ (не только среди собранных rows).

    Дубль опасен, даже когда в корзине лежит лишь одна из копий — якорь всё равно
    откроет первый одноимённый heading файла.
    """
    if not md_abs or not heading_text:
        return False
    try:
        from app.section_index import heading_repeats_in_document

        return heading_repeats_in_document(Path(md_abs), heading_text)
    except Exception:  # noqa: BLE001 - подпись о дублях не должна ломать рендер корзины
        return False


def _render_collected_sections(rows: list[dict[str, Any]]) -> None:
    from app.obsidian_export import obsidian_uri, vscode_uri

    st.markdown("### Собранные разделы")
    duplicate_keys = _duplicate_heading_keys(rows)
    for row in list(rows):
        md_abs = str(row.get("konspekt_md_abs") or "")
        line_start = row.get("line_start")
        heading_text = str(row.get("heading_text") or "")
        with st.container(border=True):
            cols = st.columns([5, 1, 1])
            with cols[0]:
                st.markdown(f"**{heading_text or '—'}**")
                st.caption(f"{Path(md_abs).name} · строки {line_start}-{row.get('line_end')}")
                if (md_abs, heading_text) in duplicate_keys or _heading_ambiguous(md_abs, heading_text):
                    st.caption("⚠️ Заголовок повторяется в документе — VS Code точнее для повторяющихся заголовков.")
                st.write(str(row.get("text") or "")[:400])
            with cols[1]:
                if md_abs:
                    st.link_button(
                        "📄 Открыть",
                        obsidian_uri(Path(md_abs), heading_text=heading_text),
                        width="stretch",
                    )
                    st.link_button(
                        "🖥 VS Code",
                        vscode_uri(Path(md_abs), line=int(line_start) if line_start else None),
                        width="stretch",
                    )
            with cols[2]:
                if st.button("🗑 Убрать", key=f"wb_remove_{md_abs}_{line_start}", width="stretch"):
                    remove_section_from_workbench(md_abs, int(line_start) if line_start else 0)
                    st.rerun()


def _render_build_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 📚 Собрать рабочий конспект")
    topic = st.text_input(
        "Название конспекта",
        value=st.session_state.get("living_konspekt_title") or "Рабочий конспект",
        key="living_konspekt_title",
    )
    mode = st.radio(
        "Способ сборки",
        ["Дословная сшивка (без LLM)", "LLM-синтез из разделов"],
        key="living_konspekt_mode",
        horizontal=True,
    )
    if st.button("Собрать и сохранить", key="living_konspekt_build", type="primary"):
        try:
            if mode.startswith("Дословная"):
                body = _stitch_verbatim(rows)
            else:
                from app.knowledge_synthesis import synthesize_sections  # heavy: LLM/Chroma services

                sections = [row_to_section(row) for row in rows]
                result = synthesize_sections(topic=topic, sections=sections)
                # Study Pack tail и для LLM-режима: summary модели без «Проверь себя» и
                # точных «файл:строки» — статичная выжимка, а не живой конспект.
                body = "\n\n".join(
                    block for block in (str(result["summary"]).strip(), _study_pack_tail(rows)) if block
                )
            target_path = _save_living_konspekt(topic, body)
        except Exception as exc:  # noqa: BLE001 - показать пользователю причину сбора/сохранения
            st.error(f"Не удалось собрать конспект: {format_request_error(exc)}")
        else:
            st.session_state["living_konspekt_last_saved"] = str(target_path)
            try:
                from app.ui_events import track_event

                track_event(
                    "living_konspekt_saved",
                    {"mode": "verbatim" if mode.startswith("Дословная") else "synthesis", "sections": len(rows)},
                )
            except Exception:  # noqa: BLE001 - аналитика не должна ломать сохранение
                pass
            st.success("✅ Сохранено в vault. Войдёт в поиск и граф после обновления индекса.")

    # Файл — стартовая площадка, а не финал: постоянный CTA-ряд по последнему сохранённому
    # (переживает rerun'ы — success-строка выше живёт только один прогон).
    last_saved = str(st.session_state.get("living_konspekt_last_saved") or "")
    if last_saved:
        from app.obsidian_export import obsidian_uri, vscode_uri

        saved_path = Path(last_saved)
        st.caption(f"Последний собранный: `{saved_path.name}`")
        cta_cols = st.columns(2)
        with cta_cols[0]:
            st.link_button("📄 Открыть в Obsidian", obsidian_uri(saved_path), width="stretch")
        with cta_cols[1]:
            st.link_button("🖥 Открыть в VS Code", vscode_uri(saved_path), width="stretch")
        st.caption("Следующий шаг: «🃏 Карточки из терминов» ниже — и конспект начнёт повторяться сам.")


def _due_by_document(rows: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    """``[(имя конспекта, source-тег, due), ...]`` по уникальным документам корзины.

    Карточки несут системный тег ``source:<rel>`` (термины из «Живого конспекта»,
    course-генерация) — SM-2 due по этому тегу и есть «состояние памяти» конспекта.
    Недоступная БД → пустой список (панель просто не рисуется).
    """
    from app.term_cards import source_tag_value

    md_paths: list[str] = []
    for row in rows:
        md = str(row.get("konspekt_md_abs") or "")
        if md and md not in md_paths:
            md_paths.append(md)

    out: list[tuple[str, str, int]] = []
    for md in md_paths:
        tag = f"source:{source_tag_value(Path(md))}"
        try:
            from app import user_state

            due = int(user_state.count_due_flashcards(tags=tag))
        except Exception:  # noqa: BLE001 - память опциональна, корзина работает и без БД
            continue
        out.append((Path(md).name, tag, due))
    return out


def _render_memory_panel(rows: list[dict[str, Any]]) -> None:
    """«🧠 Память конспекта» — замыкание петли: конспект → карточки → угасание → возврат.

    Показывает due-карточки, привязанные к конспектам корзины; «Повторить» открывает
    review-очередь Flashcards, скоупнутую тегом ``source:`` именно на этот конспект
    (тег-скоуп — штатный, через ключ ``flashcards_review_session_tags_text``).
    Нет due — панель молчит: ноль шума, пока память не начала угасать.
    """
    entries = [(doc_name, tag, due) for doc_name, tag, due in _due_by_document(rows) if due > 0]
    if not entries:
        return
    st.markdown("### 🧠 Память конспекта")
    st.caption("Карточки из этих конспектов ждут повторения — забытое подсвечивается здесь само.")
    for doc_name, tag, due in entries:
        mem_cols = st.columns([4, 2])
        with mem_cols[0]:
            st.markdown(f"**{doc_name}** — {due} карточк(и) к повторению")
        with mem_cols[1]:
            if st.button("🔁 Повторить", key=f"wb_review_{tag}", width="stretch"):
                from app.ui.flashcards_sections import FC_MAIN_SECTION_REVIEW, pending_section_key
                from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

                # Ключ text_input тег-скоупа в review: установка ДО инстанцирования
                # виджета (следующий прогон) легальна; scope-signature сам сбросит сессию.
                st.session_state["flashcards_review_session_deck_id"] = None
                st.session_state["flashcards_review_deck_sync_pending"] = None
                st.session_state["flashcards_review_session_tags_text"] = tag
                st.session_state["flashcards_review_session_tag_ids"] = [tag]
                st.session_state["flashcards_review_queue"] = []
                st.session_state["flashcards_review_index"] = 0
                st.session_state["flashcards_card_flipped"] = False
                st.session_state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
                st.session_state["flashcards_review_session_status"] = "idle"
                st.session_state["flashcards_review_session_error"] = None
                st.session_state.pop("flashcards_review_session_scope_signature", None)
                st.session_state[pending_section_key()] = FC_MAIN_SECTION_REVIEW
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
                try:
                    from app.ui_events import track_event

                    track_event("living_konspekt_review_loop_opened", {"due": due})
                except Exception:  # noqa: BLE001
                    pass
                st.rerun()


def _render_term_cards_panel(rows: list[dict[str, Any]]) -> None:
    """Карточки из сохранённых разделов «Важные термины» без нового LLM-вызова.

    Переиспользует preview редактор Flashcards (те же ``fc_preview_*`` session_state
    ключи, что заполняет ``render_generate``): редактирование/удаление/сохранение —
    уже готовый UI, не дублируем.
    """
    from app.term_cards import term_cards_from_documents

    st.markdown("### 🃏 Карточки из терминов лекции (без LLM)")
    md_paths = list(dict.fromkeys(str(row.get("konspekt_md_abs") or "") for row in rows if row.get("konspekt_md_abs")))
    cards, source_docs = term_cards_from_documents(md_paths)
    if not cards:
        st.caption(
            "В конспектах собранных разделов нет раздела «🧠 Важные термины и концепции» — "
            "карточки собрать не из чего."
        )
        return
    deck_title = f"Термины — {', '.join(source_docs)}"[:120]
    st.caption(
        f"Найдено {len(cards)} терминов с определениями в {len(source_docs)} конспект(ах): "
        + ", ".join(source_docs)
        + ". Карточки собираются без нового LLM-вызова: front/back берутся из уже сохранённого конспекта."
    )
    if len(cards) < 5:
        st.caption(
            f"Для сохранения колоды нужно минимум 5 карточек, сейчас найдено {len(cards)}. "
            "Добавьте в корзину разделы из других конспектов с терминами."
        )
        return
    if st.button("🃏 Создать карточки из терминов", key="wb_term_cards_btn", type="primary"):
        from app.ui.flashcards_sections import FC_MAIN_SECTION_CREATE, pending_section_key
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        _clear_flashcards_preview_widget_state()
        st.session_state["fc_preview_cards"] = cards
        st.session_state["fc_preview_title"] = deck_title
        st.session_state["fc_deck_name"] = deck_title
        st.session_state["fc_preview_source_type"] = "living_konspekt_terms"
        st.session_state["fc_preview_source_identifier"] = ", ".join(source_docs)
        st.session_state[pending_section_key()] = FC_MAIN_SECTION_CREATE
        # PENDING_CURRENT_VIEW_KEY, не прямая запись: current_view — ключ уже
        # инстанцированного st.selectbox в main.py на этом прогоне.
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
        try:
            from app.ui_events import track_event

            track_event("living_konspekt_term_cards_created", {"cards": len(cards)})
        except Exception:  # noqa: BLE001
            pass
        st.rerun()


def _clear_flashcards_preview_widget_state() -> None:
    """Drop stale preview editor widget values before opening Flashcards create."""
    stale_prefixes = ("prev_f_", "prev_b_", "prev_t_")
    for key in list(st.session_state.keys()):
        if key == "fc_deck_name" or (isinstance(key, str) and key.startswith(stale_prefixes)):
            st.session_state.pop(key, None)


def _render_web_queries_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 🌐 Проверить актуальность · источники")

    # «Источник этих знаний» без сети: ссылки, которые лектор сам приложил к материалу.
    lecture_links = harvest_links_from_rows(rows)
    if lecture_links:
        st.markdown("**🔗 Ссылки из лекции**")
        for label, url in lecture_links[:8]:
            st.markdown(f"- [{label}]({url})")

    query = build_query_from_rows(rows)
    if not query:
        # Разделы без концепта и с пустыми заголовками — фолбэк на свалку заголовков.
        heading_texts = [str(row.get("heading_text") or "") for row in rows]
        key_concepts = [str(row.get("concept") or "") for row in rows if row.get("concept")]
        query = build_query_terms(heading_texts=heading_texts, key_concepts=key_concepts)
    links = build_web_search_links(query)
    if not links:
        st.caption("Добавьте разделы, чтобы сформировать поисковый запрос.")
        return
    st.caption(f"Запрос: «{query}»")
    link_cols = st.columns(len(links))
    for col, (label, url) in zip(link_cols, links):
        with col:
            st.link_button(label, url, width="stretch")


_EXTERNAL_LLM_TARGETS = (
    ("ChatGPT", "https://chatgpt.com/"),
    ("Claude", "https://claude.ai/new"),
    ("Gemini", "https://gemini.google.com/app"),
)


def _collect_concept_context(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Prerequisites/related_concepts для всех уникальных концептов, привязанных к разделам корзины.

    Раздел получает ``concept`` только когда его добавили из графа
    (``_render_document_section_workbench_buttons`` в ``dashboards_graph.py``); разделы из
    Flashcards приходят без концепта — тогда контекст пуст, и это ожидаемо (нет графового
    привязки, откуда брать prerequisites).
    """
    concept_ids = sorted({str(row.get("concept") or "").strip() for row in rows if row.get("concept")})
    if not concept_ids:
        return [], []
    try:
        from app.knowledge_service import get_active_knowledge_graph

        kg = get_active_knowledge_graph()
        all_concepts = kg.get_concepts()
    except Exception:  # noqa: BLE001 - контекст концепта опционален для промпта
        return [], []

    prereqs: list[str] = []
    related: list[str] = []
    for cid in concept_ids:
        prereqs.extend(str(p) for p in kg.get_prerequisites(cid))
        info = all_concepts.get(cid) or {}
        related.extend(str(r) for r in (info.get("related_concepts") or []))

    exclude = set(concept_ids)
    prereqs_dedup = list(dict.fromkeys(p for p in prereqs if p and p not in exclude))
    related_dedup = list(dict.fromkeys(r for r in related if r and r not in exclude))
    return prereqs_dedup, related_dedup


def _render_deep_study_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 🧠 Промпт для глубокого изучения")
    topic = str(st.session_state.get("living_konspekt_title") or "Рабочий конспект")
    sections = [row_to_section(row) for row in rows]
    prerequisites, related_concepts = _collect_concept_context(rows)
    prompt_text = build_deep_study_prompt(
        topic=topic,
        sections=sections,
        prerequisites=prerequisites,
        related_concepts=related_concepts,
    )
    st.code(prompt_text, language="markdown")
    prompt_cols = st.columns(len(_EXTERNAL_LLM_TARGETS))
    for col, (label, url) in zip(prompt_cols, _EXTERNAL_LLM_TARGETS):
        with col:
            st.link_button(label, url, width="stretch")


def render_living_konspekt_view() -> None:
    ensure_workbench_hydrated()
    render_panel_header(
        "📚 Живой конспект",
        "Собирайте разделы лекций из графа/карточек, проверяйте актуальность и готовьте промпт "
        "для глубокого изучения — всё локально, облако только по вашей ссылке.",
    )

    rows = get_workbench_rows()
    st.caption(
        f"В корзине: {len(rows)} раздел(ов) · автосохраняется локально и переживает перезапуск; "
        "именованные сессии в сайдбаре — для снимков-вариантов."
    )

    if not rows:
        st.info(
            "Корзина пуста. Добавляйте разделы из панели «⚡ Действия с концептом» на Knowledge Graph "
            "или кнопкой «➕ В рабочий конспект» под карточкой Flashcards."
        )
        return

    _render_collected_sections(rows)
    _render_memory_panel(rows)
    st.divider()
    _render_build_panel(rows)
    st.divider()
    _render_term_cards_panel(rows)
    st.divider()
    _render_web_queries_panel(rows)
    st.divider()
    _render_deep_study_panel(rows)
