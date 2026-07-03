from pathlib import Path

import pytest

from app import demo_sandbox


def test_install_demo_materials_copies_six_markdown_files(monkeypatch, tmp_path) -> None:
    source = tmp_path / "demo_data"
    data = tmp_path / "data"
    source.mkdir()
    for name in [
        "alpha_rag_intro.md",
        "beta_vector_db.md",
        "gamma_hybrid.md",
        "delta_srs.md",
        "epsilon_guardrails.md",
        "python_basics.md",
        "README.md",
    ]:
        (source / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(demo_sandbox, "DATA_DIR", data)
    monkeypatch.setattr(demo_sandbox, "demo_source_dir", lambda: source)

    first = demo_sandbox.install_demo_materials()
    second = demo_sandbox.install_demo_materials()

    assert len(first) == 6
    assert first == second
    assert "demo/README.md" not in first
    assert all((data / rel).exists() for rel in first)


def test_remove_demo_materials_deletes_only_data_demo(monkeypatch, tmp_path) -> None:
    data = tmp_path / "data"
    demo = data / "demo"
    other = data / "uploads"
    demo.mkdir(parents=True)
    other.mkdir()
    (demo / "a.md").write_text("demo", encoding="utf-8")
    (other / "b.md").write_text("other", encoding="utf-8")
    monkeypatch.setattr(demo_sandbox, "DATA_DIR", data)
    monkeypatch.setattr(demo_sandbox, "demo_target_dir", lambda: demo)

    assert demo_sandbox.remove_demo_materials() == 1
    assert not demo.exists()
    assert (other / "b.md").exists()

    monkeypatch.setattr(demo_sandbox, "demo_target_dir", lambda: tmp_path / "outside")
    with pytest.raises(ValueError):
        demo_sandbox.remove_demo_materials()


def test_count_supported_materials_ignores_readme_and_service_files(monkeypatch, tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for name in ["a.md", "b.txt", "c.pdf", "d.docx", "e.html", "README.md", "state.db", ".hidden.md"]:
        (data / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(demo_sandbox, "DATA_DIR", data)

    assert demo_sandbox.count_supported_materials() == 5


def test_save_uploaded_files_filters_and_sanitizes(monkeypatch, tmp_path) -> None:
    data = tmp_path / "data"
    monkeypatch.setattr(demo_sandbox, "DATA_DIR", data)

    saved = demo_sandbox.save_uploaded_files(
        [
            ("../evil.md", b"ok"),
            ("bad.exe", b"no"),
            ("nested\\lecture one?.txt", b"txt"),
        ]
    )

    assert saved == ["uploads/evil.md", "uploads/lecture one_.txt"]
    assert (data / "uploads" / "evil.md").read_bytes() == b"ok"
    assert not (data / "uploads" / "bad.exe").exists()
