"""Run architecture regression guards."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GUARDS = (
    "scripts.check_config_access",
    "scripts.check_dead_modules",
    "scripts.check_requirements_imports",
)


def main() -> int:
    failed = False
    for module_name in GUARDS:
        module = importlib.import_module(module_name)
        rc = int(module.main())
        failed = failed or rc != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
