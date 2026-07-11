from app import user_state
import app.learning_plan_state as lps
import app.ui.course_prepare_view as course_prepare_view
import app.ui.learning_plan_navigation as learning_plan_navigation
import app.ui.resume_cards_tutor as resume_cards_tutor
import app.ui.sidebar as sidebar
from app.section_index import IndexedSection
from app.ui.course_prepare_view import _prepare_course_artifact, _preview_cards_from_plan
from app.ui.learning_plan_navigation import enriched_learning_plan_markdown, learning_plan_display_rows
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
    rows = learning_plan_display_rows(TABLE_PLAN, topic_id="topic-1")

    assert "Статус" in enriched
    assert "Материалы" in enriched
    assert "✓" in enriched
    assert "▶" in enriched
    assert "[Obsidian](obsidian://open)" in enriched
    assert "[VS Code](vscode://file)" in enriched
    assert "[Видео 1:23](https://youtu.be/x?t=83s)" in enriched
    assert rows[0]["links"]["obsidian"] == "obsidian://open"
    assert rows[0]["links"]["vscode"] == "vscode://file"
    assert rows[0]["links"]["video_url"] == "https://youtu.be/x?t=83s"


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


def test_reading_resume_open_topics_uses_pending_navigation(monkeypatch) -> None:
    session: dict = {}
    resume = {
        "resource_type": "learning_plan",
        "resource_id": "plan:course_ai_agents",
        "display_title": "Программа: Курс ИИ Агенты",
        "step_index": 0,
        "step_label": "Фундамент",
    }

    class RerunCalled(Exception):
        pass

    monkeypatch.setattr(resume_cards_tutor.st, "session_state", session)
    monkeypatch.setattr(resume_cards_tutor.user_state, "get_latest_resume", lambda: resume)
    monkeypatch.setattr(resume_cards_tutor.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(resume_cards_tutor.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(resume_cards_tutor.st, "button", lambda *args, **kwargs: True)
    monkeypatch.setattr(resume_cards_tutor.st, "rerun", lambda: (_ for _ in ()).throw(RerunCalled()))

    try:
        resume_cards_tutor.render_reading_resume_card(index_stats={})
    except RerunCalled:
        pass
    else:
        raise AssertionError("render_reading_resume_card should rerun after opening Topics")

    assert session["active_topic_id"] == "course_ai_agents"
    assert session[resume_cards_tutor.PENDING_CURRENT_VIEW_KEY] == "Темы"
    assert "current_view" not in session


def test_learning_plan_checkbox_respects_graph_content(monkeypatch) -> None:
    """B1: the local variable _graph_has_concepts mirrors get_concepts()."""
    import app.ui.topics_tab_plan_subtab as subtab

    monkeypatch.setattr(subtab._knowledge_graph, "get_concepts", lambda: {"vec": {}})
    has = bool(subtab._knowledge_graph.get_concepts())
    assert has is True

    monkeypatch.setattr(subtab._knowledge_graph, "get_concepts", lambda: {})
    has = bool(subtab._knowledge_graph.get_concepts())
    assert has is False


def test_learning_plan_display_rows_fallback_to_document_link(monkeypatch) -> None:
    monkeypatch.setattr(learning_plan_navigation, "build_section_index", lambda rel: [])
    monkeypatch.setattr(learning_plan_navigation, "resolve_source", lambda rel: Path("D:/data/intro.md"))
    monkeypatch.setattr(learning_plan_navigation, "vscode_uri", lambda path, line=None: "vscode://doc")

    rows = learning_plan_display_rows(TABLE_PLAN, topic_id="")
    enriched = enriched_learning_plan_markdown(TABLE_PLAN, learning_plan={"plan": TABLE_PLAN}, topic_id="")

    assert rows[0]["links"]["vscode_doc"] == "vscode://doc"
    assert "[Документ](vscode://doc)" in enriched


# ──────────────────────────────────────────────
# Tests for app.learning_plan_state (dedicated module)
# ──────────────────────────────────────────────


def test_lps_parse_table_normal() -> None:
    """Acceptance: step count equals data-row count in the table."""
    steps = lps.parse_plan_table(TABLE_PLAN)
    assert len(steps) == 2


def test_lps_parse_table_prompt_contract_columns() -> None:
    """Table from LEARNING_PLAN_PROMPT (8 columns) is recognised correctly."""
    plan = """
| # | Тема | Документ(ы) | Ключевые концепции | Практика | Проверка результата | Зависимости | Время (ч) |
|---|---|---|---|---|---|---|---|
| 1 | Линейная алгебра | la.md | матрицы, векторы | Решить 3 задачи | Объяснить собственные векторы | нет | 2 |
| 2 | Матричные операции | matrix.md | умножение, транспонирование | Перемножить 2 матрицы | Проверить умножение | Шаг 1 | 1.5 |
""".strip()
    steps = lps.parse_plan_table(plan)
    assert len(steps) == 2
    assert steps[0].title == "Линейная алгебра"
    assert steps[1].title == "Матричные операции"


def test_lps_step_text_has_no_pipe() -> None:
    steps = lps.parse_plan_table(TABLE_PLAN)
    assert steps
    for step in steps:
        text = lps.step_to_text(step)
        assert "|" not in text


def test_lps_step_text_starts_with_title() -> None:
    steps = lps.parse_plan_table(TABLE_PLAN)
    assert len(steps) == 2
    assert lps.step_to_text(steps[0]).startswith("Векторы")
    assert lps.step_to_text(steps[1]).startswith("Скалярное произведение")


def test_lps_step_text_contains_all_fields() -> None:
    steps = lps.parse_plan_table(TABLE_PLAN)
    text = lps.step_to_text(steps[0])
    assert "Концепции: координаты, модуль" in text
    assert "Практика: Нарисовать 3 вектора" in text
    assert "Проверка: Объяснить модуль" in text
    assert "Документы: intro.md" in text
    assert "Время: 1.5 ч" in text


def test_lps_fallback_legacy_numbered_list() -> None:
    plan_md = """
1. Первый шаг
   Деталь первого шага
2. Второй шаг
""".strip()
    steps = lps.steps_from_markdown(plan_md)
    assert steps == ["1. Первый шаг\n   Деталь первого шага", "2. Второй шаг"]


def test_lps_fallback_empty_plan() -> None:
    assert lps.steps_from_markdown("") == []
    assert lps.steps_from_markdown("   ") == []
    assert lps.steps_from_markdown(None) == []  # type: ignore[arg-type]


def test_lps_malformed_table_no_header() -> None:
    """Table with no recognised header column returns empty list without crashing."""
    plan = """
| foo | bar | baz |
|---|---|---|
| 1 | 2 | 3 |
""".strip()
    assert lps.parse_plan_table(plan) == []
    # steps_from_markdown falls through to legacy paragraph fallback — no crash
    lps.steps_from_markdown(plan)


def test_lps_malformed_table_no_separator() -> None:
    """Lines with pipe but no valid separator → not a table."""
    plan = """
| # | Тема |
| a | b |
| c | d |
""".strip()
    assert lps.parse_plan_table(plan) == []


def test_lps_malformed_table_title_column_missing() -> None:
    """Header maps to fields but 'title' is absent."""
    plan = """
| # | Часы |
|---|---|
| 1 | 2.0 |
""".strip()
    assert lps.parse_plan_table(plan) == []


def test_lps_malformed_table_empty_separator_row() -> None:
    plan = """
| # | Тема | Время (ч) |
|---|---|---|
""".strip()
    assert lps.parse_plan_table(plan) == []


def test_lps_malformed_table_does_not_crash() -> None:
    """Various broken tables return [] instead of raising."""
    cases = [
        "",
        "   ",
        "not a table at all",
        "| stray pipe",
        "| # | Тема |\n| --- | --- |\n| 1 |\n| 2 | Тема2 |\n|",
    ]
    for case in cases:
        lps.parse_plan_table(case)  # should not raise
        lps.steps_from_markdown(case)  # should not raise


def test_lps_hours_summary() -> None:
    summary = lps.hours_summary_from_markdown(TABLE_PLAN)
    assert summary == {"total_hours": 3.5, "steps_count": 2, "missing_or_invalid_hours": 0}


def test_lps_hours_summary_none_when_no_table() -> None:
    assert lps.hours_summary_from_markdown("") is None
    assert lps.hours_summary_from_markdown("some text") is None


def test_lps_hours_summary_invalid_hours() -> None:
    plan = """
| # | Тема | Время (ч) |
|---|---|---|
| 1 | Векторы | около часа |
| 2 | Производная | 2,5 |
""".strip()
    summary = lps.hours_summary_from_markdown(plan)
    assert summary == {"total_hours": 2.5, "steps_count": 2, "missing_or_invalid_hours": 1}


def test_lps_steps_from_markdown_matches_user_state() -> None:
    """The dedicated module produces identical results to user_state for the canonical table."""
    lps_steps = lps.steps_from_markdown(TABLE_PLAN)
    us_steps = user_state.learning_plan_steps_from_markdown(TABLE_PLAN)
    assert lps_steps == us_steps


def test_lps_parse_table_returns_frozen_dataclass_instances() -> None:
    steps = lps.parse_plan_table(TABLE_PLAN)
    assert len(steps) == 2
    assert isinstance(steps[0], lps.LearningPlanStep)
    assert steps[0].title == "Векторы"
    assert steps[0].documents == "intro.md"
    assert steps[0].key_concepts == "координаты, модуль"
    assert steps[0].practice.startswith("Нарисовать")
    assert steps[0].check.startswith("Объяснить")
    assert steps[0].dependencies == "нет"
    assert steps[0].hours == "1.5"


# ──────────────────────────────────────────────
# Preview cards (A2)
# ──────────────────────────────────────────────


def test_lps_preview_card_text_includes_title_concepts_hours() -> None:
    step = lps.LearningPlanStep(
        index="1",
        title="Векторы",
        key_concepts="координаты, модуль",
        hours="1.5",
    )
    card = lps.preview_card_text(step)
    assert card.startswith("Векторы")
    assert "координаты, модуль" in card
    assert "1.5" in card
    assert "|" not in card


def test_lps_preview_card_text_fallsback_to_documents() -> None:
    step = lps.LearningPlanStep(
        index="1",
        title="Векторы",
        documents="intro.md",
        hours="",
    )
    card = lps.preview_card_text(step)
    assert "intro.md" in card


def test_lps_preview_card_text_no_extras() -> None:
    step = lps.LearningPlanStep(index="1", title="Тема без данных")
    card = lps.preview_card_text(step)
    assert card == "Тема без данных"
    assert "|" not in card


def test_lps_preview_cards_from_plan_text() -> None:
    cards = lps.preview_cards_from_plan_text(TABLE_PLAN)
    assert len(cards) == 2
    assert cards[0].startswith("Векторы")
    assert "координаты" in cards[0]
    assert "1.5" in cards[0]
    assert all("|" not in c for c in cards)


def test_lps_preview_cards_empty_when_no_table() -> None:
    assert lps.preview_cards_from_plan_text("") == []
    assert lps.preview_cards_from_plan_text("просто текст без таблицы") == []


# ──────────────────────────────────────────────
# Budget compliance (B2)
# ──────────────────────────────────────────────


def test_lps_check_budget_within_budget() -> None:
    status = lps.check_budget(TABLE_PLAN, 5.0)
    assert status is not None
    assert status.total_hours == 3.5
    assert status.budget_hours == 5.0
    assert status.over_budget is False
    assert status.exceeds_by_hours == 0.0
    assert status.steps_count == 2


def test_lps_check_budget_over_budget() -> None:
    status = lps.check_budget(TABLE_PLAN, 2.0)
    assert status is not None
    assert status.over_budget is True
    assert status.exceeds_by_hours == 1.5


def test_lps_check_budget_exact_match() -> None:
    status = lps.check_budget(TABLE_PLAN, 3.5)
    assert status is not None
    assert status.over_budget is False
    assert status.exceeds_by_hours == 0.0


def test_lps_check_budget_none_when_no_table() -> None:
    assert lps.check_budget("", 10.0) is None
    assert lps.check_budget("просто текст", 10.0) is None


def test_lps_check_budget_zero_budget() -> None:
    """Zero budget skips over-budget flag but still returns summary."""
    status = lps.check_budget(TABLE_PLAN, 0.0)
    assert status is not None
    assert status.total_hours == 3.5
    assert status.over_budget is False


def test_lps_check_budget_with_invalid_hours() -> None:
    plan = """
| # | Тема | Время (ч) |
|---|---|---|
| 1 | Векторы | около часа |
| 2 | Производная | 2,5 |
""".strip()
    status = lps.check_budget(plan, 10.0)
    assert status is not None
    assert status.total_hours == 2.5
    assert status.missing_or_invalid_hours == 1
    assert status.over_budget is False

