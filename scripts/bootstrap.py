#!/usr/bin/env python3
"""
Проверка окружения перед запуском (US-1.2): .env, каталоги данных, API-ключ.

Запуск из корня репозитория: ``python scripts/bootstrap.py``
Exit code: 0 — ок, 1 — есть блокирующие проблемы.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    errors: list[str] = []
    warnings: list[str] = []

    data_root = Path(os.getenv("HOME_RAG_HOME", str(root)))
    env_path = root / ".env"
    env_example = root / ".env.example"
    data_dir = data_root / "data"
    chroma_dir = data_root / "chroma_db"
    logs_dir = data_root / "logs"
    if not env_path.is_file():
        errors.append(f"Нет файла {env_path} — скопируйте из {env_example.name} в корень проекта: copy .env.example .env")
    elif not env_path.stat().st_size:
        errors.append(f"{env_path} пустой — задайте переменные (см. {env_example.name}).")

    # Загрузка настроек после смены cwd
    sys.path.insert(0, str(root))
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path if env_path.is_file() else None)
        from app.config import CHROMA_DIR, DATA_DIR, LOG_DIR, get_settings, reset_settings_cache

        data_dir = DATA_DIR
        chroma_dir = CHROMA_DIR
        logs_dir = LOG_DIR

        reset_settings_cache()
        key = (get_settings().openai_api_key or "").strip()
        if not key:
            errors.append(
                "OPENAI_API_KEY не задан — укажите в .env (или переменные окружения). "
                "Без ключа LLM/embeddings не работают."
            )
    except Exception as e:
        errors.append(f"Не удалось прочитать настройки: {e}")

    for name, path in (("data", data_dir), ("chroma_db", chroma_dir), ("logs", logs_dir)):
        if path.is_dir():
            continue
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            target = "logs/" if name == "logs" else f"{name}/"
            if name == "logs":
                warnings.append(f"Каталог {target} ({path}): {e}")
            else:
                errors.append(f"Не удалось создать каталог {target} ({path}): {e}")

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    if errors:
        print("bootstrap: проверка не пройдена:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("bootstrap: ок — .env и каталоги на месте, OPENAI_API_KEY задан.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
