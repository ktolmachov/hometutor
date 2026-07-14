"""Architecture regression guards run in CI (evolutionary analysis #12, A1).

The four `scripts/check_*` guards encode the framework boundaries as code, but
before this test they were wired to nothing and drifted red for ~225 commits.
This parametrized test wires the four architecture guards into the pytest cycle
(and thus every CI run on push/PR). Each guard's `main()` must return 0.
If a guard starts failing, the CI job is red on the offending commit — no
violation lives longer than one commit. The guards are also runnable standalone
via `scripts/arch_regression_guards.py`.

See `doc/next/architecture_guards_plan.md` (wave-arch-law-power, A1) and the
guard aggregator `scripts/arch_regression_guards.py`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ARCH_GUARDS = (
    "scripts.check_config_access",
    "scripts.check_dead_modules",
    "scripts.check_requirements_imports",
    "scripts.check_size_budget",
)


@pytest.mark.parametrize("module_name", _ARCH_GUARDS)
def test_arch_guard_passes(module_name: str) -> None:
    module = importlib.import_module(module_name)
    rc = int(module.main())
    assert rc == 0, f"{module_name} guard failed (rc={rc}); see stdout above"


def test_arch_guards_cover_same_set_as_aggregator() -> None:
    aggregator = importlib.import_module("scripts.arch_regression_guards")
    assert set(aggregator.GUARDS) == set(_ARCH_GUARDS)
