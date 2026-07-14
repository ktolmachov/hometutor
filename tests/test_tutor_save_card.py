"""B1 (knowledge_fate_memory_loop): «→ в карточку» из ответа тьютора.

Covers the DoD: a card built from a tutor answer carries ``concept:`` and ``source:``
tags (provenance) and is therefore visible in the normal review deck. The pure
field-builder + source resolver are unit-tested; the Streamlit button is thin glue.
"""

from app.ui.tutor_chat_response_render import _build_tutor_card_fields, _resolve_answer_source_tag


def test_resolve_answer_source_tag_picks_first_real_path() -> None:
    assert _resolve_answer_source_tag([{"relative_path": "demo/lecture.md"}]) == "source:demo/lecture.md"
    # sentinel "ui" is skipped, falls through to the real file name
    assert _resolve_answer_source_tag([{"source": "ui"}, {"file_name": "a.txt"}]) == "source:a.txt"
    assert _resolve_answer_source_tag([{"source": "flashcard_front_back"}]) == ""
    assert _resolve_answer_source_tag(None) == ""


def test_build_tutor_card_fields_carries_concept_and_source_tags() -> None:
    payload = {"teaching_summary": "Кратко: токены — это кусочки текста."}
    meta = {"learner_trace": {"concept": "токенизация"}}
    sources = [{"relative_path": "demo/nlp.md"}]
    session_state = {"last_answer": {"question": "Что такое токен?"}}

    fields = _build_tutor_card_fields(payload, meta, sources, session_state)
    assert fields is not None
    front, back, tags = fields
    assert front == "Что такое токен?"
    assert back == "Кратко: токены — это кусочки текста."
    assert tags is not None
    assert "concept:токенизация" in tags
    assert "source:demo/nlp.md" in tags


def test_build_tutor_card_fields_falls_back_to_topic_for_front_and_concept() -> None:
    fields = _build_tutor_card_fields(
        {"teaching_summary": "Summary."},
        {},
        None,
        {"current_topic": "NLP"},
    )
    assert fields is not None
    assert fields[0] == "NLP"  # front from topic
    assert "concept:NLP" in fields[2]  # concept falls back to topic too


def test_build_tutor_card_fields_none_without_summary_or_front() -> None:
    # no teaching_summary → nothing to save
    assert (
        _build_tutor_card_fields({}, {"learner_trace": {"concept": "x"}}, None, {"last_answer": {"question": "q"}})
        is None
    )
    # summary present but no question/topic → no front → not saveable
    assert _build_tutor_card_fields({"teaching_summary": "s"}, {}, None, {}) is None
