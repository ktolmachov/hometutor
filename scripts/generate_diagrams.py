"""Генератор диаграмм из кода → docs/diagrams.md (mermaid).

Диаграммы, которые выводимы из исходников, не рисуются руками — они дрейфуют.
Скрипт регенерирует их детерминированно:

1. Карта HTTP API      — из ``@router.<method>("path")`` в app/routers/*.py
2. Граф слоёв          — из module-level импортов (AST) app/**, агрегировано по слоям
3. ER-схемы SQLite     — из ``CREATE TABLE`` DDL в app/*.py (+ REFERENCES → связи)
4. Фичи UI по уровням  — из FEATURES в app/ui/feature_registry.py (AST, без импорта streamlit)

Использование:
    python scripts/generate_diagrams.py            # перегенерировать docs/diagrams.md
    python scripts/generate_diagrams.py --check    # exit 1, если файл устарел (для CI/guards)

Рукописные концептуальные диаграммы (context/containers/pipeline/learning loop)
остаются в docs/architecture.md — их семантика не выводима из кода.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
OUTPUT = ROOT / "docs" / "diagrams.md"

HEADER = """\
# Диаграммы hometutor (генерируются из кода)

> **НЕ РЕДАКТИРОВАТЬ РУКАМИ.** Файл целиком генерируется скриптом
> `scripts/generate_diagrams.py` из исходников. Обновление:
> `python scripts/generate_diagrams.py`; проверка актуальности: `--check`.
> Концептуальные (рукописные) диаграммы живут в [architecture.md](architecture.md).
"""

_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_]")


def _mid(text: str) -> str:
    """Безопасный mermaid node id."""
    out = _ID_SAFE_RE.sub("_", text)
    return out if out and not out[0].isdigit() else f"n_{out}"


def _mlabel(text: str) -> str:
    """Безопасный mermaid node label (в двойных кавычках)."""
    return text.replace('"', "'").replace("{", "(").replace("}", ")")


# ── 1. Карта HTTP API ───────────────────────────────────────────────────

_ROUTE_RE = re.compile(
    r"@router\.(get|post|put|delete|patch)\(\s*f?[\"']([^\"']+)[\"']", re.S
)
_PREFIX_RE = re.compile(r"APIRouter\([^)]*prefix\s*=\s*[\"']([^\"']+)[\"']", re.S)


def collect_routes() -> dict[str, list[tuple[str, str]]]:
    """{router_module: [(METHOD, path), ...]} в порядке объявления."""
    routes: dict[str, list[tuple[str, str]]] = {}
    for path in sorted((APP_DIR / "routers").glob("*.py")):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        prefix_m = _PREFIX_RE.search(src)
        prefix = prefix_m.group(1) if prefix_m else ""
        found = [(m.group(1).upper(), prefix + m.group(2)) for m in _ROUTE_RE.finditer(src)]
        if found:
            routes[path.stem] = found
    return routes


def render_api_section(routes: dict[str, list[tuple[str, str]]]) -> str:
    total = sum(len(v) for v in routes.values())
    lines = [
        "## 1. Карта HTTP API",
        "",
        f"Всего маршрутов: **{total}** в **{len(routes)}** роутерах "
        "(источник: `app/routers/*.py`).",
        "",
        "```mermaid",
        "flowchart LR",
        '    API["FastAPI app<br/>app/api.py"]',
    ]
    for name, items in sorted(routes.items(), key=lambda kv: -len(kv[1])):
        lines.append(f'    API --> {_mid(name)}["{_mlabel(name)}<br/>{len(items)} routes"]')
    lines.append("```")
    lines.append("")
    for name in sorted(routes):
        lines.append(f"### `{name}` ({len(routes[name])})")
        lines.append("")
        lines.append("| Метод | Путь |")
        lines.append("|---|---|")
        for method, route in routes[name]:
            lines.append(f"| {method} | `{route}` |")
        lines.append("")
    return "\n".join(lines)


# ── 2. Граф зависимостей слоёв ──────────────────────────────────────────

_LAYER_ORDER = [
    "UI (Streamlit)",
    "HTTP routers",
    "API app слой",
    "Сервисы (домены)",
    "Промпты",
    "Retrieval / Index",
    "Граф знаний",
    "State (SQLite)",
    "Провайдер LLM",
    "Конфиг",
]

_LAYER_IDS = {
    "UI (Streamlit)": "ui",
    "HTTP routers": "routers",
    "API app слой": "apiapp",
    "Сервисы (домены)": "services",
    "Промпты": "prompts",
    "Retrieval / Index": "retrieval",
    "Граф знаний": "graph",
    "State (SQLite)": "state",
    "Провайдер LLM": "provider",
    "Конфиг": "config",
}


def _layer_of(module: str) -> str | None:
    """Классификация app-модуля по слою. None → вне анализа."""
    if not module.startswith("app"):
        return None
    if module.startswith("app.ui"):
        return "UI (Streamlit)"
    if module.startswith("app.routers"):
        return "HTTP routers"
    if module.startswith("app.prompts"):
        return "Промпты"
    rest = module[len("app.") :] if module != "app" else ""
    if rest == "config":
        return "Конфиг"
    if rest.startswith("provider"):
        return "Провайдер LLM"
    if rest.startswith(("user_state", "auth_db", "session_store", "metrics_db")):
        return "State (SQLite)"
    if rest.startswith(
        ("retrieval", "hybrid_retrieval", "chroma_vector_backend", "index_", "ingestion", "section_index")
    ):
        return "Retrieval / Index"
    if rest.startswith(("knowledge_graph", "graph_", "course_graph")):
        return "Граф знаний"
    if rest.startswith(("api", "middleware")):
        return "API app слой"
    return "Сервисы (домены)"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _import_targets(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module]
    return []


def collect_layer_edges() -> tuple[dict[tuple[str, str], int], list[str]]:
    """(рёбра по module-level импортам, ленивые импорты UI из backend'а file:line)."""
    edges: dict[tuple[str, str], int] = defaultdict(int)
    ui_violations: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        src_layer = _layer_of(_module_name(path))
        if src_layer is None:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:  # только module-level — соответствует инварианту гвардов
            for target in _import_targets(node):
                dst_layer = _layer_of(target)
                if dst_layer and dst_layer != src_layer:
                    edges[(src_layer, dst_layer)] += 1
        if src_layer != "UI (Streamlit)":
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for target in _import_targets(node):
                        if target.startswith("app.ui"):
                            rel = path.relative_to(ROOT).as_posix()
                            ui_violations.append(f"`{rel}:{node.lineno}` → `{target}`")
    return edges, sorted(set(ui_violations))


def render_layers_section(edges: dict[tuple[str, str], int], ui_violations: list[str]) -> str:
    lines = [
        "## 2. Граф зависимостей слоёв",
        "",
        "Агрегировано по module-level импортам `app/**` (AST). Число на ребре — количество импортов.",
        "Инвариант гвардов: UI не импортируется backend'ом; провайдер и конфиг — стоки.",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    used = {layer for pair in edges for layer in pair}
    for layer in _LAYER_ORDER:
        if layer in used:
            lines.append(f'    {_LAYER_IDS[layer]}["{_mlabel(layer)}"]')
    for (src, dst), count in sorted(edges.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {_LAYER_IDS[src]} -->|{count}| {_LAYER_IDS[dst]}")
    lines.append("```")
    lines.append("")
    lines.append("### Импорты UI из backend-слоёв (включая ленивые)")
    lines.append("")
    if ui_violations:
        lines.append("⚠️ Нарушения границы «backend не знает про UI»:")
        lines.append("")
        for item in ui_violations:
            lines.append(f"- {item}")
    else:
        lines.append("Нарушений нет ✅")
    return "\n".join(lines)


# ── 3. ER-схемы SQLite ──────────────────────────────────────────────────

_CREATE_TABLE_RE = re.compile(
    r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\((.*?)\)\s*(?:;|\"\"\")", re.S | re.I
)
_REFERENCES_RE = re.compile(r"REFERENCES\s+(\w+)", re.I)
_CONSTRAINT_STARTS = ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")

_DB_LABELS = {
    "auth_db": "data/auth.db",
    "user_state_db": "data/user_state.db (или data/users/<user_id>/…)",
}


def _split_top_level_columns(body: str) -> list[str]:
    """Разбить тело CREATE TABLE по запятым верхнего уровня (вне скобок)."""
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def collect_er_models() -> dict[str, list[dict]]:
    """{module_stem: [{name, columns: [(type, name, flags)], refs: [table]}]}"""
    models: dict[str, list[dict]] = {}
    for path in sorted(APP_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        tables = []
        for m in _CREATE_TABLE_RE.finditer(src):
            name, body = m.group(1), m.group(2)
            columns: list[tuple[str, str, str]] = []
            refs: list[tuple[str, str]] = []
            for col in _split_top_level_columns(body):
                first = col.split()[0].upper() if col.split() else ""
                if first in _CONSTRAINT_STARTS:
                    for ref in _REFERENCES_RE.findall(col):
                        refs.append((ref, ""))
                    continue
                tokens = col.split()
                col_name = tokens[0]
                col_type = tokens[1].upper() if len(tokens) > 1 else "TEXT"
                if "(" in col_type:
                    col_type = col_type.split("(")[0]
                flags = "PK" if "PRIMARY KEY" in col.upper() else ""
                columns.append((col_type, col_name, flags))
                for ref in _REFERENCES_RE.findall(col):
                    refs.append((ref, col_name))
            tables.append({"name": name, "columns": columns, "refs": refs})
        if tables:
            models[path.stem] = tables
    return models


def render_er_section(models: dict[str, list[dict]]) -> str:
    lines = [
        "## 3. Схемы хранилищ (SQLite)",
        "",
        "Из `CREATE TABLE` DDL в `app/*.py`. Связи — по `REFERENCES`.",
        "",
    ]
    for stem in sorted(models):
        db_label = _DB_LABELS.get(stem, f"см. `app/{stem}.py`")
        lines.append(f"### `{stem}.py` — {db_label} ({len(models[stem])} табл.)")
        lines.append("")
        lines.append("```mermaid")
        lines.append("erDiagram")
        for table in models[stem]:
            lines.append(f"    {table['name']} {{")
            for col_type, col_name, flags in table["columns"]:
                suffix = f" {flags}" if flags else ""
                lines.append(f"        {col_type} {col_name}{suffix}")
            lines.append("    }")
        for table in models[stem]:
            for ref_table, via in table["refs"]:
                label = via or "fk"
                lines.append(f'    {ref_table} ||--o{{ {table["name"]} : "{label}"')
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ── 4. Фичи UI по уровням опыта ─────────────────────────────────────────


def collect_features() -> list[tuple[str, str, int, str]]:
    """[(id, title, tier, surface)] из FEATURES в feature_registry.py (AST)."""
    path = APP_DIR / "ui" / "feature_registry.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    features: list[tuple[str, str, int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "FeatureSpec"):
            continue
        args = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if len(args) >= 4:
            features.append((str(args[0]), str(args[1]), int(args[2]), str(args[3])))
    return features


def render_features_section(features: list[tuple[str, str, int, str]]) -> str:
    lines = [
        "## 4. Фичи UI по уровням опыта",
        "",
        f"Всего фич: **{len(features)}** (источник: `app/ui/feature_registry.py::FEATURES`).",
        "",
        "```mermaid",
        "flowchart TB",
    ]
    by_tier: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    for fid, title, tier, surface in features:
        by_tier[tier].append((fid, title, surface))
    for tier in sorted(by_tier):
        lines.append(f'    subgraph T{tier}["Уровень {tier}"]')
        for fid, title, surface in by_tier[tier]:
            lines.append(f'        {_mid(fid)}["{_mlabel(title)}<br/><i>{surface}</i>"]')
        lines.append("    end")
    tiers = sorted(by_tier)
    for a, b in zip(tiers, tiers[1:]):
        lines.append(f"    T{a} --> T{b}")
    lines.append("```")
    return "\n".join(lines)


# ── Сборка / режимы ─────────────────────────────────────────────────────


def generate() -> str:
    layer_edges, ui_violations = collect_layer_edges()
    sections = [
        HEADER,
        render_api_section(collect_routes()),
        render_layers_section(layer_edges, ui_violations),
        render_er_section(collect_er_models()),
        render_features_section(collect_features()),
    ]
    return "\n\n".join(s.rstrip() for s in sections) + "\n"


def main(argv: list[str]) -> int:
    content = generate()
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print(f"diagrams guard failed: {OUTPUT.relative_to(ROOT)} устарел — "
                  "запустите python scripts/generate_diagrams.py")
            return 1
        print("diagrams guard passed")
        return 0
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"written: {OUTPUT.relative_to(ROOT)} ({len(content.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
