"""Deterministic public projection for article descriptions."""

from __future__ import annotations

import re
from typing import Any


PUBLIC_DESCRIPTION_LIMIT = 155
MIN_USEFUL_SENTENCE_LENGTH = 40

WEAK_DESCRIPTION_ENDINGS = frozenset(
    {
        "ja",
        "sekä",
        "tai",
        "mutta",
        "että",
        "jotta",
        "kun",
        "jos",
        "koska",
        "vaan",
        "eli",
        "on",
        "ovat",
        "oli",
        "olivat",
        "tulee",
        "jossa",
        "joissa",
        "jonka",
        "jotka",
        "kuten",
    }
)

_SENTENCE_END_RE = re.compile(r"""[.!?](?:["”’»])?(?=\s|$)""")
_WORD_RE = re.compile(r"[\w]+(?:[-’'][\w]+)*", re.UNICODE)


def project_public_description(
    value: Any,
    *,
    limit: int = PUBLIC_DESCRIPTION_LIMIT,
    min_sentence_length: int = MIN_USEFUL_SENTENCE_LENGTH,
) -> str:
    """Normalize and cap a public description without cutting a word.

    Over-limit text prefers the longest complete sentence that fits and meets
    the usefulness floor. Otherwise it retreats to a whole-word boundary,
    removes weak Finnish connector endings, and appends one Unicode ellipsis.
    """
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text

    sentence_ends = [
        match.end()
        for match in _SENTENCE_END_RE.finditer(text)
        if min_sentence_length <= match.end() <= limit
    ]
    if sentence_ends:
        return text[: sentence_ends[-1]]

    word_limit = max(0, limit - 1)
    words = [
        match
        for match in _WORD_RE.finditer(text)
        if match.end() <= word_limit
    ]
    while words and words[-1].group(0).casefold() in WEAK_DESCRIPTION_ENDINGS:
        words.pop()

    if not words:
        return "…" if limit else ""
    return f"{text[: words[-1].end()]}…"
