from __future__ import annotations

import requests

from app.ui import topics_catalog


def _http_error(status_code: int, detail: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response._content = (  # noqa: SLF001 - requests test fixture
        ('{"detail": "' + detail + '"}').encode("utf-8")
    )
    response.headers["Content-Type"] = "application/json"
    return requests.HTTPError(f"{status_code} error", response=response)


def test_topics_catalog_503_is_throttled_between_reruns(monkeypatch) -> None:
    state = {"topics_catalog": None}
    calls = {"n": 0}

    def fail_fetch(*_args, **_kwargs):
        calls["n"] += 1
        raise _http_error(503, "requires full reindex")

    monkeypatch.setattr(topics_catalog.st, "session_state", state)
    monkeypatch.setattr(topics_catalog, "fetch_json", fail_fetch)

    assert topics_catalog.load_topics_catalog(force=False) is None
    assert topics_catalog.load_topics_catalog(force=False) is None

    assert calls["n"] == 1
    assert state["topics_catalog_error"] == "requires full reindex"


def test_topics_catalog_force_bypasses_error_throttle(monkeypatch) -> None:
    state = {"topics_catalog": None}
    calls = {"n": 0}

    def fail_fetch(*_args, **_kwargs):
        calls["n"] += 1
        raise _http_error(503, "requires full reindex")

    monkeypatch.setattr(topics_catalog.st, "session_state", state)
    monkeypatch.setattr(topics_catalog, "fetch_json", fail_fetch)

    topics_catalog.load_topics_catalog(force=False)
    topics_catalog.load_topics_catalog(force=True)

    assert calls["n"] == 2
