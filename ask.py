import argparse
import importlib
import json
import uuid
from typing import Optional

from app.guardrails import InputGuardrailError
from app.input_validation import prepare_ask_request
def _parse_args():
    parser = argparse.ArgumentParser(description="Home RAG CLI")
    parser.add_argument(
        "--profile",
        choices=["fast", "quality"],
        help="Профиль RAG (fast или quality). Переопределяет RAG_PROFILE из окружения.",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Краткий вывод (только ответ, без списка источников).",
    )
    parser.add_argument(
        "--log",
        type=str,
        help="Путь к файлу для сохранения истории запросов/ответов в формате JSONL.",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Идентификатор multi-turn сессии (как POST /ask session_id); без флага — без persisted session.",
    )
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Сгенерировать новый session_id (UUID) на старте; игнорируется, если задан --session-id.",
    )
    parser.add_argument(
        "--query-mode",
        type=str,
        default=None,
        help="Режим запроса, например tutor (как POST /ask query_mode).",
    )
    parser.add_argument("--question", type=str, default=None, help="Вопрос для one-shot запуска без prompt ввода.")
    parser.add_argument("--folder", type=str, default=None, help="Фильтр по последней папке.")
    parser.add_argument("--folder-rel", type=str, default=None, help="Фильтр по относительному пути папки.")
    parser.add_argument("--file-name", type=str, default=None, help="Фильтр по имени файла.")
    parser.add_argument("--relative-path", type=str, default=None, help="Фильтр по относительному пути файла.")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Не читать stdin; требует --question.",
    )
    parser.add_argument(
        "--exit-after-one",
        action="store_true",
        help="Завершить интерактивный режим после первого обработанного вопроса.",
    )
    return parser.parse_args()


def _append_log(log_path: Optional[str], question: str, result: dict) -> None:
    if not log_path:
        return

    entry = {
        "question": question,
        "answer": result.get("answer"),
        "sources": result.get("sources"),
        "debug": result.get("debug"),
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    args = _parse_args()

    answer_question = importlib.import_module("app.query_service").answer_question

    # getattr: тесты и моки _parse_args могут отдавать SimpleNamespace без новых полей
    session_id = (getattr(args, "session_id", None) or "").strip() or None
    if bool(getattr(args, "new_session", False)) and not session_id:
        session_id = str(uuid.uuid4())
        print(f"Новая сессия: {session_id}\n")
    _qm = getattr(args, "query_mode", None)
    query_mode_cli = (_qm or "").strip() or None

    non_interactive = bool(getattr(args, "non_interactive", False))
    question_cli = (getattr(args, "question", None) or "").strip() or None
    if non_interactive and not question_cli:
        raise SystemExit("--non-interactive requires --question")

    def _filter_value(name: str, prompt: str) -> str | None:
        value = getattr(args, name, None)
        if value is not None:
            return value.strip() or None
        if non_interactive:
            return None
        return input(prompt).strip() or None

    folder = _filter_value("folder", "Фильтр по последней папке (Enter = без фильтра): ")
    folder_rel = _filter_value("folder_rel", "Фильтр по относительному пути папки (Enter = без фильтра): ")
    file_name = _filter_value("file_name", "Фильтр по имени файла (Enter = без фильтра): ")
    relative_path = _filter_value("relative_path", "Фильтр по относительному пути файла (Enter = без фильтра): ")

    if not non_interactive:
        print("\nRAG готов. Для выхода напиши: exit\n")

    pending_question = question_cli
    while True:
        if pending_question is not None:
            raw_question = pending_question
            pending_question = None
        elif non_interactive:
            break
        else:
            raw_question = input("Вопрос: ")
        if raw_question.strip().lower() in {"exit", "quit"}:
            break

        try:
            prepared_request = prepare_ask_request(
                type(
                    "CliAskRequest",
                    (),
                    {
                        "question": raw_question,
                        "folder": folder,
                        "folder_rel": folder_rel,
                        "file_name": file_name,
                        "relative_path": relative_path,
                        "session_id": session_id,
                        "query_mode": query_mode_cli,
                        "rag_profile": args.profile,
                    },
                )()
            )
        except InputGuardrailError as exc:
            print(f"\nОшибка вопроса [{exc.code}]: {exc}\n")
            continue

        result = answer_question(prepared_request.question, prepared_request.options)

        print("\nОтвет:\n")
        print(result.get("answer", ""))

        if not args.brief and result.get("sources"):
            print("\nИсточники:")
            for i, src in enumerate(result["sources"], start=1):
                print(
                    f"{i}. path={src.get('relative_path')} "
                    f"page={src.get('page')} "
                    f"score={src.get('score')}"
                )
        print()

        _append_log(args.log, prepared_request.question, result)

        if question_cli is not None or bool(getattr(args, "exit_after_one", False)):
            break


if __name__ == "__main__":
    main()
