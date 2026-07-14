from streamlit.errors import StreamlitAPIException

from app.ui import control_panel


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
