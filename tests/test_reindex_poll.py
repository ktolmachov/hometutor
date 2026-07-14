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


def test_poll_reindex_status_remembers_graph_refresh_after_completed(monkeypatch) -> None:
    state = {"poll_reindex_status": True}

    graph_refresh = {
        "ok": True,
        "published": False,
        "gate_passed": False,
        "quality_report": {"fail_reasons": ["Не все связи с evidence"]},
    }
    monkeypatch.setattr(reindex_poll.st, "session_state", state)
    monkeypatch.setattr(
        reindex_poll,
        "fetch_json",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "ingest_run_summary": {"human_ru": "Готово"},
            "cost": {"knowledge_graph_refresh": graph_refresh},
        },
    )
    monkeypatch.setattr(reindex_poll, "clear_ui_api_caches", lambda: None)
    monkeypatch.setattr(reindex_poll.st, "rerun", lambda: None)
    monkeypatch.setattr(reindex_poll.st, "success", lambda *_args, **_kwargs: None)

    reindex_poll.poll_reindex_status()

    assert state["last_ingest_graph_refresh"] == graph_refresh


def test_poll_reindex_status_navigates_after_completed(monkeypatch) -> None:
    state = {"poll_reindex_status": True, "_reindex_after_view": "Knowledge Graph"}

    monkeypatch.setattr(reindex_poll.st, "session_state", state)
    monkeypatch.setattr(
        reindex_poll,
        "fetch_json",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "ingest_run_summary": {"human_ru": "Готово"},
        },
    )
    monkeypatch.setattr(reindex_poll, "clear_ui_api_caches", lambda: None)
    monkeypatch.setattr(reindex_poll.st, "rerun", lambda: None)
    monkeypatch.setattr(reindex_poll.st, "success", lambda *_args, **_kwargs: None)

    reindex_poll.poll_reindex_status()

    assert state["_pending_current_view"] == "Knowledge Graph"
    assert "_reindex_after_view" not in state


def test_poll_reindex_status_does_not_clear_caches_while_running(monkeypatch) -> None:
    state = {"poll_reindex_status": True}
    called = {"clear": 0, "progress": 0, "rerun": 0}

    monkeypatch.setattr(reindex_poll.st, "session_state", state)
    monkeypatch.setattr(
        reindex_poll,
        "fetch_json",
        lambda *_args, **_kwargs: {
            "status": "running",
            "lifecycle_phase": "building",
            "ingest_unique_processed": 7,
            "ingest_unique_total": 19,
            "current_file": "uploads/hometutor_101/README.md",
        },
    )
    monkeypatch.setattr(
        reindex_poll,
        "clear_ui_api_caches",
        lambda: called.__setitem__("clear", called["clear"] + 1),
    )
    monkeypatch.setattr(
        reindex_poll.st,
        "progress",
        lambda *_args, **_kwargs: called.__setitem__("progress", called["progress"] + 1),
    )
    monkeypatch.setattr(
        reindex_poll,
        "_refresh_soon",
        lambda *_args, **_kwargs: called.__setitem__("rerun", called["rerun"] + 1),
    )

    reindex_poll.poll_reindex_status()

    assert state["poll_reindex_status"] is True
    assert called["clear"] == 0
    assert called["progress"] == 1
    assert called["rerun"] == 1


def test_poll_reindex_status_shows_starting_state_before_worker_updates(monkeypatch) -> None:
    state = {"poll_reindex_status": True}
    called = {"info": [], "rerun": 0}

    monkeypatch.setattr(reindex_poll.st, "session_state", state)
    monkeypatch.setattr(reindex_poll, "fetch_json", lambda *_args, **_kwargs: {"status": "idle"})
    monkeypatch.setattr(reindex_poll.st, "info", lambda message, *_args, **_kwargs: called["info"].append(message))
    monkeypatch.setattr(
        reindex_poll,
        "_refresh_soon",
        lambda *_args, **_kwargs: called.__setitem__("rerun", called["rerun"] + 1),
    )

    reindex_poll.poll_reindex_status()

    assert state["poll_reindex_status"] is True
    assert called["info"] == ["Запускаю индексацию материалов…"]
    assert called["rerun"] == 1
