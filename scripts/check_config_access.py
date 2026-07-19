"""Guard raw env access in application modules.

Runtime settings must be declared in ``app.config.Settings`` or
``RetrievalSettings`` and consumed via ``get_settings()`` /
``get_retrieval_settings()``. Diagnostic-only modules are explicitly allowed.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
ALLOWED = {
    APP_DIR / "config.py",
    APP_DIR / "ingestion_env_diag.py",
}


def _is_os_env_access(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "getenv":
            return isinstance(func.value, ast.Name) and func.value.id == "os"
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return isinstance(node.value, ast.Name) and node.value.id == "os"
    return False


def find_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path in ALLOWED:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            violations.append(f"{path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if _is_os_env_access(node):
                lineno = getattr(node, "lineno", 0)
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: raw os env access")
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print("Raw env access must go through app.config:")
        for item in violations:
            print(f"  {item}")
        return 1
    print("config access guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
