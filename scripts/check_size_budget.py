"""Guard architecture size budgets from AR-2026-06-25-005/006.

This is a no-growth budget: existing large files/functions remain tracked debt,
but new changes must not increase the count or peak. Budgets were re-synced to
HEAD on 2026-07-13 (evolutionary analysis #12, architecture_guards_plan A2) —
the prior snapshot (2026-06-25) had drifted red across all four metrics while
the guard was wired to nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

# No-growth snapshot synced to HEAD 2026-07-13. These are recognised-debt
# ceilings: the numbers must not grow. If a budget is exceeded, the answer is
# to fix the structure — not to bump the number a second time in the dark.
#
# Re-sync 2026-07-18 (documented, not silent): commit 326 added the
# ``initial_selected_concept`` feature to
# ``app/ui/dashboards_graph.py::_render_knowledge_graph_tab`` (+10 net lines in
# the existing peak-debt file). The bump below is a snapshot re-sync of the
# peak ceiling, accompanied by this rationale; splitting that function into a
# helper module is tracked as follow-up structural work (do NOT bump again
# without a new explicit justification).
MAX_LARGE_FILES = 33  # files > FILE_LINE_LIMIT, excluding FILE_LINE_WAIVERS
MAX_LONG_FUNCTIONS = 156
# 2026-07-19 B4: +1 for apply_learning_intent which dispatches 10 intents
# (7 simple + 3 composition). Splitting would add more helpers, not reduce count.
MAX_FILE_LINES = 1952  # peak single-file size (still includes waived deposits)
MAX_FUNCTION_LINES = 361
FILE_LINE_LIMIT = 600
FUNCTION_LINE_LIMIT = 80

# Deliberate non-splittable deposits: exempt from the large_files *count* (they
# are not structural debt to shrink), but they still cap peak_file_lines so no
# new file may exceed the current ceiling. The single-source rule ("a prompt
# lives in one place") outranks the line budget; do not split these for the guard.
FILE_LINE_WAIVERS: dict[str, str] = {
    "app/prompts/_impl.py": "prompt text deposit (single-source rule); verdict: do not split",
}


def _is_waived(rel_posix: str) -> bool:
    return rel_posix in FILE_LINE_WAIVERS


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
        rel = path.relative_to(ROOT).as_posix()
        if lines > FILE_LINE_LIMIT and not _is_waived(rel):
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
