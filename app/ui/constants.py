"""Константы Streamlit UI (без зависимостей от streamlit)."""

MAX_HISTORY = 20
TEXT_PREVIEW_EXTENSIONS = (".txt", ".md", ".html", ".pdf", ".docx")
SUGGESTED_QUESTIONS = [
    "Сравни hybrid retrieval и vector-only на практических кейсах",
    "Сделай обзор по теме AI-агентов в разработке",
    "Какие документы лучше всего покрывают prompt injection?",
    "Собери конспект по теме RAG и knowledge management",
]

# Плейсхолдеры без Unicode «—»: в dropdown Base Web такой текст иногда не рисуется; список рендерится в portal вне сайдбара.
_SIDEBAR_FILTER_TOPIC_ALL = "Все темы (без фильтра)"
_SIDEBAR_FILTER_FOLDER_ALL = "Все папки (без фильтра)"
