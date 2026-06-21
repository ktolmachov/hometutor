import re

KEYWORD_QUERY = "keyword"
QA_QUERY = "qa"

_ID_PATTERN = re.compile(r"\b[A-Za-z]{2,}(?:[-_/][A-Za-z0-9.]+)+\b")
_ASCII_EXACT_PATTERN = re.compile(r"^[A-Za-z0-9._/#-]{2,40}$")
_UNICODE_SINGLE_TERM_PATTERN = re.compile(r"^[^\W_]{2,40}$", re.UNICODE)
_QUESTION_STARTERS = {
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "\u0447\u0442\u043e",
    "\u043a\u0430\u043a\u043e\u0439",
    "\u043a\u0430\u043a\u0430\u044f",
    "\u043a\u0430\u043a\u043e\u0435",
    "\u043a\u0430\u043a\u0438\u0435",
    "\u043a\u0442\u043e",
    "\u043a\u043e\u0433\u043e",
    "\u043a\u043e\u043c\u0443",
    "\u043a\u0435\u043c",
    "\u0447\u0435\u043c",
    "\u0433\u0434\u0435",
    "\u043a\u043e\u0433\u0434\u0430",
    "\u0437\u0430\u0447\u0435\u043c",
    "\u043f\u043e\u0447\u0435\u043c\u0443",
    "\u043a\u0430\u043a",
    "\u0441\u043a\u043e\u043b\u044c\u043a\u043e",
    "\u043b\u0438",
    "\u044d\u0442\u043e",
    "\u0435\u0441\u0442\u044c",
    "\u043c\u043e\u0436\u0435\u0442",
    "\u043c\u043e\u0433\u0443\u0442",
    "\u043d\u0443\u0436\u043d\u043e",
    "\u043d\u0430\u0434\u043e",
}


def _starts_like_question(normalized: str) -> bool:
    lower_normalized = normalized.lower()
    return normalized.endswith("?") or any(
        lower_normalized.startswith(f"{starter} ") for starter in _QUESTION_STARTERS
    )


def detect_query_type(question: str) -> str:
    normalized = " ".join((question or "").strip().split())
    if not normalized:
        return QA_QUERY

    if _starts_like_question(normalized):
        return QA_QUERY

    if _ASCII_EXACT_PATTERN.fullmatch(normalized):
        return KEYWORD_QUERY

    if _ID_PATTERN.search(normalized):
        return KEYWORD_QUERY

    if " " not in normalized and _UNICODE_SINGLE_TERM_PATTERN.fullmatch(normalized):
        return KEYWORD_QUERY

    tokens = normalized.split()
    if len(tokens) <= 4 and any(any(ch.isdigit() for ch in token) for token in tokens):
        return KEYWORD_QUERY

    uppercase_tokens = [
        token
        for token in tokens
        if len(token) >= 2 and token.upper() == token and any(ch.isalpha() for ch in token)
    ]
    if len(tokens) <= 5 and uppercase_tokens:
        return KEYWORD_QUERY

    return QA_QUERY


def detect_extended_query_type(question: str) -> str:
    """Уточнение типа для не-keyword вопросов без LLM-классификатора (US-3.4).

    Возвращает одно из: ``learning_plan`` | ``overview`` | ``synthesis`` | ``qa``.
    Вызывать только если ``detect_query_type`` уже вернул ``QA_QUERY``.
    """
    normalized = " ".join((question or "").strip().split())
    if not normalized:
        return QA_QUERY

    low = normalized.lower()

    learning_markers = (
        "план обучения",
        "learning plan",
        "порядок изучения",
        "roadmap",
        "что учить в каком порядке",
        "с чего начать изучение",
    )
    if any(m in low for m in learning_markers):
        return "learning_plan"

    synthesis_markers = (
        "сравни ",
        "сопоставь",
        "синтез",
        "резюмируй",
        "итог по",
        "выводы по",
        "summarize",
        "in summary",
        "compare ",
        "versus",
        " vs ",
    )
    if any(m in low for m in synthesis_markers):
        return "synthesis"

    overview_markers = (
        "краткий обзор",
        "дай обзор",
        "обзор темы",
        "overview",
        "общая картина",
        "в двух словах",
        "кратко о том",
        "big picture",
    )
    if any(m in low for m in overview_markers):
        return "overview"

    return QA_QUERY
