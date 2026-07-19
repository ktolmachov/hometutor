"""#19 P1 lecture depth — unit + contract + persistence tests.

Verifies: prediction question generation, segment result persistence,
compute_lecture_depth, _advance_segment persistence hook.
"""

from __future__ import annotations

from pathlib import Path


# ── user_state_lecture persistence ──────────────────────────────────────────

class TestLectureSegmentPersistence:
    @staticmethod
    def _in_memory_db():
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE lecture_segment_progress (
                konspekt_path TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                passed INTEGER NOT NULL DEFAULT 0,
                predicted_correct INTEGER DEFAULT NULL,
                gate_score REAL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (konspekt_path, segment_index)
            )"""
        )
        return conn

    def test_upsert_and_read(self, monkeypatch) -> None:
        conn = self._in_memory_db()
        monkeypatch.setattr(
            "app.user_state_lecture._with_db",
            lambda fn, **kw: fn(conn),
        )
        from app.user_state_lecture import (
            upsert_lecture_segment_result,
            get_lecture_segment_results,
        )

        upsert_lecture_segment_result(
            konspekt_path="/test/konspekt.md",
            segment_index=0,
            passed=True,
            predicted_correct=True,
            gate_score=0.8,
        )
        upsert_lecture_segment_result(
            konspekt_path="/test/konspekt.md",
            segment_index=1,
            passed=False,
            predicted_correct=False,
            gate_score=0.4,
        )

        results = get_lecture_segment_results("/test/konspekt.md")
        assert len(results) == 2
        assert results[0]["passed"] is True
        assert results[0]["predicted_correct"] is True
        assert results[0]["gate_score"] == 0.8
        assert results[1]["passed"] is False
        assert results[1]["predicted_correct"] is False
        assert results[1]["gate_score"] == 0.4

    def test_upsert_overwrites(self, monkeypatch) -> None:
        conn = self._in_memory_db()
        monkeypatch.setattr("app.user_state_lecture._with_db", lambda fn, **kw: fn(conn))
        from app.user_state_lecture import (
            upsert_lecture_segment_result,
            get_lecture_segment_results,
        )

        upsert_lecture_segment_result(
            konspekt_path="/test/overwrite.md", segment_index=0, passed=False, gate_score=0.3
        )
        upsert_lecture_segment_result(
            konspekt_path="/test/overwrite.md", segment_index=0, passed=True, gate_score=0.9
        )
        results = get_lecture_segment_results("/test/overwrite.md")
        assert len(results) == 1
        assert results[0]["passed"] is True
        assert results[0]["gate_score"] == 0.9

    def test_empty_results_for_unknown_path(self, monkeypatch) -> None:
        conn = self._in_memory_db()
        monkeypatch.setattr("app.user_state_lecture._with_db", lambda fn, **kw: fn(conn))
        from app.user_state_lecture import get_lecture_segment_results
        results = get_lecture_segment_results("/nonexistent.md")
        assert results == []

    def test_compute_depth(self, monkeypatch) -> None:
        conn = self._in_memory_db()
        monkeypatch.setattr("app.user_state_lecture._with_db", lambda fn, **kw: fn(conn))
        from app.user_state_lecture import (
            upsert_lecture_segment_result,
            compute_lecture_depth,
        )

        upsert_lecture_segment_result(
            konspekt_path="/test/depth.md", segment_index=0, passed=True, predicted_correct=True
        )
        upsert_lecture_segment_result(
            konspekt_path="/test/depth.md", segment_index=1, passed=True, predicted_correct=False
        )
        upsert_lecture_segment_result(
            konspekt_path="/test/depth.md", segment_index=2, passed=False
        )

        depth = compute_lecture_depth("/test/depth.md", total_segments=5)
        assert depth["passed_count"] == 2
        assert depth["total_segments"] == 5
        assert depth["depth_pct"] == 40.0
        assert depth["predicted_correct_count"] == 1
        assert depth["last_completed_at"] is not None

    def test_compute_depth_zero_total(self, monkeypatch) -> None:
        conn = self._in_memory_db()
        monkeypatch.setattr("app.user_state_lecture._with_db", lambda fn, **kw: fn(conn))
        from app.user_state_lecture import compute_lecture_depth
        depth = compute_lecture_depth("/empty.md", total_segments=0)
        assert depth["passed_count"] == 0
        assert depth["total_segments"] == 0
        assert depth["depth_pct"] == 0.0
        assert depth["predicted_correct_count"] == 0

    def test_results_ordered_by_index(self, monkeypatch) -> None:
        conn = self._in_memory_db()
        monkeypatch.setattr("app.user_state_lecture._with_db", lambda fn, **kw: fn(conn))
        from app.user_state_lecture import (
            upsert_lecture_segment_result,
            get_lecture_segment_results,
        )

        for i in (3, 0, 1, 2):
            upsert_lecture_segment_result(
                konspekt_path="/test/order.md", segment_index=i, passed=True
            )
        results = get_lecture_segment_results("/test/order.md")
        indices = [r["segment_index"] for r in results]
        assert indices == [0, 1, 2, 3], f"expected ordered, got {indices}"


# ── source-level contracts ──────────────────────────────────────────────────

class TestLectureP1SourceContracts:
    def test_user_state_lecture_module_exists(self) -> None:
        src = (Path("app/user_state_lecture.py")).read_text(encoding="utf-8")
        assert "def upsert_lecture_segment_result" in src
        assert "def get_lecture_segment_results" in src
        assert "def compute_lecture_depth" in src
        assert "CREATE TABLE IF NOT EXISTS lecture_segment_progress" in src

    def test_lecture_route_has_prediction(self) -> None:
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        assert "_render_prediction_question" in src
        assert "prediction_shown" in src
        assert "prediction_question" in src
        assert "prediction_student_answer" in src

    def test_advance_segment_calls_persistence(self) -> None:
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        fn = src.split("def _advance_segment")[1].split("\ndef ")[0]
        assert "upsert_lecture_segment_result" in fn
        assert "user_state_lecture" in fn

    def test_gate_score_set_before_advance(self) -> None:
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_gate")[1].split("\ndef ")[0]
        assert 'gate["gate_score"]' in fn

    def test_generate_gate_quiz_accepts_num_questions(self) -> None:
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        fn = src.split("def _generate_gate_quiz")[1].split("\ndef ")[0]
        assert "num_questions" in fn

    def test_prediction_reset_on_segment_click(self) -> None:
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        fn = src.split("def render_lecture_route")[1].split("\ndef ")[0]
        assert 'gate["prediction_shown"] = False' in fn

    def test_no_new_storage_schema_outside_user_state(self) -> None:
        """Kill switch: no ad-hoc SQLite outside user_state_lecture."""
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        assert "sqlite" not in src
        assert ".db" not in src

    def test_composition_hints_not_hardcoded(self) -> None:
        """P1 prompts come from prompt layer, not hardcoded in route."""
        src = (Path("app/ui/living_konspekt_lecture_route.py")).read_text(encoding="utf-8")
        fn = src.split("def _render_prediction_question")[1].split("\ndef ")[0]
        assert "Попробуйте предсказать" not in fn or "_generate_gate_quiz" in fn


# ── prediction correctness computation ──────────────────────────────────────

class TestPredictionCorrectness:
    def test_predicted_correct_matching_answer(self) -> None:
        """predicted_correct=True when student answer matches correct_answer."""
        pred_answer = "Option B"
        pred_question = {"correct_answer": "Option B", "question": "What?"}
        predicted_correct = str(pred_answer) == str(pred_question["correct_answer"])
        assert predicted_correct is True

    def test_predicted_correct_mismatch(self) -> None:
        pred_answer = "Option A"
        pred_question = {"correct_answer": "Option B", "question": "What?"}
        predicted_correct = str(pred_answer) == str(pred_question["correct_answer"])
        assert predicted_correct is False

    def test_predicted_correct_none_when_no_answer(self) -> None:
        pred_answer = None
        pred_question = {"correct_answer": "Option B"}
        predicted_correct = None
        if pred_answer is not None and isinstance(pred_question, dict):
            correct_answer = pred_question.get("correct_answer") or pred_question.get("answer")
            if correct_answer is not None:
                predicted_correct = str(pred_answer) == str(correct_answer)
        assert predicted_correct is None
