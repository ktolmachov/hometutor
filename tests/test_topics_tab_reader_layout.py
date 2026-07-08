from pathlib import Path

import app.ui.topics_tab_right_column as view


class _Container:
    def __init__(self, st):
        self.st = st

    def __enter__(self):
        self.st.container_calls += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStreamlit:
    def __init__(self, *, opened: bool):
        self.session_state = {"read_open": opened}
        self.container_calls = 0
        self.markdown_calls: list[str] = []
        self.warning_calls: list[str] = []

    def button(self, *_args, **_kwargs):
        return False

    def rerun(self):
        raise AssertionError("button was not clicked")

    def container(self, *, border=False):
        assert border is True
        return _Container(self)

    def markdown(self, text, *, unsafe_allow_html=False):
        assert unsafe_allow_html is False
        self.markdown_calls.append(str(text))

    def warning(self, text):
        self.warning_calls.append(str(text))

    def error(self, text):
        raise AssertionError(str(text))


def _patch_vault(monkeypatch, md_path: Path) -> None:
    import app.obsidian_export as obsidian_export

    monkeypatch.setattr(obsidian_export, "resolve_source", lambda _rel_path: object())
    monkeypatch.setattr(obsidian_export, "vault_target", lambda _src: md_path)


def test_read_button_only_toggles_and_does_not_render_markdown(monkeypatch, tmp_path):
    md_path = tmp_path / "note.md"
    md_path.write_text("# Note\n\nBody", encoding="utf-8")
    _patch_vault(monkeypatch, md_path)
    fake_st = _FakeStreamlit(opened=True)
    monkeypatch.setattr(view, "st", fake_st)

    view._render_obsidian_read_button("lesson.txt", key="read")

    assert fake_st.container_calls == 0
    assert fake_st.markdown_calls == []


def test_reader_panel_renders_open_note_full_width(monkeypatch, tmp_path):
    md_path = tmp_path / "note.md"
    md_path.write_text("---\ntitle: hidden\n---\n# Note\n\nBody", encoding="utf-8")
    _patch_vault(monkeypatch, md_path)
    fake_st = _FakeStreamlit(opened=True)
    monkeypatch.setattr(view, "st", fake_st)

    view._render_obsidian_reader_panel("lesson.txt", key="read")

    assert fake_st.container_calls == 1
    assert fake_st.markdown_calls == ["# Note\n\nBody"]
