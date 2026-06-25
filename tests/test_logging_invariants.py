import json
import logging

from app.logging_config import StructuredFormatter, StructuredLogMaskingFilter


def test_sink_payload_is_masked() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="contact alice@example.com",
        args=(),
        exc_info=None,
    )
    record.extra_fields = {
        "question": "email bob@example.com and token: abcdef123456",
        "safe_field": "alice@example.com",
    }

    assert StructuredLogMaskingFilter().filter(record)

    payload = json.loads(StructuredFormatter().format(record))

    assert payload["message"] == "contact [REDACTED_EMAIL]"
    assert payload["question"] == "email [REDACTED_EMAIL] and token: [REDACTED_SECRET]"
    assert payload["safe_field"] == "alice@example.com"
