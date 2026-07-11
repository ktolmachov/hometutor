from app import user_state
import app.ui.course_prepare_view as course_prepare_view
import app.ui.learning_plan_navigation as learning_plan_navigation
import app.ui.sidebar as sidebar
from app.section_index import IndexedSection
from app.ui.course_prepare_view import _prepare_course_artifact, _preview_cards_from_plan
from app.ui.learning_plan_navigation import enriched_learning_plan_markdown
from types import SimpleNamespace
from pathlib import Path


TABLE_PLAN = """
| # | Тема | Документ(ы) | Ключевые концепции | Практика | Проверка результата | Зависимости | Время (ч) |
|---|---|---|---|---|---|---|---|
| 1 | Векторы | intro.md | координаты, модуль | Нарисовать 3 вектора и подписать координаты | Объяснить модуль и направление | нет | 1.5 |
| 2 | Скалярное произведение | dot.md | угол, проекция | Решить 2 задачи на угол между векторами | Отличить проекцию от длины | Векторы | 2 |
""".strip()


def test_learning_plan_steps_from_markdown_parses_table_rows_as_steps() -> None:
    steps = user_state.learning_plan_steps_from_markdown(TABLE_PLAN)

    assert len(steps) == 2
    assert steps[0].startswith("Векторы")
    assert "Концепции: координаты, модуль" in steps[0]
    assert "Практика: Нарисовать 3 вектора" in steps[0]
    assert "Проверка: Объяснить модуль" in steps[0]
    assert "Документы: intro.md" in steps[0]
    assert "Время: 1.5 ч" in steps[0]
    assert steps[1].startswith("Скалярное произведение")


def test_learning_plan_steps_from_markdown_keeps_legacy_numbered_fallback() -> None:
    plan_md = """
1. Первый шаг
   Деталь первого шага
2. Второй шаг
""".strip()

    steps = user_state.learning_plan_steps_from_markdown(plan_md)

    assert steps == ["1. Первый шаг\n   Деталь первого шага", "2. Второй шаг"]


def test_learning_plan_steps_from_markdown_does_not_leak_table_pipes() -> None:
    steps = user_state.learning_plan_steps_from_markdown(TABLE_PLAN)

    assert steps
    assert all("|" not in step for step in steps)


def test_preview_cards_from_plan_uses_structured_table_steps() -> None:
    cards = _preview_cards_from_plan({"plan": TABLE_PLAN})

    assert len(cards) == 2
    assert cards[0].startswith("Векторы")
    assert all("|" not in card for card in cards)


def test_learning_plan_table_hours_summary_sums_numeric_hours() -> None:
    summary = user_state.learning_plan_table_hours_summary_from_markdown(TABLE_PLAN)

    assert summary == {
        "total_hours": 3.5,
        "steps_count": 2,
        "missing_or_invalid_hours": 0,
    }


def test_learning_plan_table_hours_summary_counts_invalid_hours() -> None:
    plan = """
| # | Тема | Время (ч) |
|---|---|---|
| 1 | Векторы | около часа |
| 2 | Производная | 2,5 |
""".strip()

    summary = user_state.learning_plan_table_hours_summary_from_markdown(plan)

    assert summary == {
        "total_hours": 2.5,
        "steps_count": 2,
        "missing_or_invalid_hours": 1,
    }


def test_prepare_course_artifact_rebuilds_and_saves_plan(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_fetch_json(method: str, path: str, *, timeout: int, json: dict) -> dict:
        assert method == "POST"
        assert timeout == 120
        calls.append((path, json))
        if path == "/synthesize":
            return {"summary": "new synthesis"}
        if path == "/learning-plan":
            return {"plan": TABLE_PLAN}
        raise AssertionError(path)

    def fake_save_course_artifact(documents: list[str], artifact: dict) -> dict:
        return {"saved": True, **artifact, "saved_documents": documents}

    monkeypatch.setattr(course_prepare_view, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(course_prepare_view, "save_course_artifact", fake_save_course_artifact)

    artifact, learning_plan = _prepare_course_artifact(
        documents=["course/a.md"],
        course_title="Course A",
        topic_name="Topic A",
        goal="Learn",
        level="intermediate",
        time_budget_hours=6,
        known_topics=["basics"],
        user_progress=True,
    )

    assert [path for path, _ in calls] == ["/synthesize", "/learning-plan"]
    assert learning_plan["selection_mode"] == "course_scope"
    assert learning_plan["selected_documents"] == ["course/a.md"]
    assert artifact["saved"] is True
    assert artifact["learning_plan"] == learning_plan
    assert artifact["flashcards_preview"][0].startswith("Векторы")


def test_enriched_learning_plan_markdown_adds_inline_material_links(monkeypatch) -> None:
    section = IndexedSection(
        heading_text="Координаты вектора",
        slug="coords",
        level=2,
        line_start=12,
        line_end=24,
        text="body",
        own_text="body",
        source_abs=Path("D:/data/intro.md"),
        konspekt_md_abs=Path("D:/data/vault/intro.md"),
    )

    monkeypatch.setattr(learning_plan_navigation, "build_section_index", lambda rel: [section])
    monkeypatch.setattr(learning_plan_navigation, "best_section_for", lambda sections, query: section)
    monkeypatch.setattr(learning_plan_navigation, "obsidian_uri", lambda path, heading_text=None: "obsidian://open")
    monkeypatch.setattr(learning_plan_navigation, "vscode_uri", lambda path, line=None: "vscode://file")
    monkeypatch.setattr(
        learning_plan_navigation,
        "video_citation_for_candidate",
        lambda candidate: SimpleNamespace(
            status="available",
            citation=SimpleNamespace(timestamp_label="1:23", url="https://youtu.be/x?t=83s"),
        ),
    )
    monkeypatch.setattr(
        user_state,
        "get_reading_status",
        lambda resource_type, resource_id: {"step_index": 1},
    )

    enriched = enriched_learning_plan_markdown(
        TABLE_PLAN,
        learning_plan={"plan": TABLE_PLAN},
        topic_id="topic-1",
    )

    assert "Статус" in enriched
    assert "Материалы" in enriched
    assert "✓" in enriched
    assert "▶" in enriched
    assert "[Obsidian](obsidian://open)" in enriched
    assert "[VS Code](vscode://file)" in enriched
    assert "[Видео 1:23](https://youtu.be/x?t=83s)" in enriched


def test_sidebar_load_active_course_plan_into_session(monkeypatch) -> None:
    session: dict = {}
    artifact = {"learning_plan": {"topic": "Course", "plan": TABLE_PLAN}}

    monkeypatch.setattr(sidebar.st, "session_state", session)
    monkeypatch.setattr(sidebar, "normalize_source_paths", lambda paths: list(paths))
    monkeypatch.setattr(sidebar, "load_course_artifact", lambda docs: artifact)

    loaded = sidebar._load_active_course_plan_into_session({"source_paths": ["course/a.md"]})

    assert loaded is True
    assert session["last_course_prepare"] == artifact
    assert session["last_learning_plan"] == artifact["learning_plan"]
    assert session[sidebar.PENDING_CURRENT_VIEW_KEY] == "Темы"
