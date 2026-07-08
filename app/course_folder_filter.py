"""Course-folder visibility rules shared by UI and course cache."""

from __future__ import annotations

_TECHNICAL_COURSE_FOLDER_PREFIXES = frozenset(("_", "test-", "tmp", "temp"))
_TECHNICAL_COURSE_FOLDER_NAMES = frozenset({
    ".cache",
    ".chroma",
    ".git",
    "__pycache__",
    "cache",
    "chroma_db",
    "graph_generations",
    "logs",
    "tmp",
})


def is_user_course_folder_rel(folder_rel: str) -> bool:
    """Return False for service/test folders that must not be shown as courses."""
    normalized = str(folder_rel or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return False
    first = normalized.split("/", 1)[0].strip().lower()
    if not first:
        return False
    if first in _TECHNICAL_COURSE_FOLDER_NAMES:
        return False
    return not any(first.startswith(prefix) for prefix in _TECHNICAL_COURSE_FOLDER_PREFIXES)


def is_user_source_path(path: str) -> bool:
    """Return False for indexed service/test source paths that should not feed course UX or graph scope."""
    return is_user_course_folder_rel(path)
