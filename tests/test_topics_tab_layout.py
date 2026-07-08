from app.ui.topics_tab import _use_full_width_topic_workspace


def test_active_single_topic_course_uses_full_width_workspace():
    assert _use_full_width_topic_workspace(
        active_scope={"folder_rel": "ai-agents"},
        filtered_topics=[{"topic_id": "course_ai"}],
        quiz_active=False,
    )


def test_topic_catalog_keeps_map_when_navigation_is_useful():
    assert not _use_full_width_topic_workspace(
        active_scope=None,
        filtered_topics=[{"topic_id": "a"}],
        quiz_active=False,
    )
    assert not _use_full_width_topic_workspace(
        active_scope={"folder_rel": "ai-agents"},
        filtered_topics=[{"topic_id": "a"}, {"topic_id": "b"}],
        quiz_active=False,
    )
    assert not _use_full_width_topic_workspace(
        active_scope={"folder_rel": "ai-agents"},
        filtered_topics=[{"topic_id": "a"}],
        quiz_active=True,
    )
