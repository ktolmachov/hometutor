"""Demo sandbox and first-run material helpers."""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath

from app.config import BASE_DIR, DATA_DIR

DEMO_SUBDIR = "demo"
UPLOADS_SUBDIR = "uploads"
BUILTIN_DEMO_COURSE_REL = Path(UPLOADS_SUBDIR) / "hometutor_101"
ALLOWED_UPLOAD_EXTS = {".md", ".txt", ".pdf", ".docx", ".html"}

_SAFE_NAME_RE = re.compile(r"[^A-Za-zА-Яа-я0-9._ -]+")


def demo_source_dir() -> Path:
    return BASE_DIR / "demo_data"


def demo_target_dir() -> Path:
    return DATA_DIR / DEMO_SUBDIR


def builtin_demo_course_source_dir() -> Path:
    return demo_source_dir() / BUILTIN_DEMO_COURSE_REL


def builtin_demo_course_target_dir() -> Path:
    return DATA_DIR / BUILTIN_DEMO_COURSE_REL


def _relative_to_data(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


def _require_data_child(path: Path) -> Path:
    root = DATA_DIR.resolve()
    target = path.resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("Path must stay inside the data directory")
    return target


def is_demo_installed() -> bool:
    target = demo_target_dir()
    mini_demo_installed = target.is_dir() and any(
        path.is_file() and path.suffix.lower() == ".md" and path.name.lower() != "readme.md"
        for path in target.rglob("*")
    )
    course = builtin_demo_course_target_dir()
    course_installed = (course / "README.md").is_file() and any(
        path.is_file() and path.suffix.lower() == ".md"
        for path in (course / "lectures").glob("*.md")
    )
    return mini_demo_installed or course_installed


def _copy_tree_files(source: Path, target: Path) -> list[str]:
    saved: list[str] = []
    if not source.is_dir():
        return saved
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        destination = _require_data_child(target / rel)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        saved.append(_relative_to_data(destination))
    return saved


def install_demo_materials() -> list[str]:
    source = demo_source_dir()
    target = demo_target_dir()
    target.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for path in sorted(source.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        destination = target / path.name
        shutil.copy2(path, destination)
        saved.append(_relative_to_data(destination))
    saved.extend(
        _copy_tree_files(
            builtin_demo_course_source_dir(),
            builtin_demo_course_target_dir(),
        )
    )
    return saved


def remove_demo_materials() -> int:
    removed = 0
    for target in (demo_target_dir(), builtin_demo_course_target_dir()):
        target = _require_data_child(target)
        if not target.exists():
            continue
        removed += sum(1 for path in target.rglob("*") if path.is_file())
        shutil.rmtree(target)
    return removed


def count_supported_materials() -> int:
    root = DATA_DIR
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if path.name.lower() == "readme.md":
            continue
        if path.suffix.lower() in ALLOWED_UPLOAD_EXTS:
            count += 1
    return count


def _safe_upload_name(raw_name: str) -> str:
    name = PurePosixPath(str(raw_name or "").replace("\\", "/")).name.strip()
    if not name:
        name = "material"
    suffix = PurePosixPath(name).suffix.lower()
    stem = (name[: -len(suffix)] if suffix else name).strip() or "material"
    safe_stem = _SAFE_NAME_RE.sub("_", stem).strip(" .") or "material"
    return f"{safe_stem}{suffix}"


def save_uploaded_files(files: list[tuple[str, bytes]]) -> list[str]:
    target = DATA_DIR / UPLOADS_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for raw_name, content in files:
        filename = _safe_upload_name(raw_name)
        if Path(filename).suffix.lower() not in ALLOWED_UPLOAD_EXTS:
            continue
        destination = _require_data_child(target / filename)
        destination.write_bytes(content)
        saved.append(_relative_to_data(destination))
    return saved
