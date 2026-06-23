#!/usr/bin/env python3
"""
Полное удаление локальных производственных артефактов hometutor: векторный индекс
(Chroma), реестры поколений, пользовательское состояние SQLite, JSONL-логи
(history/feedback/metrics), каталог cost_logs и производные графовые кеши.

Не удаляет исходные документы corpus в data/* (кроме concept_graph.json,
graph_generations/, cache рядом с user_state.db).

Требуется явный токен подтверждения (см. --confirm-token). Остановите API/бот
перед запуском.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Публичный контракт: точное совпадение строки (gate против случайного запуска).
CONFIRM_TOKEN = "DELETE-ALL-LOCAL-HOME-RAG-DATA"


def _rmtree(path: Path) -> bool:
    import shutil

    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def _unlink(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


def is_path_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def plan_deletion() -> dict[str, Any]:
    """Возвращает канонические пути удаления (для тестов и verify)."""
    from app.config import CHROMA_DIR, DATA_DIR, LOG_DIR, get_settings

    s = get_settings()
    chroma = CHROMA_DIR.resolve()
    user_db = Path(s.user_state_db).resolve()
    cache_dir = (user_db.parent / "cache").resolve()
    cost_dir = Path(s.llm_cost_log_dir).resolve()
    graph_gen = (DATA_DIR / "graph_generations").resolve()
    concept = (DATA_DIR / "concept_graph.json").resolve()

    ssr_profiles = (LOG_DIR / "ssr_llm_profiles").resolve()
    ssr_feedback = (LOG_DIR / "ssr_feedback").resolve()
    dirs = [chroma, cost_dir, graph_gen, cache_dir, ssr_profiles, ssr_feedback]
    files = [
        Path(s.index_meta_path).resolve(),
        Path(s.index_registry_path).resolve(),
        Path(s.index_registry_lock_path).resolve(),
        Path(s.metrics_store_path).resolve(),
        Path(s.metrics_dashboard_db_path).resolve(),
        Path(s.feedback_path).resolve(),
        Path(s.history_path).resolve(),
        Path(s.faq_memory_path).resolve(),
        concept,
        user_db,
    ]

    # active_index.json лежит внутри chroma — не дублируем отдельным unlink.
    files = [f for f in files if not is_path_under(f, chroma)]
    files = [f for f in files if f.resolve() != cache_dir.resolve()]
    # locks/metadata могли бы попасть под chroma при нестандартных путях
    uniq_files: list[Path] = []
    seen: set[Path] = set()
    for f in files:
        rf = f.resolve()
        if rf not in seen:
            seen.add(rf)
            uniq_files.append(f)

    uniq_dirs: list[Path] = []
    seen_d: set[Path] = set()
    for d in dirs:
        rd = d.resolve()
        if rd not in seen_d:
            seen_d.add(rd)
            uniq_dirs.append(d)

    return {
        "dirs": uniq_dirs,
        "files": uniq_files,
    }


def verify_deletion_complete() -> tuple[bool, list[str]]:
    """True, если ни один из запланированных путей не существует."""
    plan = plan_deletion()
    remaining: list[str] = []
    for d in plan["dirs"]:
        if d.exists():
            remaining.append(str(d))
    for f in plan["files"]:
        if f.exists():
            remaining.append(str(f))
    return not remaining, sorted(remaining)


def delete_all_local_data(*, confirm_token: str | None) -> dict[str, Any]:
    if confirm_token != CONFIRM_TOKEN:
        raise ValueError(
            f"Подтверждение отклонено: ожидается ровно {CONFIRM_TOKEN!r} "
            f"(передайте через --confirm-token)."
        )

    plan = plan_deletion()
    removed_dirs: list[str] = []
    removed_files: list[str] = []

    for d in plan["dirs"]:
        if _rmtree(d):
            removed_dirs.append(str(d))

    for f in plan["files"]:
        if _unlink(f):
            removed_files.append(str(f))

    ok, left = verify_deletion_complete()
    return {
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "verify_ok": ok,
        "remaining": left,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Удаление локальных индексов, user-state и телеметрии hometutor",
    )
    parser.add_argument(
        "--confirm-token",
        default=None,
        help=f"Обязательно для удаления: точное значение {CONFIRM_TOKEN!r}",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Только проверить, что целевые пути отсутствуют (без удаления).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывести результат как JSON (для скриптов).",
    )
    args = parser.parse_args(argv)

    if args.verify_only:
        ok, left = verify_deletion_complete()
        payload = {"verify_ok": ok, "remaining": left}
        if args.json:
            import json

            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if ok:
                print("OK: локальные цели удаления отсутствуют.")
            else:
                print("FAIL: остались пути:")
                for p in left:
                    print(f"  {p}")
        return 0 if ok else 2

    if not args.confirm_token:
        parser.error(f"Укажите --confirm-token {CONFIRM_TOKEN!r} или --verify-only")

    try:
        result = delete_all_local_data(confirm_token=args.confirm_token)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Удалено каталогов: {len(result['removed_dirs'])}")
        print(f"Удалено файлов: {len(result['removed_files'])}")
        if result["verify_ok"]:
            print("Проверка полноты: OK")
        else:
            print("Проверка полноты: FAIL — остатки:")
            for p in result["remaining"]:
                print(f"  {p}")

    return 0 if result["verify_ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
