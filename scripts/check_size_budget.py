"""Guard architecture size budgets from AR-2026-06-25-005/006.

This is a no-growth budget: existing large files/functions remain tracked debt,
but new changes must not increase the count or peak.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

MAX_LARGE_FILES = 24
MAX_LONG_FUNCTIONS = 138
MAX_FILE_LINES = 1651
MAX_FUNCTION_LINES = 338
FILE_LINE_LIMIT = 600
FUNCTION_LINE_LIMIT = 80


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def _function_span(node: ast.AST) -> int:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start)
    return max(0, end - start + 1)


def _size_snapshot() -> dict[str, int]:
    large_files = 0
    long_functions = 0
    peak_file_lines = 0
    peak_function_lines = 0
    for path in sorted(APP_DIR.rglob("*.py")):
        lines = len(_read_lines(path))
        peak_file_lines = max(peak_file_lines, lines)
        if lines > FILE_LINE_LIMIT:
            large_files += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = _function_span(node)
                peak_function_lines = max(peak_function_lines, span)
                if span > FUNCTION_LINE_LIMIT:
                    long_functions += 1
    return {
        "large_files": large_files,
        "long_functions": long_functions,
        "peak_file_lines": peak_file_lines,
        "peak_function_lines": peak_function_lines,
    }


def main() -> int:
    snapshot = _size_snapshot()
    limits = {
        "large_files": MAX_LARGE_FILES,
        "long_functions": MAX_LONG_FUNCTIONS,
        "peak_file_lines": MAX_FILE_LINES,
        "peak_function_lines": MAX_FUNCTION_LINES,
    }
    failures = [
        f"{key}={value} exceeds budget {limits[key]}"
        for key, value in snapshot.items()
        if value > limits[key]
    ]
    if failures:
        print("Size budget guard failed:")
        for item in failures:
            print(f"  {item}")
        return 1
    print(
        "size budget guard passed "
        f"(large_files={snapshot['large_files']}, "
        f"long_functions={snapshot['long_functions']}, "
        f"peak_file_lines={snapshot['peak_file_lines']}, "
        f"peak_function_lines={snapshot['peak_function_lines']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
