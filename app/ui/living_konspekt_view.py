"""«Живой конспект» — study-поверхность над Section Anchor Index.

Корзина (:data:`WORKBENCH_SECTIONS_KEY`) живёт в ``st.session_state`` как
реактивное зеркало. Persisted/runtime-контракт и автосохранение принадлежат
``app.workbench_service``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, MutableMapping

import streamlit as st

from app.media_sidecar import UrlVideoSource, load_media_sidecar_for_konspekt
from app.media_urls import normalize_video_url
from app import workbench_service
from app.section_index import IndexedSection, parse_sections, row_to_section
from app.ui.living_konspekt_add_panel import render_add_sections_panel

# Медиа-кластер вынесен в living_konspekt_media (size-budget); реэкспорт имён
# сохраняет существующие импорты тестов/соседних модулей из этого файла.
from app.ui.living_konspekt_media import (  # noqa: F401 - реэкспорт
    _expected_asr_params,
    _format_timestamp,
    _media_section_for_row,
    _render_all_lesson_videos_panel,
    _render_media_panel,
    _row_section_id,
    _sidecar_stale_reasons,
    _unique_document_rows,
)
from app.ui.living_konspekt_next_steps import (
    _collect_concept_context,
    render_deep_study_panel,
    render_web_queries_panel,
)
from app.ui.living_konspekt_reader import render_reader
from app.ui.helpers import format_request_error
from app.ui.widgets import render_panel_header

WORKBENCH_SECTIONS_KEY = workbench_service.WORKBENCH_SECTIONS_KEY
_WORKBENCH_KV_KEY = workbench_service.WORKBENCH_KV_KEY
_WORKBENCH_HYDRATED_KEY = "_workbench_hydrated"

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)


# ── Корзина: тонкий Streamlit-адаптер поверх app.workbench_service ───────
def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    return state if state is not None else st.session_state


def _ensure_auth_context() -> None:
    from app.ui.auth_gate import ensure_streamlit_auth_context

    ensure_streamlit_auth_context()


def ensure_workbench_hydrated(state: MutableMapping[str, Any] | None = None) -> None:
    """Один раз за сессию поднять runtime rows из ``app_kv`` через сервис."""
    target = _state(state)
    if target.get(_WORKBENCH_HYDRATED_KEY):
        return
    target[_WORKBENCH_HYDRATED_KEY] = True
    if WORKBENCH_SECTIONS_KEY in target:
        target[WORKBENCH_SECTIONS_KEY] = workbench_service.normalize_runtime_rows(
            list(target.get(WORKBENCH_SECTIONS_KEY) or [])
        )
        return
    if state is not None:
        target[WORKBENCH_SECTIONS_KEY] = []
        return
    try:
        _ensure_auth_context()
        target[WORKBENCH_SECTIONS_KEY] = workbench_service.load_rows()
    except Exception:  # noqa: BLE001 - недоступный профиль → пустая корзина, не падение
        return


def set_workbench_rows(
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Заменить корзину целиком (restore research-сессии) + авто-персист через сервис."""
    target = _state(state)
    runtime_rows = workbench_service.normalize_runtime_rows([row for row in rows if isinstance(row, dict)])
    target[WORKBENCH_SECTIONS_KEY] = runtime_rows
    target[_WORKBENCH_HYDRATED_KEY] = True
    if state is None:
        try:
            _ensure_auth_context()
            workbench_service.save_rows(runtime_rows)
        except Exception:  # noqa: BLE001 - restore не должен падать из-за авто-персиста
            pass


