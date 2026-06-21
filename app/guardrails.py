import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+message\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(the\s+)?(hidden\s+)?prompt\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(all\s+)?instructions\b", re.IGNORECASE),
    re.compile(r"\bигнориру(й|йте)\s+(все\s+)?(предыдущие|прошлые|вышеуказанные)\s+(инструкции|указания|правила)\b", re.IGNORECASE),
    re.compile(r"\bзабуд(ь|ьте)\s+(все\s+)?(инструкции|правила|ограничения)\b", re.IGNORECASE),
    re.compile(r"\bсистемн(ый|ого)\s+промпт\b", re.IGNORECASE),
    re.compile(r"\bпокажи\s+(системн(ый|ого)\s+промпт|скрытый\s+промпт)\b", re.IGNORECASE),
    re.compile(r"\bраскрой\s+(системн(ый|ого)\s+промпт|скрытый\s+промпт)\b", re.IGNORECASE),
    re.compile(r"\bсообщени[ея]\s+разработчик[а-я]*\b", re.IGNORECASE),
    re.compile(r"\bигнориру(й|йте).{0,40}\b(previous|prior|system|developer)\b", re.IGNORECASE),
    re.compile(r"\b(pokazhi|raskroi|ignorirui).{0,40}\b(system\s+prompt|developer\s+message)\b", re.IGNORECASE),
)

OUTPUT_LEAK_PATTERNS = (
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+message\b", re.IGNORECASE),
    re.compile(r"\bapi[_ -]?key\b", re.IGNORECASE),
    re.compile(r"\bsecret(s)?\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bпарол[ьяеию]\b", re.IGNORECASE),
    re.compile(r"\bсекрет(ы|ный|ная|ные)?\b", re.IGNORECASE),
    re.compile(r"\bтокен(ы|ом|а|у)?\b", re.IGNORECASE),
    re.compile(r"\bключ(и|а|ом|у)?\s+(api|доступа|доступ)\b", re.IGNORECASE),
    re.compile(r"\bsk-[a-z0-9]{8,}\b", re.IGNORECASE),
)

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\-\(\)\s]{8,}\d)")
OPENAI_KEY_PATTERN = re.compile(r"\bsk-[a-z0-9]{8,}\b", re.IGNORECASE)


def _phone_match_is_likely_datetime_or_date_prefix(match: re.Match) -> bool:
    """Снимает ложные срабатывания ``PHONE_PATTERN`` на ISO-датах и фрагментах datetime."""
    frag = match.group(0)
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", frag))
GENERIC_API_KEY_PATTERN = re.compile(r"\b(?:api[_ -]?key|token|secret|password)\b\s*[:=]?\s*([A-Za-z0-9_\-]{6,})", re.IGNORECASE)

SAFE_FALLBACK_MESSAGES = {
    "empty_answer": "Не удалось сформировать надежный ответ по доступному контексту. Попробуйте уточнить вопрос.",
    "missing_sources": "Я не могу надежно ответить без подтверждающих источников. Уточните вопрос или переиндексируйте данные.",
    "grounded_abstain": (
        "Я не могу подтвердить ответ по найденным источникам. Уточните вопрос или проверьте материалы."
    ),
    "suspicious_output": "Ответ был скрыт, потому что выглядел как попытка раскрыть внутренние инструкции или секреты.",
    "pii_detected": "Ответ был скрыт, потому что мог содержать чувствительные персональные данные.",
}

FALLBACK_PHRASES = (
    "не удалось сформировать надежный ответ",
    "не могу надежно ответить без подтверждающих источников",
    "ответ был скрыт",
    "недостаточно данных",
    "не хватает данных",
)


