from pathlib import Path


def test_streamlit_toasts_do_not_use_plain_checkmark_icon() -> None:
    offenders: list[str] = []
    for path in Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if 'icon="✓"' in text or "icon='✓'" in text:
            offenders.append(str(path))

    assert offenders == []
