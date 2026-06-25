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
