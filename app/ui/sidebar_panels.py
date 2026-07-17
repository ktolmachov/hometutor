"""Sidebar sub-panels extracted from :mod:`app.ui.sidebar` (size-budget split).

Each panel is a self-contained Streamlit block; moved out so the sidebar
orchestrator stays under the architecture file-size budget.
"""

from __future__ import annotations

import json

import streamlit as st

from app import user_state

_RESTORE_PREVIEW_KEYS: dict[str, tuple[str, ...]] = {
    "profiles": ("learner_profile_snapshots", "learner_profile_migration_log"),
    "decks": ("flashcard_decks",),
    "cards": ("flashcards",),
    "reviews": ("spaced_repetition",),
}


def _restore_preview_entity_rows(preview: dict) -> dict[str, int]:
    counts = preview.get("table_row_counts") if isinstance(preview, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    out: dict[str, int] = {}
    for label, keys in _RESTORE_PREVIEW_KEYS.items():
        out[label] = sum(int(counts.get(table) or 0) for table in keys)
    return out


def _restore_result_summary(result: dict) -> str:
    rows = int((result or {}).get("rows_inserted") or 0)
    ver = int((result or {}).get("sync_version") or 0)
    return f"Снимок применён: импортировано {rows} строк (sync_version={ver})."


def _render_sidebar_backup_restore_panel() -> None:
    """US-10.1 / US-10.2: единый блок backup + restore (ключи виджетов стабильны для session_state)."""
    from app.sync_service import (
        bundle_json_bytes,
        import_bundle_from_dict,
        qr_payload_for_bundle,
        qr_png_bytes,
    )

    if str(st.query_params.get("e2e_restore_preview") or "").lower() in {"1", "true", "yes"}:
        raw_restore = {
            "sync_version": user_state.SYNC_BUNDLE_VERSION,
            "exported_at": "2026-04-16T12:00:00Z",
            "tables": {},
        }
        st.session_state["restore_bundle_raw"] = raw_restore
        st.session_state["restore_bundle_preview"] = user_state.preview_full_sync_bundle(raw_restore)

    st.markdown("**Синхронизация и backup (US-10.1)**")
    st.download_button(
        "Скачать полный backup (rag_sync.json)",
        data=bundle_json_bytes(),
        file_name="rag_sync.json",
        mime="application/json",
        key="sidebar_sync_dl",
        help="Снимок user_state + quiz stats; восстановление через мастер ниже или import_full_sync_bundle.",
    )
    try:
        payload, fits = qr_payload_for_bundle()
        st.caption("QR: полный импорт со скана" if fits else "QR: только отпечаток — переносите JSON-файл")
        st.image(qr_png_bytes(payload))
    except Exception as e:  # noqa: BLE001 - robust QR backup display, continue UI render on failure
        st.warning(f"QR недоступен: {e}")

    st.markdown("**Восстановление из backup (US-10.2)**")
    st.caption(
        f"Ожидается `sync_version` = **{user_state.SYNC_BUNDLE_VERSION}**. "
        "Сначала предпросмотр, затем подтверждение — полная перезапись локального прогресса."
    )
    up = st.file_uploader("Файл backup (JSON)", type=["json"], key="sidebar_sync_upload")
    c_prev, c_clr = st.columns(2)
    with c_prev:
        preview_clicked = st.button("Предпросмотр", key="sidebar_restore_preview", width='stretch')
    with c_clr:
        if st.button("Сбросить предпросмотр", key="sidebar_restore_clear", width='stretch'):
            st.session_state.pop("restore_bundle_raw", None)
            st.session_state.pop("restore_bundle_preview", None)
            st.rerun()
    if preview_clicked:
        if up is None:
            st.warning("Выберите JSON-файл.")
        else:
            try:
                raw_restore = json.loads(up.getvalue().decode("utf-8"))
                preview = user_state.preview_full_sync_bundle(raw_restore)
                st.session_state["restore_bundle_raw"] = raw_restore
                st.session_state["restore_bundle_preview"] = preview
            except json.JSONDecodeError:
                st.error("Файл не является корректным JSON.")
            except ValueError as ex:
                st.error(str(ex))
    prev = st.session_state.get("restore_bundle_preview")
    if isinstance(prev, dict):
        st.success("Предпросмотр готов — проверьте счётчики и подтвердите импорт.")
        exp_at = prev.get("exported_at")
        if exp_at:
            st.caption(f"Экспортировано: {str(exp_at)[:19].replace('T', ' ')} UTC")
        st.metric("Всего строк (таблицы)", int(prev.get("total_rows") or 0))
        st.caption("Строк по таблице (top-level ключи bundle.tables)")
        counts = prev.get("table_row_counts") or {}
        if isinstance(counts, dict):
            busy = [(k, v) for k, v in counts.items() if int(v or 0) > 0]
            busy.sort(key=lambda kv: -kv[1])
            for name, n in busy[:12]:
                st.caption(f"- `{name}`: **{n}**")
        entity_counts = _restore_preview_entity_rows(prev)
        st.caption(
            "Ключевые сущности: "
            f"profiles={entity_counts['profiles']}, "
            f"decks={entity_counts['decks']}, "
            f"cards={entity_counts['cards']}, "
            f"reviews={entity_counts['reviews']}"
        )
        st.markdown('<div data-testid="e2e-restore-confirm"></div>', unsafe_allow_html=True)
        confirm = st.checkbox(
            "Я понимаю, что импорт перезапишет локальный прогресс на этой машине",
            key="sidebar_restore_confirm",
        )
        if st.button("Импортировать снимок", key="sidebar_sync_apply", disabled=not confirm):
            raw_apply = st.session_state.get("restore_bundle_raw")
            if not isinstance(raw_apply, dict):
                st.error("Нет данных для импорта — снова нажмите «Предпросмотр».")
            else:
                result = import_bundle_from_dict(raw_apply)
                st.session_state.pop("restore_bundle_raw", None)
                st.session_state.pop("restore_bundle_preview", None)
                st.success(_restore_result_summary(result))
