import json
from pathlib import Path

from app.graph_publish_status import (
    _compact_report,
    build_learner_publish_status_view,
    get_graph_publish_status,
    graph_freshness_gap,
)


def _write_registry(path: Path, *, active_gid: str, previous_gid: str | None = None) -> None:
    previous = None
    if previous_gid:
        previous = {
            "generation_id": previous_gid,
            "chunks_collection": f"{previous_gid}_chunks",
            "summaries_collection": f"{previous_gid}_summaries",
        }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "index_version": 2,
                "active_generation": {
                    "generation_id": active_gid,
                    "chunks_collection": f"{active_gid}_chunks",
                    "summaries_collection": f"{active_gid}_summaries",
                },
                "previous_generation": previous,
                "staging_generation": None,
                "last_failed_generation": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_bundle(root: Path, generation_id: str, *, gate_passed: bool = True) -> None:
    bundle_dir = root / generation_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "kg.sqlite").write_bytes(b"placeholder")
    (bundle_dir / "graph_quality_report.json").write_text(
        json.dumps(
            {
                "generation_id": generation_id,
                "gate_passed": gate_passed,
                "published": gate_passed,
                "metrics": {"concept_count": 7},
                "fail_reasons": [] if gate_passed else ["blocked"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_publish_status_falls_back_to_previous_when_active_bundle_missing(tmp_path, monkeypatch):
    from app import graph_generation_paths, index_registry

    registry_path = tmp_path / "index_registry.json"
    monkeypatch.setattr(index_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(index_registry, "REGISTRY_LOCK_PATH", tmp_path / "index_registry.lock")
    by_generation = tmp_path / "graph_generations" / "by_generation"
    staging = tmp_path / "graph_generations" / "staging"
    monkeypatch.setattr(graph_generation_paths, "BY_GENERATION_ROOT", by_generation)
    monkeypatch.setattr(graph_generation_paths, "STAGING_ROOT", staging)

    _write_registry(registry_path, active_gid="active-gen", previous_gid="previous-gen")
    _write_bundle(by_generation, "previous-gen")
    _write_bundle(staging, "staging-failed", gate_passed=False)

    status = get_graph_publish_status()

    assert status["reader_source"] == "previous"
    assert status["reader_generation_id"] == "previous-gen"
    assert status["active"]["exists"] is False
    assert status["previous"]["exists"] is True
    assert status["latest_failed_staging"]["label"] == "staging-failed"


def test_publish_status_prefers_active_bundle_when_present(tmp_path, monkeypatch):
    from app import graph_generation_paths, index_registry

    registry_path = tmp_path / "index_registry.json"
    monkeypatch.setattr(index_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(index_registry, "REGISTRY_LOCK_PATH", tmp_path / "index_registry.lock")
    by_generation = tmp_path / "graph_generations" / "by_generation"
    monkeypatch.setattr(graph_generation_paths, "BY_GENERATION_ROOT", by_generation)
    monkeypatch.setattr(graph_generation_paths, "STAGING_ROOT", tmp_path / "graph_generations" / "staging")

    _write_registry(registry_path, active_gid="active-gen", previous_gid="previous-gen")
    _write_bundle(by_generation, "active-gen")
    _write_bundle(by_generation, "previous-gen")

    status = get_graph_publish_status()

    assert status["reader_source"] == "active"
    assert status["reader_generation_id"] == "active-gen"
    assert status["active"]["report"]["gate_passed"] is True


def test_compact_report_dedupes_fail_reasons() -> None:
    report = _compact_report(
        {
            "gate_passed": False,
            "fail_reasons": ["Конфликт alias: LLM vs LLM", "Конфликт alias: LLM vs LLM", "  "],
        }
    )

    assert report["fail_reasons"] == ["Конфликт alias: LLM vs LLM"]


def test_compact_report_preserves_source_paths() -> None:
    # A1 (fixed): _compact_report must preserve the *list* (for set-based freshness),
    # not only count. Legacy count-only reports still supported via fallback.
    rep = _compact_report({"source_paths": ["demo/a.md", "demo/b.md"], "published": True})
    assert rep["source_paths_count"] == 2
    assert rep["source_paths"] == ["demo/a.md", "demo/b.md"]

    assert _compact_report({})["source_paths_count"] == 0
    assert _compact_report({})["source_paths"] == []

    assert _compact_report({"source_paths": "not-a-list"})["source_paths_count"] == 0
    assert _compact_report({"source_paths": "not-a-list"})["source_paths"] == []

    # Hashes are also preserved (for heuristic contract + content-based checks)
    rep2 = _compact_report({
        "source_paths": ["f1.md"],
        "source_content_hashes": ["h1", "h1", " h2 "],
        "published": True
    })
    assert rep2["source_content_hashes"] == ["h1", "h2"]
    assert rep2["source_content_hashes_count"] == 2


def test_graph_freshness_gap_counts_index_minus_active_graph() -> None:
    # Legacy count-only path (no "source_paths" list in report): still works for back-compat.
    index_stats = {"files": ["demo/a.md", "demo/b.md", "demo/c.md"]}
    publish_status = {"active": {"report": {"source_paths_count": 2}}}
    assert graph_freshness_gap(index_stats, publish_status) == 1


def test_graph_freshness_gap_zero_when_fresh_or_no_index() -> None:
    fresh = {"active": {"report": {"source_paths_count": 3}}}
    assert graph_freshness_gap({"files": ["a.md", "b.md", "c.md"]}, fresh) == 0
    # No indexed materials → nothing to lag behind.
    assert graph_freshness_gap({"files": []}, fresh) == 0
    assert graph_freshness_gap(None, fresh) == 0
    # Promote skipped: active bundle has no report → whole index looks "not on the map" (legacy count path).
    assert graph_freshness_gap({"files": ["a.md", "b.md"]}, {"active": {"report": None}}) == 2


def test_graph_freshness_gap_uses_actual_set_not_just_count() -> None:
    """P1: critical fix — must detect staleness by set membership, not |count|.

    Same cardinality but different members → positive gap.
    """
    # index has a,b,c ; graph recorded a,b,d (same count=3) → c is missing from map
    index_stats = {"files": ["demo/a.md", "demo/b.md", "demo/c.md"]}
    publish_status = {
        "active": {
            "report": {
                "source_paths": ["demo/a.md", "demo/b.md", "demo/d.md"],
                "source_paths_count": 3,
            }
        }
    }
    assert graph_freshness_gap(index_stats, publish_status) == 1

    # Overlap but net missing
    index_stats2 = {"files": ["x.md", "y.md", "z.md"]}
    publish_status2 = {"active": {"report": {"source_paths": ["y.md", "z.md", "w.md"]}}}
    assert graph_freshness_gap(index_stats2, publish_status2) == 1  # x missing


def test_graph_freshness_gap_filters_non_user_paths() -> None:
    """Technical/service paths in the raw index 'files' must not contribute to gap
    (they are excluded from graph source_paths too via is_user_source_path).
    """
    # "cache/..." and "_tmp/..." are technical → filtered out on index side before set diff
    index_stats = {"files": ["demo/real.md", "cache/internal.json", "_tmp/scratch.txt", "docs/lec.md"]}
    # graph only knows the user ones
    publish_status = {"active": {"report": {"source_paths": ["demo/real.md", "docs/lec.md"]}}}
    # even though raw len(index)=4, after user filter len=2, and set matches graph → gap 0
    assert graph_freshness_gap(index_stats, publish_status) == 0

    # a new user file appears
    index_stats2 = {"files": ["demo/real.md", "docs/lec.md", "uploads/new.pdf", "cache/foo"]}
    assert graph_freshness_gap(index_stats2, publish_status) == 1  # uploads/new.pdf


def _assert_no_engineer_jargon(text: str) -> None:
    lowered = text.lower()
    for banned in ("bundle", "staging", "promote", "generation", "published graph", "read-path"):
        assert banned not in lowered, f"learner surface still has jargon: {banned!r} in {text!r}"


def test_learner_publish_status_active_is_plain_language() -> None:
    view = build_learner_publish_status_view(
        {
            "reader_source": "active",
            "reader_generation_id": "gen-active-1",
            "active": {
                "generation_id": "gen-active-1",
                "exists": True,
                "report": {"gate_passed": True, "published": True},
            },
            "previous": {},
            "latest_failed_staging": None,
        }
    )
    assert view["tone"] == "success"
    assert view["primary"] == "Карта актуальна"
    assert view["badge_label"] is None
    _assert_no_engineer_jargon(view["primary"])
    # Technical ids only in debug tier
    assert any("gen-active-1" in line for line in view["debug_lines"])


def test_learner_publish_status_previous_and_failed_attempt() -> None:
    from app.graph_publish_status import LEARNER_MAP_PREVIEW_WARNING

    view = build_learner_publish_status_view(
        {
            "reader_source": "previous",
            "reader_generation_id": "gen-prev",
            "active": {"generation_id": "gen-new", "exists": False, "report": None},
            "previous": {"generation_id": "gen-prev", "exists": True, "report": {"published": True}},
            "latest_failed_staging": {
                "label": "staging-xyz",
                "report": {
                    "fail_reasons": ["Недостаточно документов для семантического графа"],
                    "metrics": {"doc_count": 1, "concept_count": 2, "semantic_relation_count": 0},
                },
            },
        }
    )
    assert view["tone"] == "warning"
    assert "предыдущая версия" in view["primary"].lower()
    assert view["badge_label"] == "⚠ предыдущая карта"
    assert view["badge_title"] == view["primary"]
    _assert_no_engineer_jargon(view["primary"])
    _assert_no_engineer_jargon(view["badge_label"])
    assert view["failed_title"]
    _assert_no_engineer_jargon(view["failed_title"])
    assert any("Добавьте ещё" in r for r in view["failed_reasons"])
    # P4: only keys present in metrics (no synthetic evidence/docs zeros)
    assert view["failed_metrics"] == ["концепты 2", "связи 0"]
    surface = " ".join(
        [
            view["primary"],
            *view["captions"],
            str(view["failed_title"]),
            *view["failed_reasons"],
            *view["failed_metrics"],
            str(view["badge_label"] or ""),
            LEARNER_MAP_PREVIEW_WARNING,
        ]
    )
    _assert_no_engineer_jargon(surface)


def test_learner_publish_status_legacy_and_unavailable() -> None:
    legacy = build_learner_publish_status_view({"reader_source": "legacy", "active": {}, "previous": {}})
    assert "не собрана" in legacy["primary"].lower()
    assert legacy["badge_label"] == "⚠ карта не собрана"
    _assert_no_engineer_jargon(legacy["primary"])
    _assert_no_engineer_jargon(legacy["badge_label"])

    missing = build_learner_publish_status_view(None)
    assert "временно недоступен" in missing["primary"].lower()
    _assert_no_engineer_jargon(missing["primary"])


def test_kg_mission_badge_uses_learner_view(monkeypatch) -> None:
    """P1: Mission Control badge must share learner copy, not engineer jargon."""
    import app.ui.mission_control as mc

    monkeypatch.setattr(
        "app.graph_publish_status.get_graph_publish_status",
        lambda: {
            "reader_source": "previous",
            "reader_generation_id": "g-prev",
            "active": {"exists": False, "generation_id": "g-new"},
            "previous": {"exists": True, "generation_id": "g-prev"},
        },
    )
    html_out = mc._kg_bundle_state_badge()
    assert "предыдущая карта" in html_out
    assert "previous bundle" not in html_out.lower()
    assert "bundle" not in html_out.lower()
    assert "generation" not in html_out.lower()
