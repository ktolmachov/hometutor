from dataclasses import dataclass
from typing import Any

from fastapi.exceptions import RequestValidationError

from app.config import KNOWN_RAG_PROFILES
from app.guardrails import InputGuardrailError, detect_prompt_injection, validate_question
from app.models import QueryOptions


@dataclass(frozen=True)
class ValidatedAskRequest:
    question: str
    options: QueryOptions


def _normalize_optional_filter(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


_HOMEWORK_LEVELS = frozenset({"hint", "plan", "error_review", "full_solution"})

_MAX_TUTOR_GOAL_STR = 512
_MAX_LLM_FIELD_CHARS = 2000


def _field_code(field_name: str, suffix: str) -> str:
    field = "".join(ch if ch.isalnum() else "_" for ch in field_name.strip().lower())
    return f"{field or 'field'}_{suffix}"


def validate_llm_input_text(
    value: Any,
    *,
    field_name: str,
    required: bool = False,
    max_chars: int = _MAX_LLM_FIELD_CHARS,
) -> str | None:
    """Validate non-/ask text before it can be interpolated into an LLM prompt."""
    if value is None:
        if required:
            raise InputGuardrailError(f"{field_name} is required", _field_code(field_name, "required"))
        return None

    text = str(value).strip()
    if not text:
        if required:
            raise InputGuardrailError(f"{field_name} is empty", _field_code(field_name, "empty"))
        return None

    if len(text) > max_chars:
        raise InputGuardrailError(
            f"{field_name} is too long (max {max_chars} characters)",
            _field_code(field_name, "too_long"),
        )

    injection = detect_prompt_injection(text)
    if injection.triggered:
        raise InputGuardrailError(
            injection.detail or "Input rejected by guardrails",
            injection.code or "input_rejected",
        )

    return text


def validate_llm_input_list(
    values: list[str] | None,
    *,
    field_name: str,
    max_items: int = 50,
    max_chars: int = _MAX_LLM_FIELD_CHARS,
) -> list[str] | None:
    if values is None:
        return None
    if len(values) > max_items:
        raise InputGuardrailError(
            f"{field_name} has too many items (max {max_items})",
            _field_code(field_name, "too_many"),
        )
    out: list[str] = []
    for idx, value in enumerate(values):
        validated = validate_llm_input_text(
            value,
            field_name=f"{field_name}[{idx}]",
            required=False,
            max_chars=max_chars,
        )
        if validated is not None:
            out.append(validated)
    return out


def _normalize_tutor_goal_str(value: Any) -> str | None:
    s = _normalize_optional_filter(value)
    if s is None:
        return None
    if len(s) > _MAX_TUTOR_GOAL_STR:
        return s[:_MAX_TUTOR_GOAL_STR]
    return s


def _normalize_tutor_goal_time_budget_min(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 240:
        return None
    return n


def _normalize_homework_level(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    return s if s in _HOMEWORK_LEVELS else None


def _normalize_rag_profile(value: Any) -> str | None:
    if value is None:
        return None
    profile = str(value).strip().lower()
    return profile if profile in KNOWN_RAG_PROFILES else None


def prepare_ask_request(request: Any) -> ValidatedAskRequest:
    hl = _normalize_homework_level(getattr(request, "homework_level", None))
    homework_mode = bool(getattr(request, "homework_mode", False))
    assistance = _normalize_optional_filter(getattr(request, "assistance_level", None))

    if hl:
        homework_mode = True
        assistance = hl
    elif homework_mode and not assistance:
        assistance = "hint"

    return ValidatedAskRequest(
        question=validate_question(getattr(request, "question", None)),
        options=QueryOptions(
            folder=_normalize_optional_filter(getattr(request, "folder", None)),
            folder_rel=_normalize_optional_filter(getattr(request, "folder_rel", None)),
            file_name=_normalize_optional_filter(getattr(request, "file_name", None)),
            relative_path=_normalize_optional_filter(getattr(request, "relative_path", None)),
            topic=_normalize_optional_filter(getattr(request, "topic", None)),
            homework_mode=homework_mode,
            assistance_level=assistance,
            study_mode=bool(getattr(request, "study_mode", False)),
            followup_context=_normalize_optional_filter(getattr(request, "followup_context", None)),
            session_id=_normalize_optional_filter(getattr(request, "session_id", None)),
            query_mode=_normalize_optional_filter(getattr(request, "query_mode", None)),
            quiz_learning_mode=_normalize_optional_filter(getattr(request, "quiz_learning_mode", None)),
            tutor_goal_subtopic=_normalize_tutor_goal_str(getattr(request, "tutor_goal_subtopic", None)),
            tutor_goal_target_level=_normalize_tutor_goal_str(getattr(request, "tutor_goal_target_level", None)),
            tutor_goal_desired_outcome=_normalize_tutor_goal_str(
                getattr(request, "tutor_goal_desired_outcome", None)
            ),
            tutor_goal_time_budget_min=_normalize_tutor_goal_time_budget_min(
                getattr(request, "tutor_goal_time_budget_min", None)
            ),
            rag_profile=_normalize_rag_profile(getattr(request, "rag_profile", None)),
        ),
    )


def build_error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def map_request_validation_error(exc: RequestValidationError) -> tuple[int, dict[str, str]]:
    errors = exc.errors()
    if not errors:
        return 400, build_error_detail("invalid_request", "Request body is invalid")

    first_error = errors[0]
    error_type = first_error.get("type", "")
    loc = tuple(first_error.get("loc", ()))

    if "question" in loc and error_type == "missing":
        return 400, build_error_detail("question_required", "Question is required")

    if "question" in loc and error_type.startswith("string_"):
        return 400, build_error_detail("question_invalid_type", "Question must be a string")

    if error_type == "json_invalid":
        return 400, build_error_detail("invalid_json", "Request body must be valid JSON")

    if "profile" in loc:
        valid = ", ".join(sorted(KNOWN_RAG_PROFILES))
        return 400, build_error_detail("invalid_profile", f"Unknown RAG profile. Valid profiles: {valid}")

    return 400, build_error_detail("invalid_request", "Request body is invalid")
