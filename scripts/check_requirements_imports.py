"""Guard direct third-party imports in ``app/`` against requirements drift."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
REQUIREMENTS = ROOT / "requirements.txt"

IMPORT_TO_REQUIREMENT = {
    "aiogram": "aiogram",
    "apscheduler": "apscheduler",
    "bs4": "beautifulsoup4",
    "chromadb": "chromadb",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "fastapi": "fastapi",
    "filelock": "filelock",
    "fitz": "pymupdf",
    "genanki": "genanki",
    "httpx": "httpx",
    "llama_index": "llama-index",
    "numpy": "numpy",
    "openai": "openai",
    "opentelemetry": "opentelemetry-api",
    "pandas": "pandas",
    "plotly": "plotly",
    "pydantic": "pydantic",
    "pypdf": "pypdf",
    "qrcode": "qrcode",
    "requests": "requests",
    "speech_recognition": "SpeechRecognition",
    "streamlit": "streamlit",
    "tiktoken": "tiktoken",
    "yaml": "PyYAML",
}


def _normalize_requirement(line: str) -> str | None:
    raw = line.split("#", 1)[0].strip()
    if not raw or raw.startswith("-"):
        return None
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if separator in raw:
            raw = raw.split(separator, 1)[0]
            break
    return raw.split("[", 1)[0].strip().lower().replace("_", "-") or None


def _declared_requirements() -> set[str]:
    return {
        req
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if (req := _normalize_requirement(line))
    }


def _local_top_level_names() -> set[str]:
    return {path.stem for path in APP_DIR.rglob("*.py")} | {"app"}


def _stdlib_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", set()))
    names.update({"__future__"})
    return names


def _imported_top_levels() -> set[str]:
    imported: set[str] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".", 1)[0])
    return imported


def find_missing_requirements() -> list[str]:
    declared = _declared_requirements()
    local = _local_top_level_names()
    stdlib = _stdlib_names()
    missing: list[str] = []
    for name in sorted(_imported_top_levels()):
        if name in local or name in stdlib:
            continue
        requirement = IMPORT_TO_REQUIREMENT.get(name)
        if requirement is None and importlib.util.find_spec(name) is None:
            continue
        if requirement is None:
            continue
        normalized = requirement.lower().replace("_", "-")
        if normalized not in declared:
            missing.append(f"{name} -> {requirement}")
    return missing


def main() -> int:
    missing = find_missing_requirements()
    if missing:
        print("Direct app imports missing from requirements.txt:")
        for item in missing:
            print(f"  {item}")
        return 1
    print("requirements import guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