def get_workbench_rows(state: MutableMapping[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = _state(state).get(WORKBENCH_SECTIONS_KEY)
    return rows if isinstance(rows, list) else []


# TODO(W4-cleanup): внутренние UI-модули фичи ещё импортируют эти адаптеры из view;
# внешний доменный контракт уже живёт в app.workbench_service.
def add_section_to_workbench(
    section: IndexedSection,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Добавить раздел в session_state-зеркало; доменная операция живёт в сервисе."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    before = {str(row.get("row_key") or "") for row in rows}
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    new_rows = workbench_service.add_section(rows, section, storage=storage)
    target[WORKBENCH_SECTIONS_KEY] = new_rows
    added = any(str(row.get("row_key") or "") not in before for row in new_rows)
    if state is None:
        try:
            # Funnel «чтение → обучение»: раздел добавлен (из графа/карточки/сбора по концепту).
            from app.ui_events import track_event

            track_event("living_konspekt_section_added")
        except Exception:  # noqa: BLE001 - аналитика не должна ломать корзину
            pass
    return added


def move_section_in_workbench(
    row_key: str,
    delta: int,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Сдвинуть раздел по ``row_key``; доменная операция живёт в сервисе."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    new_rows = workbench_service.move_section(rows, row_key, delta, storage=storage)
    changed = [row.get("row_key") for row in new_rows] != [row.get("row_key") for row in rows]
    target[WORKBENCH_SECTIONS_KEY] = new_rows
    return changed


def remove_section_from_workbench(
    row_key: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.remove_section(rows, row_key, storage=storage)


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
        f"- {_row_konspekt_label(row)}:{row.get('line_start')}-{row.get('line_end')}"
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


def media_caption_line(
    t_start: float | int | None,
    t_end: float | int | None,
    video_title: str | None,
    youtube_url_with_t: str | None = None,
) -> str | None:
    """Markdown-строка «🎬 видео с таймкодом» для сохранённого артефакта (чистая, тестируемая).

    Без таймкода — ``None``: строка медиа в файле полезна только адресной.
    """
    if t_start is None:
        return None
    window = _format_timestamp(t_start) + (f"–{_format_timestamp(t_end)}" if t_end is not None else "")
    title = (video_title or "видео").strip() or "видео"
    if youtube_url_with_t:
        return f"*🎬 [{title} · {window}]({youtube_url_with_t})*"
    return f"*🎬 {title} · {window}*"


def _media_line_for_row(
    row: dict[str, Any],
    sidecar_cache: dict[str, Any],
    stale_cache: dict[str, list[str]] | None = None,
) -> str | None:
    """Таймкод раздела для артефакта: сохранённый конспект не должен терять видео-привязку.

    Критерий доверия тот же, что в UI-панели (:mod:`living_konspekt_media`): stale-sidecar
    или low-confidence раздел → ``None``, иначе файл получил бы таймкод, который само
    приложение считает недостоверным.

    ``stale_cache`` обязателен по смыслу: staleness хэширует konspekt И локальный
    видеофайл (гигабайты) — считается один раз на документ, а не на каждый раздел.
    """
    md_abs = str(row.get("konspekt_md_abs") or "")
    if not md_abs:
        return None
    if md_abs not in sidecar_cache:
        try:
            sidecar_cache[md_abs] = load_media_sidecar_for_konspekt(Path(md_abs))
        except Exception:  # noqa: BLE001 - медиа опционально, склейка не должна падать
            sidecar_cache[md_abs] = None
    sidecar = sidecar_cache[md_abs]
    if sidecar is None:
        return None
    media_section = _media_section_for_row(sidecar, row)
    if media_section is None or media_section.t_start is None or media_section.low_confidence:
        return None
    stale = stale_cache if stale_cache is not None else {}
    if md_abs not in stale:
        stale[md_abs] = _sidecar_stale_reasons(sidecar, md_abs)
    if stale[md_abs]:
        return None
    # Таймкод легитимен только для первичного видео (по нему выровнен media_sha256);
    # вторичные media.videos[] — смежные материалы, их не таймкодируем (см. _videos_block).
    video = sidecar.video
    youtube_url: str | None = None
    title: str | None = getattr(video, "title", None)
    if isinstance(video, UrlVideoSource):
        try:
            normalized = normalize_video_url(video.url)
            if normalized.is_youtube:
                youtube_url = normalized.with_timestamp(media_section.t_start)
        except ValueError:
            youtube_url = None
    return media_caption_line(media_section.t_start, media_section.t_end, title, youtube_url)


def _videos_block(sidecar_cache: dict[str, Any]) -> str:
    """«🎬 Видео материалов» для артефакта: ВСЕ источники из ``media.videos[]``.

    Первичное видео даёт таймкоды разделов, но вторичные (доклады, разборы) иначе
    терялись бы при сохранении. URL — кликабельным, локальный файл — именем.
    """
    lines: list[str] = []
    seen: set[str] = set()
    for sidecar in sidecar_cache.values():
        if sidecar is None:
            continue
        for video in sidecar.videos:
            if isinstance(video, UrlVideoSource):
                key = video.canonical_url or video.url
                label = (video.title or "").strip() or key
                entry = f"- [{label}]({key})"
            else:
                key = str(getattr(video, "path", ""))
                label = (getattr(video, "title", None) or Path(key).name or "видео").strip()
                entry = f"- {label} (`{Path(key).name}`)"
            if key and key not in seen:
                seen.add(key)
                lines.append(entry)
    return "## 🎬 Видео материалов\n\n" + "\n".join(lines) if lines else ""


def _stitch_verbatim(rows: list[dict[str, Any]]) -> str:
    """Детерминированная склейка: главная мысль лекции + заголовки-источники + якоря + текст.

    Под источником — видео-таймкод раздела из media-sidecar (артефакт остаётся
    мультимодальным). В конец — «Проверь себя» и «## Источники» (``файл:строки``).
    """
    header_parts = [
        f"> **Главная мысль исходной лекции ({doc_name}):** {idea}"
        for doc_name, idea in _lecture_main_ideas(rows)
    ]

    sidecar_cache: dict[str, Any] = {}
    stale_cache: dict[str, list[str]] = {}
    parts: list[str] = []
    for row in rows:
        heading = str(row.get("heading_text") or "Без названия")
        source_name = _row_konspekt_label(row)
        location = f"{source_name}:{row.get('line_start')}"
        media_line = _media_line_for_row(row, sidecar_cache, stale_cache)
        source_block = f"*Источник: {location}*" + (f"\n\n{media_line}" if media_line else "")
        parts.append(f"## {heading}\n\n{source_block}\n\n{row.get('text') or ''}")

    blocks: list[str] = []
    if header_parts:
        blocks.append("\n>\n".join(header_parts))
    blocks.append("\n\n---\n\n".join(parts))
    videos = _videos_block(sidecar_cache)
    if videos:
        blocks.append(videos)
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


def _row_konspekt_label(row: dict[str, Any]) -> str:
    md_abs = str(row.get("konspekt_md_abs") or "")
    if md_abs:
        return Path(md_abs).name
    return str(row.get("konspekt_md_label") or row.get("source_label") or "непереносимый источник")


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


def _row_stale_status(row: dict[str, Any]) -> str | None:
    """Дрейф строки корзины относительно исходного конспекта (корзина хранит снимок).

    ``None`` — источник совпадает; иначе короткая причина для caption. Снимок при этом
    остаётся читаемым/собираемым — это предупреждение, не блокировка.
    """
    if str(row.get("portability_status") or "") == workbench_service.NON_PORTABLE:
        reason = str(row.get("resolve_error") or "источник вне data/").replace("_", " ")
        return f"непереносимый снимок: {reason}"
    md_abs = str(row.get("konspekt_md_abs") or "")
    if not md_abs:
        return None
    path = Path(md_abs)
    if not path.is_file():
        return "исходный файл не найден — используется сохранённый снимок"
    try:
        from app.section_index import _cached_parse_sections

        sections = _cached_parse_sections(path)
    except Exception:  # noqa: BLE001 - проверка дрейфа опциональна, корзина работает без неё
        return None
    for section in sections:
        if section.slug == row.get("slug") and section.line_start == row.get("line_start"):
            if section.text == str(row.get("text") or ""):
                return None
            return "раздел изменился в источнике — в корзине старый снимок"
    row_id = _row_section_id(row)
    if row_id is not None:
        try:
            from app.media_alignment import compute_section_id

            if any(compute_section_id(s) == row_id for s in sections):
                return "раздел переехал в источнике (строки сместились)"
        except Exception:  # noqa: BLE001 - compute_section_id опционален — дрейф не проверяем, корзина работает
            return None
    return "раздел не найден в источнике — возможно, конспект перегенерирован"


def _bulk_heading_normalized(heading: str) -> str:
    return _SLUG_RE.sub(" ", heading.strip().lower()).strip()


def _is_bulk_document_section(section) -> bool:
    if section.level != 2:
        return False
    if not section.text.strip():
        return False
    return _bulk_heading_normalized(section.heading_text) not in {"оглавление", "содержание", "toc"}


def _add_document_sections_to_workbench(
    md_abs: str,
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> tuple[int, int]:
    representative = next((row for row in rows if str(row.get("konspekt_md_abs") or "") == md_abs), None)
    if representative is None:
        return 0, 0

    md_path = Path(md_abs)
    source_abs = Path(str(representative.get("source_abs") or md_abs))
    added = duplicates = 0
    for parsed in parse_sections(md_path):
        if not _is_bulk_document_section(parsed):
            continue
        section = IndexedSection(
            heading_text=parsed.heading_text,
            slug=parsed.slug,
            level=parsed.level,
            line_start=parsed.line_start,
            line_end=parsed.line_end,
            text=parsed.text,
            own_text=parsed.own_text,
            source_abs=source_abs,
            konspekt_md_abs=md_path,
            concept=representative.get("concept"),
        )
        if add_section_to_workbench(section, state=state):
            added += 1
        else:
            duplicates += 1
    return added, duplicates


def _render_bulk_document_panel(rows: list[dict[str, Any]]) -> None:
    documents = _unique_document_rows(rows)
    if not documents:
        return

    st.markdown("### 📥 Быстро добавить разделы")
    options = [str(row.get("konspekt_md_abs") or "") for row in documents]
    labels = {path: Path(path).name for path in options}
    selected = st.selectbox(
        "Документ",
        options,
        format_func=lambda path: labels.get(path, path),
        key="living_konspekt_bulk_doc",
    )
    if st.button("➕ Добавить крупные разделы документа", key="living_konspekt_bulk_add", width="stretch"):
        try:
            added, duplicates = _add_document_sections_to_workbench(selected, rows)
        except OSError as exc:
            st.error(f"Не удалось прочитать документ: {format_request_error(exc)}")
            return
        st.toast(
            f"В корзину: +{added}" + (f" · уже было: {duplicates}" if duplicates else ""),
            icon="📚",
        )
        st.rerun()


def _render_collected_sections(rows: list[dict[str, Any]]) -> None:
    from app.obsidian_export import obsidian_uri, vscode_uri

    st.markdown("### Собранные разделы")
    duplicate_keys = _duplicate_heading_keys(rows)
    row_list = list(rows)
    for idx, row in enumerate(row_list):
        md_abs = str(row.get("konspekt_md_abs") or "")
        row_key = str(row.get("row_key") or f"legacy_{idx}")
        line_start = row.get("line_start")
        heading_text = str(row.get("heading_text") or "")
        with st.container(border=True):
            cols = st.columns([5, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{heading_text or '—'}**")
                st.caption(f"{_row_konspekt_label(row)} · строки {line_start}-{row.get('line_end')}")
                if (md_abs, heading_text) in duplicate_keys or _heading_ambiguous(md_abs, heading_text):
                    st.caption("⚠️ Заголовок повторяется в документе — VS Code точнее для повторяющихся заголовков.")
                stale_status = _row_stale_status(row)
                if stale_status:
                    st.caption(f"🕰 {stale_status}")
                st.write(str(row.get("text") or "")[:400])
                _render_media_panel(row)
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
                move_cols = st.columns(2)
                with move_cols[0]:
                    if st.button(
                        "↑",
                        key=f"wb_move_up_{row_key}",
                        disabled=idx == 0,
                        help="Поднять раздел выше",
                        width="stretch",
                    ):
                        move_section_in_workbench(row_key, -1)
                        st.rerun()
                with move_cols[1]:
                    if st.button(
                        "↓",
                        key=f"wb_move_down_{row_key}",
                        disabled=idx >= len(row_list) - 1,
                        help="Опустить раздел ниже",
                        width="stretch",
                    ):
                        move_section_in_workbench(row_key, 1)
                        st.rerun()
            with cols[3]:
                if st.button("🗑 Убрать", key=f"wb_remove_{row_key}", width="stretch"):
                    remove_section_from_workbench(row_key)
                    st.rerun()


def _render_build_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 📚 Собрать рабочий конспект")
    # Дефолт через setdefault ДО инстанцирования: value= вместе с key= для уже
    # существующего session_state-ключа — анти-паттерн (Streamlit его игнорирует и warn'ит).
    st.session_state.setdefault("living_konspekt_title", "Рабочий конспект")
    topic = st.text_input(
        "Название конспекта",
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
                except Exception:  # noqa: BLE001 - аналитика не должна ломать переход к повторению
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
        except Exception:  # noqa: BLE001 - аналитика не должна ломать создание карточек
            pass
        st.rerun()


def _clear_flashcards_preview_widget_state() -> None:
    """Drop stale preview editor widget values before opening Flashcards create."""
    stale_prefixes = ("prev_f_", "prev_b_", "prev_t_")
    for key in list(st.session_state.keys()):
        if key == "fc_deck_name" or (isinstance(key, str) and key.startswith(stale_prefixes)):
            st.session_state.pop(key, None)


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
    render_add_sections_panel(expanded=not rows)

    if not rows:
        st.info(
            "Корзина пуста. Найдите разделы прямо здесь, добавьте их из Knowledge Graph "
            "или кнопкой «➕ В рабочий конспект» под карточкой Flashcards."
        )
        return

    tab_sections, tab_reader, tab_memory, tab_export, tab_next = st.tabs(
        ["🧩 Разделы", "📖 Читать", "🧠 Память", "📚 Сохранить", "🌐 Дальше"]
    )
    with tab_sections:
        _render_all_lesson_videos_panel(rows)
        _render_bulk_document_panel(rows)
        _render_collected_sections(rows)
    with tab_reader:
        render_reader(rows, media_renderer=_render_media_panel)
    with tab_memory:
        _render_memory_panel(rows)
        _render_term_cards_panel(rows)
    with tab_export:
        _render_build_panel(rows)
    with tab_next:
        render_web_queries_panel(rows)
        st.divider()
        render_deep_study_panel(rows)
