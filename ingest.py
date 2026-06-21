"""CLI: полная индексация ``data/`` (см. ``app.ingestion.build_index``)."""
from __future__ import annotations

import argparse
import logging

from app.config import PROJECT_ROOT_PATH
from app.ingestion import build_index

# Импорт ``app.ingestion`` поднимает ``setup_logging()`` в ``app.ingestion``.
logger = logging.getLogger(PROJECT_ROOT_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Индексация документов из data/ в Chroma (прогресс в stdout: строки INGEST_PROGRESS).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Сбросить активный индекс и пересобрать коллекции (жёсткий rebuild).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Не спрашивать подтверждение интерактивно (для CI/скриптов).",
    )
    args = parser.parse_args()
    reset = bool(args.reset)
    logger.info(
        "ingest_cli | flags_reset=%s flags_yes_non_interactive=%s",
        bool(args.reset),
        bool(args.yes),
    )
    if not args.yes:
        answer = input("Сбросить старый индекс? (y/n): ").strip().lower()
        reset = answer == "y"
    logger.info("ingest_cli | invoking_build_index | reset=%s", reset)
    build_index(reset=reset)


if __name__ == "__main__":
    main()
