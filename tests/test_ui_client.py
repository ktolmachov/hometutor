from app import ui_client


class _DummyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"status": "ok"}


class _DummySession:
    def __init__(self) -> None:
        self.get_kwargs: dict | None = None

    def get(self, _url: str, **kwargs):
        self.get_kwargs = kwargs
        return _DummyResponse()


def test_ui_bootstrap_sends_auth_headers(monkeypatch):
    session = _DummySession()
    monkeypatch.setattr(ui_client, "_http_session", lambda: session)
    monkeypatch.setattr(
        ui_client,
        "_auth_headers",
        lambda extra_headers=None: {"Authorization": "Bearer token"},
    )

    call = getattr(ui_client._cached_ui_bootstrap, "__wrapped__", ui_client._cached_ui_bootstrap)

    assert call("http://api.local") == {"status": "ok"}
    assert session.get_kwargs is not None
    assert session.get_kwargs["headers"] == {"Authorization": "Bearer token"}