class GuardrailError(ValueError):
    """Base error for input/output guardrail violations."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class InputGuardrailError(GuardrailError):
    """Raised when user input violates request guardrails."""


class OutputGuardrailError(GuardrailError):
    """Raised when model output violates response guardrails."""


@dataclass(frozen=True)
class GuardrailCheckResult:
    triggered: bool
    code: str | None = None
    detail: str | None = None


def _normalize_text(value: Any) -> str:
    text = str(value or "")
    # Unicode нормализация и базовая очистка управления/zero-width
    text = unicodedata.normalize("NFKC", text)
    # Удаляем zero-width и невидимые разделители, оставляя обычные пробелы/переводы строк
    text = "".join(
        ch
        for ch in text
        if not unicodedata.category(ch).startswith("C") or ch in ("\n", "\r", "\t")
    )
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_for_detection(value: Any) -> tuple[str, str]:
    """
    Нормализация для pattern-детекции.

    Возвращает кортеж:
    - base: результат _normalize_text (для русских/оригинальных паттернов)
    - ascii_like: версия с лёгким гомоглиф-маппингом (кириллица -> латиница)
      для устойчивости англоязычных паттернов к Unicode-обфускации.
    """
    base = _normalize_text(value)
    if not base:
        return base, base

    homoglyph_map = {
        # Кириллица → латиница для критичных букв (используется ТОЛЬКО во второй строке)
        "А": "A",
        "а": "a",
        "В": "B",
        "Е": "E",
        "е": "e",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "о": "o",
        "Р": "P",
        "р": "p",
        "С": "C",
        "с": "c",
        "Т": "T",
        "У": "Y",
        "у": "y",
        "Х": "X",
        "х": "x",
    }

    ascii_like = "".join(homoglyph_map.get(ch, ch) for ch in base)
    return base, ascii_like


def _settings():
    return get_settings()


def _looks_like_safe_fallback_message(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in FALLBACK_PHRASES)


def is_abstain_phrase(answer: str) -> bool:
    """True when answer text matches known abstain/fallback phrases."""
    return _looks_like_safe_fallback_message(answer)


def redact_sensitive_text(value: Any) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return normalized

    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", normalized)
    redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    redacted = OPENAI_KEY_PATTERN.sub("[REDACTED_API_KEY]", redacted)
    redacted = GENERIC_API_KEY_PATTERN.sub(lambda match: match.group(0).replace(match.group(1), "[REDACTED_SECRET]"), redacted)
    return redacted


def detect_prompt_injection(question: Any) -> GuardrailCheckResult:
    base, ascii_like = _normalize_for_detection(question)
    settings = _settings()

    if not settings.guardrails_block_on_prompt_injection or not base:
        return GuardrailCheckResult(triggered=False)

    for pattern in INJECTION_PATTERNS:
        # Сначала проверяем нормализованный текст как есть (русские паттерны и т.п.)
        if pattern.search(base):
            return GuardrailCheckResult(
                triggered=True,
                code="prompt_injection_detected",
                detail="Question looks like a prompt injection attempt",
            )
        # Затем — версию с гомоглиф-маппингом для англоязычных паттернов
        if pattern.search(ascii_like):
            return GuardrailCheckResult(
                triggered=True,
                code="prompt_injection_detected",
                detail="Question looks like a prompt injection attempt",
            )

    return GuardrailCheckResult(triggered=False)


def validate_question(question: Any) -> str:
    normalized = _normalize_text(question)
    settings = _settings()

    if question is None:
        raise InputGuardrailError("Question is required", "question_required")

    if not normalized:
        raise InputGuardrailError("Question must not be empty", "question_empty")

    if len(normalized) > settings.guardrails_max_question_length:
        raise InputGuardrailError(
            f"Question is too long (max {settings.guardrails_max_question_length} characters)",
            "question_too_long",
        )

    injection_check = detect_prompt_injection(normalized)
    if injection_check.triggered:
        raise InputGuardrailError(
            injection_check.detail or "Question looks like a prompt injection attempt",
            injection_check.code or "prompt_injection_detected",
        )

    return normalized


def detect_output_violation(answer: Any, sources: list[dict[str, Any]] | None) -> GuardrailCheckResult:
    # Для output-guardrails достаточно базовой нормализации; важно не искажать текст
    # относительно ожидаемых фраз fallback-а и паттернов утечек.
    normalized = _normalize_text(answer)
    settings = _settings()

    if not normalized:
        return GuardrailCheckResult(
            triggered=True,
            code="empty_answer",
            detail="Model returned an empty answer",
        )

    for pattern in OUTPUT_LEAK_PATTERNS:
        if pattern.search(normalized):
            return GuardrailCheckResult(
                triggered=True,
                code="suspicious_output",
                detail="Answer appears to expose system instructions or secrets",
            )

    if EMAIL_PATTERN.search(normalized):
        return GuardrailCheckResult(
            triggered=True,
            code="pii_detected",
            detail="Answer appears to contain sensitive personal data",
        )

    for phone_match in PHONE_PATTERN.finditer(normalized):
        if not _phone_match_is_likely_datetime_or_date_prefix(phone_match):
            return GuardrailCheckResult(
                triggered=True,
                code="pii_detected",
                detail="Answer appears to contain sensitive personal data",
            )

    has_sources = bool(sources)
    if settings.guardrails_require_sources and not has_sources and not _looks_like_safe_fallback_message(normalized):
        return GuardrailCheckResult(
            triggered=True,
            code="missing_sources",
            detail="Answer has no supporting sources and no explicit fallback",
        )

    return GuardrailCheckResult(triggered=False)


def validate_answer(answer: Any, sources: list[dict[str, Any]] | None) -> GuardrailCheckResult:
    check = detect_output_violation(answer, sources)
    if check.triggered:
        raise OutputGuardrailError(
            check.detail or "Answer did not pass output guardrails",
            check.code or "output_guardrail_triggered",
        )
    return check


def apply_output_guardrails(answer: Any, sources: list[dict[str, Any]] | None) -> tuple[str, bool]:
    """
    Проверка выхода. При срабатывании только по PII и включённом fallback —
    заменяем e-mail/телефон на маркеры и возвращаем текст (без полной подмены ответа).

    Returns:
        (текст для пользователя, True если выполнено редактирование PII)
    """
    check = detect_output_violation(answer, sources)
    if not check.triggered:
        return str(answer), False

    if check.code == "pii_detected":
        if not should_apply_fallback("pii_detected"):
            raise OutputGuardrailError(
                check.detail or "Answer did not pass output guardrails",
                "pii_detected",
            )
        redacted = redact_sensitive_text(answer)
        validate_answer(redacted, sources)
        return redacted, True

    validate_answer(answer, sources)
    return str(answer), False


def get_safe_fallback_message(code: str) -> str:
    return SAFE_FALLBACK_MESSAGES.get(
        code,
        "Ответ был скрыт guardrails, потому что не прошел проверку безопасности.",
    )


def should_apply_fallback(code: str) -> bool:
    settings = _settings()
    policy_map = {
        "empty_answer": settings.guardrails_fallback_on_empty_answer,
        "missing_sources": settings.guardrails_fallback_on_missing_sources,
        "suspicious_output": settings.guardrails_fallback_on_suspicious_output,
        "pii_detected": settings.guardrails_fallback_on_pii_detected,
    }
    return policy_map.get(code, True)
