# Windows: консоль по умолчанию cp1252 — до bm25/print-хуков пробуем UTF-8 для stdout/stderr.
import sys

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        _reconf = getattr(_stream, "reconfigure", None)
        if _reconf is None:
            continue
        try:
            _reconf(encoding="utf-8", errors="replace")
        except (OSError, ValueError, TypeError):
            pass

# bm25s (transitive) импортирует utils.benchmark → на Windows нет stdlib `resource`,
# пакет эмитирует logger.warning() через bm25s.utils.benchmark; глушим только эту запись.
import logging

_BM25_RESOURCE_BANNER = "resource module not available on Windows"


class _SuppressBM25SResourceWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        return _BM25_RESOURCE_BANNER not in record.getMessage()


logging.getLogger("bm25s.utils.benchmark").addFilter(_SuppressBM25SResourceWarning())

# bm25s.utils.benchmark печатает баннер через print() на import-time (не через warnings/logging).
# Гасим stdout на время форсированного импорта здесь, пока модуль ещё не в sys.modules.
import sys as _sys

if "bm25s.utils.benchmark" not in _sys.modules:
    import contextlib as _cl, io as _io
    with _cl.redirect_stdout(_io.StringIO()):
        import bm25s.utils.benchmark as _bm25s_bench  # noqa: F401
    del _cl, _io, _bm25s_bench
del _sys

# НЕ импортировать session_store здесь — имя затеняет подмодуль app.session_store.
# Используйте: from app.session_store import session_store  (напрямую из подмодуля).
# Шаг condense: аналогично ``from app.condense_step import condense_step`` нельзя —
# иначе имя затеняет подмодуль ``app.condense_step``.
