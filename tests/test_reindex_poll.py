from app.ui import reindex_poll


def test_poll_reindex_status_clears_caches_after_completed(monkeypatch) -> None:
    state = {"poll_reindex_status": True}
    called = {"clear": 0, "rerun": 0}

    monkeypatch.setattr(reindex_poll.st, "session_state", state)
    monkeypatch.setattr(
        reindex_poll,
        "fetch_json",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "ingest_run_summary": {"human_ru": "Готово"},
        },
    )
    monkeypatch.setattr(reindex_poll, "clear_ui_api_caches", lambda: called.__setitem__("clear", called["clear"] + 1))
    monkeypatch.setattr(reindex_poll.st, "rerun", lambda: called.__setitem__("rerun", called["rerun"] + 1))
    monkeypatch.setattr(reindex_poll.st, "success", lambda *_args, **_kwargs: None)

    reindex_poll.poll_reindex_status()

    assert state["poll_reindex_status"] is False
    assert state["_reindex_success_message"] == "Готово"
    assert called == {"clear": 1, "rerun": 1}


def test_poll_reindex_status_does_not_clear_caches_while_running(monkeypatch) -> None:
    state = {"poll_reindex_status": True}
    called = {"clear": 0}

    monkeypatch.setattr(reindex_poll.st, "session_state", state)
    monkeypatch.setattr(reindex_poll, "fetch_json", lambda *_args, **_kwargs: {"status": "running"})
    monkeypatch.setattr(reindex_poll, "clear_ui_api_caches", lambda: called.__setitem__("clear", called["clear"] + 1))
    monkeypatch.setattr(reindex_poll.st, "info", lambda *_args, **_kwargs: None)

    reindex_poll.poll_reindex_status()

    assert state["poll_reindex_status"] is True
    assert called["clear"] == 0
