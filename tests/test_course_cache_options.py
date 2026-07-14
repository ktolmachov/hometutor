from app.course_cache import build_mission_control_course_options
from app.course_folder_filter import is_user_course_folder_rel


def test_user_course_folder_filter_hides_technical_roots():
    assert is_user_course_folder_rel("ai-agents")
    assert is_user_course_folder_rel("courses/agents")
    assert not is_user_course_folder_rel("_test_workbench")
    assert not is_user_course_folder_rel("_test_view_smoke/test_click")
    assert not is_user_course_folder_rel("graph_generations/staging")
    assert not is_user_course_folder_rel("cache/course_artifacts")


def test_build_mission_control_course_options_skips_technical_folders(monkeypatch):
    monkeypatch.setattr("app.course_cache.list_course_candidates", lambda: [])
    index_stats = {
        "folder_rel_options": [
            "_test_workbench",
            "_test_artifact_manifest",
            "graph_generations/staging",
            "ai-agents",
        ],
        "files": [
            "_test_workbench/fixture.md",
            "_test_artifact_manifest/doc.md",
            "graph_generations/staging/kg.sqlite",
            "ai-agents/lesson-1.md",
            "ai-agents/lesson-2.md",
        ],
    }

    options = build_mission_control_course_options(index_stats)

    assert [item["folder_rel"] for item in options] == ["ai-agents"]
    assert options[0]["source_paths"] == ["ai-agents/lesson-1.md", "ai-agents/lesson-2.md"]


def test_build_mission_control_course_options_keeps_uploaded_course_pack(monkeypatch):
    monkeypatch.setattr("app.course_cache.list_course_candidates", lambda: [])
    index_stats = {
        "folder_rel_options": [
            "uploads/hometutor_101",
            "uploads\\hometutor_101\\konspekts",
            "uploads\\hometutor_101\\lectures",
        ],
        "files": [
            "uploads/hometutor_101/README.md",
            "uploads/hometutor_101/lectures/urok_1.md",
            "uploads/hometutor_101/konspekts/urok_1.konspekt.md",
            "uploads/other_note.md",
        ],
    }

    options = build_mission_control_course_options(index_stats)

    assert [item["folder_rel"] for item in options] == ["uploads/hometutor_101"]
    assert options[0]["source_paths"] == [
        "uploads/hometutor_101/README.md",
        "uploads/hometutor_101/lectures/urok_1.md",
        "uploads/hometutor_101/konspekts/urok_1.konspekt.md",
    ]
