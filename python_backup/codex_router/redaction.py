"""Small, conservative secret redaction helpers."""

import re


SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "authorization",
    "api_key",
    "client_secret",
}

_BEARER_RE = re.compile(r"(Bearer\s+)[^\s,;]+", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(
    r"((?:access_token|refresh_token|authorization|api_key|client_secret)\s*[:=]\s*)[^\s,;]+",
    re.IGNORECASE,
)


def redact_text(value):
    if value is None:
        return ""
    text = str(value)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    return _KEY_VALUE_RE.sub(r"\1[REDACTED]", text)


def redact_value(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in SECRET_KEYS else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return redact_text(value)
