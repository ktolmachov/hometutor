from types import SimpleNamespace

from app import config, ingestion_support


def test_first_session_precompute_tail_skips_when_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(enable_first_session_precompute=False),
    )

    def fail_if_called(**_kwargs):
        raise AssertionError("list_course_candidates should not run when precompute is disabled")

    monkeypatch.setattr(ingestion_support, "list_course_candidates", fail_if_called)

    ingestion_support.run_first_session_precompute_tail(docs_root=tmp_path)


def test_list_course_candidates_from_index_includes_user_folders_excludes_service() -> None:
    # A1: candidate source must mirror the hero resolver — demo/uploads/docs qualify,
    # service folders never do, regardless of where the old data/docs scope sat.
    from app.course_cache import list_course_candidates_from_index

    cands = list_course_candidates_from_index([
        "demo/lesson.pdf", "demo/a.md",
        "uploads/note.txt",
        "docs/course/c.md",
        "cache/x.md",          # service
        ".git/internal.md",    # service
        "__pycache__/p.md",    # service
    ])
    folders = {c["folder_rel"] for c in cands}
    assert folders == {"demo", "uploads", "docs"}
    demo = next(c for c in cands if c["folder_rel"] == "demo")
    assert demo["source_paths"] == ["demo/a.md", "demo/lesson.pdf"]


def test_precompute_tail_derives_candidates_from_indexed_files(monkeypatch, tmp_path) -> None:
    # A1: with precompute enabled, the tail builds artifacts for folders present in the
    # index manifest (demo, docs) — even when docs_root points nowhere. This is what
    # unblocks the demo/upload first-run doors.
    # Import these BEFORE patching get_settings so their module-level get_settings() calls
    # run with the real Settings object (metrics_core etc. read many fields at import).
    import app.ingestion as ing_mod
    import app.ingestion_content_state as ics

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(enable_first_session_precompute=True))
    monkeypatch.setattr(ics, "build_file_manifest", lambda root, exts: {"files": {"demo/lesson.pdf": {}, "docs/note.md": {}}})
    monkeypatch.setattr(ing_mod, "get_doc_supported_exts", lambda: {".md", ".pdf"})

    built: list[str] = []
    monkeypatch.setattr(
        ingestion_support,
        "_build_and_save_first_session_candidate",
        lambda *, candidate, docs_root, retrieve_fn, logger: built.append(candidate["folder_rel"]),
    )

    ingestion_support.run_first_session_precompute_tail(docs_root=tmp_path / "missing_docs")
    assert set(built) == {"demo", "docs"}
