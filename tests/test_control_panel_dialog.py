from streamlit.errors import StreamlitAPIException

from app.ui import control_panel


def test_theme_card_uses_html_title_instead_of_raw_markdown(monkeypatch) -> None:
    class _Container:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    markdown_calls: list[tuple[str, bool]] = []

    def _capture_markdown(body: str, *, unsafe_allow_html: bool = False) -> None:
        markdown_calls.append((body, unsafe_allow_html))

    monkeypatch.setattr(control_panel.st, "container", lambda **_kwargs: _Container())
    monkeypatch.setattr(control_panel.st, "markdown", _capture_markdown)
    monkeypatch.setattr(control_panel.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(control_panel.st, "button", lambda *_args, **_kwargs: False)

    control_panel._render_theme_card("berry", current_theme="forest")

    assert markdown_calls
    body, unsafe = markdown_calls[0]
    assert unsafe is True
    assert "**" not in body
    assert "<strong>🍇 Ягода</strong>" in body


def test_open_control_panel_dialog_suppresses_duplicate_dialog_error(monkeypatch) -> None:
    warnings: list[str] = []

    def _raise_duplicate_dialog() -> None:
        raise StreamlitAPIException("Only one dialog is allowed to be opened at the same time.")

    monkeypatch.setattr(control_panel, "render_control_panel_dialog", _raise_duplicate_dialog)
    monkeypatch.setattr(control_panel.st, "warning", lambda message: warnings.append(str(message)))

    control_panel.open_control_panel_dialog()

    assert warnings == ["Закройте текущее всплывающее окно и откройте настройки ещё раз."]


def test_open_control_panel_dialog_reraises_unexpected_streamlit_errors(monkeypatch) -> None:
    def _raise_other_error() -> None:
        raise StreamlitAPIException("Unexpected Streamlit dialog failure.")

    monkeypatch.setattr(control_panel, "render_control_panel_dialog", _raise_other_error)

    try:
        control_panel.open_control_panel_dialog()
    except StreamlitAPIException as exc:
        assert "Unexpected Streamlit dialog failure" in str(exc)
    else:
        raise AssertionError("Unexpected StreamlitAPIException should be re-raised")
