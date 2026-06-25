"""Guard known architecture-review dead-module candidates.

The review intentionally scoped this guard to backend modules already flagged
as orphan candidates. Remaining unreferenced modules must carry an explicit
keep reason here so future cleanups can distinguish tools from accidental
dead code.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

CANDIDATES = {
    "app.log_masking_policy",
    "app.smart_konspekt",
    "app.router_eval",
    "app.eval_uplift",
    "app.eval_ragas_backend",
    "app.eval_retrieval_comparison",
    "app.ssr_pregeneration",
    "app.ssr_weekly_planner",
    "app.ssr_graph_routing",
    "app.ssr_llm_profile_summary",
    "app.session_analytics_parser",
    "app.adversarial_test_runner",
    "app.answer_parser",
    "app.tutor_context_parser",
    "app.prompt_smoke_checks",
    "app.langfuse_dataset",
    "app.index_backup",
}

KEEP_REASONS = {
    "app.smart_konspekt": "manual smart-konspekt generation utility",
    "app.router_eval": "offline router eval harness",
    "app.eval_uplift": "offline retrieval uplift analysis",
    "app.eval_ragas_backend": "optional RAGAS backend integration",
    "app.eval_retrieval_comparison": "offline retrieval comparison tool",
    "app.ssr_pregeneration": "future async SSR pre-generation hook",
    "app.ssr_weekly_planner": "weekly SSR planning domain module",
    "app.ssr_graph_routing": "SSR graph-routing experiment module",
    "app.ssr_llm_profile_summary": "SSR profiling summary utility",
    "app.session_analytics_parser": "session analytics parser for exported traces",
    "app.adversarial_test_runner": "manual adversarial regression harness",
    "app.answer_parser": "typed answer parsing helper kept for API evolution",
    "app.tutor_context_parser": "typed tutor context parser kept for API evolution",
    "app.prompt_smoke_checks": "manual prompt smoke-check utility",
    "app.langfuse_dataset": "optional Langfuse dataset integration",
    "app.index_backup": "index lifecycle backup/restore owner named in conventions",
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _import_refs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            refs.add(node.module)
            if node.module == "app":
                for alias in node.names:
                    refs.add(f"app.{alias.name}")
    return refs


def _all_import_refs() -> dict[str, set[str]]:
    roots = [ROOT / "app", ROOT / "tests", ROOT / "scripts"]
    top_level = [ROOT / "main.py", ROOT / "ingest.py", ROOT / "telegram_bot.py"]
    refs_by_file: dict[str, set[str]] = {}
    for root in roots:
        for path in root.rglob("*.py"):
            refs_by_file[str(path)] = _import_refs(path)
    for path in top_level:
        if path.exists():
            refs_by_file[str(path)] = _import_refs(path)
    return refs_by_file


def _is_referenced(module: str, refs_by_file: dict[str, set[str]]) -> bool:
    owner = str(ROOT / Path(*module.split("."))).replace(".py", "")
    for path, refs in refs_by_file.items():
        current_module = _module_name(Path(path)) if path.startswith(str(APP_DIR)) else ""
        if current_module == module:
            continue
        if module in refs:
            return True
        if any(ref.startswith(f"{module}.") for ref in refs):
            return True
        if any(ref != "app" and module.startswith(f"{ref}.") for ref in refs):
            return True
    return False


def find_unannotated_orphans() -> list[str]:
    refs_by_file = _all_import_refs()
    unannotated: list[str] = []
    for module in sorted(CANDIDATES):
        path = ROOT / Path(*module.split(".")).with_suffix(".py")
        if not path.exists():
            continue
        if _is_referenced(module, refs_by_file):
            continue
        if module not in KEEP_REASONS:
            unannotated.append(module)
    return unannotated


def main() -> int:
    unannotated = find_unannotated_orphans()
    if unannotated:
        print("Dead-module candidates need deletion, wiring, or KEEP_REASONS:")
        for module in unannotated:
            print(f"  {module}")
        return 1
    print("dead module guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
