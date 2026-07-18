"""W9a Tutor Chat UI contracts (source-level + pure helpers)."""

from __future__ import annotations

from pathlib import Path

from app.ui.tutor_chat_controls import format_tutor_session_title


def test_format_tutor_session_title_prefers_topic_over_uuid() -> None:
    title = format_tutor_session_title(
        {
            "session_id": "abcdef12-3456",
            "topic": "Hybrid retrieval",
            "last_user_preview": "что такое RAG?",
            "last_updated": "2026-07-18T12:00:00",
        },
        session_id="abcdef12-3456",
    )
    assert "Hybrid retrieval" in title
    assert "abcdef12" not in title


def test_format_tutor_session_title_falls_back_to_preview() -> None:
    title = format_tutor_session_title(
        {"last_user_preview": "Объясни attention", "last_updated": "2026-07-18T09:00:00"},
        session_id="deadbeef",
    )
    assert "attention" in title.lower() or "Объясни" in title


def test_tutor_depth_labels_have_no_json_jargon() -> None:
    src = Path("app/ui/tutor_chat_controls.py").read_text(encoding="utf-8")
    assert "depth_level в JSON" not in src
    assert "Кратко" in src and "С объяснением" in src and "Глубоко" in src


def test_tutor_session_order_history_before_exports() -> None:
    src = Path("app/ui/tutor_chat_session.py").read_text(encoding="utf-8")
    hist = src.index("_render_tutor_history")
    exports = src.index("render_tutor_chat_exports")
    chat_in = src.index('st.chat_input("Спросите тьютора')
    assert hist < chat_in < exports
    assert "Экспорт и эксперт" in src


def test_tutor_intro_collapses_after_reply() -> None:
    src = Path("app/ui/tutor_chat_header.py").read_text(encoding="utf-8")
    assert "has_assistant_reply" in src
    assert "Как пользоваться чатом" in src
    assert "prefers-reduced-motion" in src


def test_tutor_footer_hides_tech_counters_outside_diagnostic() -> None:
    src = Path("app/ui/tutor_chat_footer.py").read_text(encoding="utf-8")
    assert 'get_ui_level() == "diagnostic"' in src
