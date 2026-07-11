from types import SimpleNamespace

from app.ui.tutor_chat_session import _is_flashcard_handoff_seed_message


def test_flashcard_handoff_seed_message_detected_by_debug_flag() -> None:
    msg = SimpleNamespace(
        metadata={
            "debug": {"flashcard_handoff_seed": True},
            "sources": [],
        }
    )

    assert _is_flashcard_handoff_seed_message(msg) is True


def test_flashcard_handoff_seed_message_detected_by_source_route() -> None:
    msg = SimpleNamespace(
        metadata={
            "sources": [{"route": "flashcard_seed"}],
        }
    )

    assert _is_flashcard_handoff_seed_message(msg) is True


def test_regular_tutor_message_is_not_flashcard_handoff_seed() -> None:
    msg = SimpleNamespace(metadata={"debug": {}, "sources": [{"route": "rag"}]})

    assert _is_flashcard_handoff_seed_message(msg) is False
