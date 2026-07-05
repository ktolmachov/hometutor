"""Generate-and-preview view for Flashcards hub."""

from __future__ import annotations

from typing import Any, Callable

import json
import time

import requests
import streamlit as st

from app.config import get_settings

from app.ui.flashcards_read_cache import invalidate_flashcards_read_cache
from app.ui.flashcards_sections import (
    FC_MAIN_SECTION_REVIEW,
    FC_SOURCE_COURSE_LABEL,
    FC_SOURCE_DOCUMENT_LABEL,
    FC_SOURCE_UPLOAD_LABEL,
    apply_e2e_source_override,
    pending_section_key,
)
from app.ui.study_scope import get_active_scope

# Последовательный LLM-вызов на документ (~45–60 с); UI read-timeout должен пережить весь batch.
_FLASHCARD_GENERATE_TIMEOUT_DOC_SEC = 180
_FLASHCARD_GENERATE_TIMEOUT_PER_COURSE_DOC_SEC = 60
_FLASHCARD_GENERATE_TIMEOUT_COURSE_BUFFER_SEC = 120
_FLASHCARD_GENERATE_TIMEOUT_MAX_SEC = 3600
_FC_GENERATE_CACHE_HINT_KEY = "fc_generate_llm_cache_hint"
_FC_GENERATE_SUMMARY_KEY = "fc_generate_summary"


def _route_saved_living_konspekt_deck_to_review(deck_id: int) -> None:
    """After saving a Living Konspekt deck, make the next screen the review flow."""
    try:
        # Финальный шаг funnel «чтение → обучение»: колода из живого конспекта сохранена.
        from app.ui_events import track_event

        track_event("living_konspekt_term_deck_saved", {"deck_id": deck_id})
    except Exception:  # noqa: BLE001 - аналитика не должна ломать сохранение колоды
        pass
    st.session_state["flashcards_subview"] = "review_from_deck"
    st.session_state["flashcards_review_session_deck_id"] = deck_id
    st.session_state["flashcards_review_deck_sync_pending"] = deck_id
    st.session_state["flashcards_review_queue"] = []
    st.session_state["flashcards_review_index"] = 0
    st.session_state["flashcards_card_flipped"] = False
    st.session_state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    st.session_state["flashcards_review_session_status"] = "idle"
    st.session_state["flashcards_review_session_error"] = None
    st.session_state.pop("flashcards_review_session_scope_signature", None)
    st.session_state[pending_section_key()] = FC_MAIN_SECTION_REVIEW


def _format_duration_sec(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}:{secs:02d}"
    return f"{secs} с"


def _doc_done_caption(*, cards_count: int, latency_ms: float | int | None, cache_hit: bool) -> str:
    parts = [f"✓ {cards_count} карточек"]
    if isinstance(latency_ms, (int, float)) and latency_ms > 0:
        parts.append(f"за {float(latency_ms) / 1000:.0f} с")
    if cache_hit:
        parts.append("кэш LLM")
    return " · ".join(parts)


def _flashcard_generate_timeout_sec(*, scope: str, source_path_count: int = 1) -> int:
    if scope == "course":
        n = max(1, source_path_count)
        return min(
            _FLASHCARD_GENERATE_TIMEOUT_MAX_SEC,
            n * _FLASHCARD_GENERATE_TIMEOUT_PER_COURSE_DOC_SEC + _FLASHCARD_GENERATE_TIMEOUT_COURSE_BUFFER_SEC,
        )
    return _FLASHCARD_GENERATE_TIMEOUT_DOC_SEC


def _is_read_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    msg = str(exc).lower()
    return "read timed out" in msg or "timed out" in msg


def _course_card_tags(
    *,
    base_tags: str | None,
    course_id: str | None,
    folder_rel: str | None,
    source_path: str,
) -> str:
    from app.user_state_flashcards import parse_flashcard_tags

    tags = parse_flashcard_tags(base_tags)
    if course_id:
        tags.append(f"course:{course_id}")
    if folder_rel:
        tags.append(f"folder:{folder_rel}")
    tags.append(f"source:{source_path}")
    return ", ".join(dict.fromkeys(tags))


def _mark_flashcard_generate_timeout() -> None:
    st.session_state[_FC_GENERATE_CACHE_HINT_KEY] = True


def _clear_flashcard_generate_timeout_hint() -> None:
    st.session_state.pop(_FC_GENERATE_CACHE_HINT_KEY, None)


def _show_flashcard_generate_timeout_error(exc: Exception) -> None:
    _mark_flashcard_generate_timeout()
    st.error(f"Превышен таймаут ожидания: {exc}")
    st.warning(
        "Генерация на сервере могла продолжиться в фоне. "
        "Подождите 1–2 минуты и нажмите «Сгенерировать» снова — "
        "повтор обычно быстрее за счёт кэша LLM на сервере."
    )


