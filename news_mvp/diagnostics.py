"""Bounded, secret-safe exception description for logs and durable error columns.

A bare exception class name (`type(error).__name__`) makes every failure
undisagnosable: a live tick reported `"error": "ValueError"` with no statement of
what disagreed, so provider, gate and content failures were indistinguishable.

The message must be useful without ever persisting provider output, which can
carry credentials, tokens, or full response bodies. This trims to one bounded
line and redacts anything credential-shaped before it is recorded.
"""

import re

MAX_CHARS = 300

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|bearer|authorization)\b\s*[:=]?\s*\S+"),
    re.compile(r"\bgh[a-z]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9\-_]{16,}\b"),
    re.compile(r"\bey[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{5,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def safe_error(error):
    """`"<ClassName>: <bounded, redacted message>"` for durable recording."""
    message = str(error).replace("\n", " ").replace("\r", " ").strip()
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[redacted]", message)
    if len(message) > MAX_CHARS:
        message = message[: MAX_CHARS - 3].rstrip() + "..."
    return f"{type(error).__name__}: {message}" if message else type(error).__name__