def _show_flashcard_generate_error(exc: Exception) -> None:
    if _is_read_timeout_error(exc):
        _show_flashcard_generate_timeout_error(exc)
        return
    st.error(f"Ошибка генерации: {exc}")


def _generate_course_flashcards_with_progress(
    *,
    api_call: Callable[..., Any],
    source_paths: list[str],
    num_cards: int,
    course_id: str | None,
    folder_rel: str | None,
    course_title: str | None,
) -> dict[str, Any]:
    paths = [str(path).strip() for path in source_paths if str(path).strip()]
    cards: list[dict[str, str | None]] = []
    errors: list[str] = []
    total = len(paths)
    cache_hits = 0
    docs_ok = 0
    started = time.perf_counter()

    with st.status(f"Генерация по курсу: {total} документ(ов)…", expanded=True) as status:
        for index, path in enumerate(paths):
            status.update(label=f"Документ {index + 1} из {total}")
            st.caption(f"`{path}`")
            try:
                doc_result = api_call(
                    "POST",
                    "/flashcards/generate",
                    json={"scope": "document", "identifier": path, "num_cards": num_cards},
                    timeout=_FLASHCARD_GENERATE_TIMEOUT_DOC_SEC,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced below as per-document failure.
                if _is_read_timeout_error(exc):
                    raise
                errors.append(f"{path}: {exc}")
                continue
            if not doc_result.get("success"):
                errors.append(f"{path}: {doc_result.get('error') or 'generation failed'}")
                continue
            docs_ok += 1
            if doc_result.get("llm_cache_hit"):
                cache_hits += 1
            doc_cards_raw = doc_result.get("cards") or []
            st.caption(
                _doc_done_caption(
                    cards_count=len(doc_cards_raw),
                    latency_ms=doc_result.get("latency_ms"),
                    cache_hit=bool(doc_result.get("llm_cache_hit")),
                )
            )
            for card in doc_cards_raw:
                front = str(card.get("front") or "").strip()
                back = str(card.get("back") or "").strip()
                if not front or not back:
                    continue
                cards.append(
                    {
                        "front": front,
                        "back": back,
                        "tags": _course_card_tags(
                            base_tags=card.get("tags"),
                            course_id=course_id,
                            folder_rel=folder_rel,
                            source_path=path,
                        ),
                    }
                )
        if cards:
            status.update(label=f"Готово: {len(cards)} карточек", state="complete")
        else:
            status.update(label="Не удалось сгенерировать карточки", state="error")

    if not cards:
        return {
            "success": False,
            "cards": [],
            "deck_title": course_title or "Курс",
            "error": "; ".join(errors) if errors else "No valid cards generated",
        }
    duration_sec = time.perf_counter() - started
    return {
        "success": True,
        "cards": cards,
        "deck_title": course_title or "Курс",
        "error": None,
        "generation_errors": errors,
        "generation_stats": {
            "docs_total": total,
            "docs_ok": docs_ok,
            "docs_failed": len(errors),
            "cards_total": len(cards),
            "cache_hits": cache_hits,
            "latency_ms": round(duration_sec * 1000, 2),
        },
        "duration_sec": duration_sec,
    }


def render_generate(*, api_call: Callable[..., Any]) -> None:
    apply_e2e_source_override()

    st.markdown("### ✨ Сгенерировать карточки")
    st.markdown('<div data-testid="e2e-fc-jump-review-from-generate"></div>', unsafe_allow_html=True)
    if st.button("🔁 К повторению", key="fc_jump_review_from_generate", width='stretch'):
        st.session_state[pending_section_key()] = FC_MAIN_SECTION_REVIEW
        st.rerun()

    st.markdown('<div data-testid="e2e-fc-source-mode"></div>', unsafe_allow_html=True)
    active_scope = get_active_scope()
    source_modes = [FC_SOURCE_DOCUMENT_LABEL, FC_SOURCE_UPLOAD_LABEL]
    if active_scope:
        source_modes.insert(1, FC_SOURCE_COURSE_LABEL)
    elif st.session_state.get("fc_source_mode") == FC_SOURCE_COURSE_LABEL:
        st.session_state["fc_source_mode"] = FC_SOURCE_DOCUMENT_LABEL
    source_mode = st.radio(
        "Источник",
        source_modes,
        horizontal=True,
        key="fc_source_mode",
    )

    identifier: str | None = None
    upload_content: str | None = None
    source_paths: list[str] = []
    course_id: str | None = None
    course_title: str | None = None
    folder_rel: str | None = None
    scope = "document"

    if source_mode == FC_SOURCE_DOCUMENT_LABEL:
        catalog = st.session_state.get("topics_catalog") or {}
        topics = catalog.get("topics") or []
        if active_scope:
            from app.ui.topics_tab_filters import filter_topics_by_active_scope
            topics = filter_topics_by_active_scope(topics, active_scope)
        doc_options: dict[str, str] = {}
        for topic in topics:
            for doc in topic.get("documents") or []:
                label = f"{topic['topic_name']} / {doc.get('file_name') or doc.get('relative_path', '')}"
                doc_options[label] = doc.get("relative_path", "")
        if not doc_options:
            st.info("База знаний пуста. Сначала проиндексируй документы.")
            return
        chosen = st.selectbox("Выбери документ", list(doc_options.keys()), key="fc_doc_select")
        identifier = doc_options[chosen]
    elif source_mode == FC_SOURCE_COURSE_LABEL:
        scope = "course"
        scope_data = active_scope or {}
        source_paths = [str(path).strip() for path in scope_data.get("source_paths") or [] if str(path).strip()]
        course_id = str(scope_data.get("id") or "").strip() or None
        course_title = str(scope_data.get("title") or scope_data.get("folder_rel") or "Активный курс")
        folder_rel = str(scope_data.get("folder_rel") or "").strip() or None
        identifier = json.dumps(
            {"course_id": course_id, "folder_rel": folder_rel},
            ensure_ascii=False,
            sort_keys=True,
        )
        if not source_paths:
            st.info("В активном курсе нет списка документов. Активируйте курс из вкладки «Темы».")
            return
        st.caption(f"Курс: **{course_title}** · документов: **{len(source_paths)}**")
        warn_docs = get_settings().flashcard_course_warn_documents
        if len(source_paths) > warn_docs:
            st.warning(
                f"Курс большой ({len(source_paths)} док.). Генерация займёт ~"
                f"{max(1, len(source_paths) * 40 // 60)} мин. "
                f"Можно снизить «карточек на документ» или генерировать по одному файлу."
            )
        with st.expander("Документы курса", expanded=False):
            for path in source_paths[:30]:
                st.markdown(f"- `{path}`")
            if len(source_paths) > 30:
                st.caption(f"И ещё {len(source_paths) - 30} документ(ов).")
    else:
        scope = "upload"
        uploaded = st.file_uploader(
            "Загрузи файл (PDF, TXT, MD, DOCX)",
            type=["pdf", "txt", "md", "docx"],
            key="fc_file_upload",
        )
        if uploaded:
            try:
                if uploaded.name.endswith(".pdf"):
                    import pypdf

                    reader = pypdf.PdfReader(uploaded)
                    upload_content = "\n".join(p.extract_text() or "" for p in reader.pages)
                else:
                    upload_content = uploaded.read().decode("utf-8", errors="replace")
                identifier = uploaded.name
                st.caption(f"Извлечено {len(upload_content):,} символов")
            except Exception as e:  # noqa: BLE001 - UI displays parse error.
                st.error(f"Не удалось прочитать файл: {e}")
                return
        else:
            st.info("Загрузи файл для генерации карточек.")
            return

    num_cards_label = "Карточек на документ" if scope == "course" else "Количество карточек"
    num_cards = st.slider(num_cards_label, 5, 20, 12 if scope != "course" else 5, key="fc_num_cards")

    if st.session_state.get(_FC_GENERATE_CACHE_HINT_KEY):
        st.info(
            "Повторная генерация может пройти быстрее — ответы LLM уже могут быть в кэше сервера."
        )

    summary = st.session_state.pop(_FC_GENERATE_SUMMARY_KEY, None)
    if summary:
        cache_note = ""
        cache_hits = int(summary.get("cache_hits") or 0)
        if cache_hits:
            cache_note = f" · кэш LLM: {cache_hits} док."
        st.success(
            f"Сгенерировано **{summary.get('cards_total', 0)}** карточек "
            f"за **{_format_duration_sec(float(summary.get('duration_sec') or 0))}**{cache_note}"
        )

    st.markdown('<div data-testid="e2e-fc-generate"></div>', unsafe_allow_html=True)
    if st.button("⚡ Сгенерировать карточки", type="primary", width='stretch', key="fc_generate_btn"):
        batch_started = time.perf_counter()
        try:
            if scope == "course":
                result = _generate_course_flashcards_with_progress(
                    api_call=api_call,
                    source_paths=source_paths,
                    num_cards=num_cards,
                    course_id=course_id,
                    folder_rel=folder_rel,
                    course_title=course_title,
                )
            else:
                with st.spinner("Генерирую карточки… (~30–60 сек)"):
                    payload: dict = {"scope": scope, "num_cards": num_cards}
                    if scope == "document":
                        payload["identifier"] = identifier
                    else:
                        payload["identifier"] = identifier
                        payload["content"] = (upload_content or "")[:14000]
                    result = api_call(
                        "POST",
                        "/flashcards/generate",
                        json=payload,
                        timeout=_FLASHCARD_GENERATE_TIMEOUT_DOC_SEC,
                    )
        except Exception as e:  # noqa: BLE001 - UI displays API failure.
            _show_flashcard_generate_error(e)
            return

        if not result.get("success"):
            st.error(result.get("error") or "Не удалось сгенерировать карточки")
            return

        _clear_flashcard_generate_timeout_hint()
        gen_errors = result.get("generation_errors") or []
        if gen_errors:
            st.warning(
                "Часть документов не удалось обработать: "
                + "; ".join(gen_errors[:3])
                + ("…" if len(gen_errors) > 3 else "")
            )

        stats = result.get("generation_stats") or {}
        duration_sec = float(result.get("duration_sec") or (time.perf_counter() - batch_started))
        st.session_state[_FC_GENERATE_SUMMARY_KEY] = {
            "cards_total": len(result.get("cards") or []),
            "duration_sec": duration_sec,
            "cache_hits": stats.get("cache_hits") or (1 if result.get("llm_cache_hit") else 0),
        }

        st.session_state["fc_preview_cards"] = result.get("cards") or []
        st.session_state["fc_preview_title"] = result.get("deck_title") or (identifier or "Новая колода")
        st.session_state["fc_preview_source_type"] = scope
        st.session_state["fc_preview_source_identifier"] = result.get("source_identifier") or identifier
        st.rerun()

    preview = st.session_state.get("fc_preview_cards")
    if preview:
        st.divider()
        st.markdown(f"#### Предпросмотр — {len(preview)} карточек")
        st.caption("Отредактируй или удали карточки перед сохранением.")

        edited: list[dict] = []
        to_delete: set[int] = set()
        for i, card in enumerate(preview):
            with st.container(border=True):
                cc1, cc2, cc3 = st.columns([5, 5, 1])
                with cc1:
                    f = st.text_area("Front", value=card["front"], key=f"prev_f_{i}", height=80)
                with cc2:
                    b = st.text_area("Back", value=card["back"], key=f"prev_b_{i}", height=80)
                with cc3:
                    st.write("")
                    if st.button("🗑", key=f"prev_del_{i}", help="Убрать эту карточку"):
                        to_delete.add(i)
                t = st.text_input("Теги", value=card.get("tags") or "", key=f"prev_t_{i}")
                if i not in to_delete:
                    edited.append({"front": f, "back": b, "tags": t or None})

        if to_delete:
            st.session_state["fc_preview_cards"] = [c for i, c in enumerate(preview) if i not in to_delete]
            st.rerun()

        st.divider()
        deck_name = st.text_input(
            "Название колоды",
            value=st.session_state.get("fc_preview_title", "Новая колода"),
            key="fc_deck_name",
        )
        st.markdown('<div data-testid="e2e-fc-save-deck"></div>', unsafe_allow_html=True)
        if st.button("💾 Сохранить колоду", type="primary", width='stretch', key="fc_save_btn"):
            valid_cards = [
                c
                for c in edited
                if str(c.get("front") or "").strip() and str(c.get("back") or "").strip()
            ]
            if not valid_cards:
                st.warning("Нет карточек для сохранения.")
            elif len(valid_cards) < 5:
                st.warning(
                    f"Нужно минимум 5 карточек с непустыми полями «Вопрос» и «Ответ». Сейчас: {len(valid_cards)}."
                )
            else:
                try:
                    source_type = st.session_state.get("fc_preview_source_type") or scope
                    source_identifier = st.session_state.get("fc_preview_source_identifier") or identifier
                    r = api_call(
                        "POST",
                        "/flashcards/decks",
                        json={
                            "name": deck_name,
                            "source_type": source_type,
                            "source_identifier": source_identifier,
                            "cards": valid_cards,
                        },
                    )
                    st.success(f"✅ Сохранено {r['card_count']} карточек в колоду «{deck_name}»")
                    invalidate_flashcards_read_cache()
                    st.session_state.pop("fc_preview_cards", None)
                    st.session_state.pop("fc_preview_title", None)
                    st.session_state.pop("fc_preview_source_type", None)
                    st.session_state.pop("fc_preview_source_identifier", None)
                    deck_id = int(r.get("deck_id") or 0)
                    if source_type == "living_konspekt_terms" and deck_id:
                        _route_saved_living_konspekt_deck_to_review(deck_id)
                    else:
                        st.session_state["flashcards_subview"] = "decks"
                        st.session_state[pending_section_key()] = "decks"
                    st.rerun()
                except Exception as e:  # noqa: BLE001 - UI displays API failure.
                    st.error(f"Ошибка сохранения: {e}")
