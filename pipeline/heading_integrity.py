"""Narrow, side-effect-free checks for a proven writer-output corruption.

This is NOT a Markdown parser or a general spelling/censorship validator.
Only an orphan triple-star suffix in a plain ATX heading is diagnosed. More
complex inline markup is left alone rather than guessed at. Never reconstruct
missing letters: the writer/editor must return a source-grounded replacement.
"""
from __future__ import annotations

import re

_HEADING = re.compile(r"^#{1,6}[ \t]+(.+)$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_WORD_STARS = re.compile(r"[^\W\d_]\*{3}(?=\s|[.,!?;:]|$)", re.UNICODE)


def corrupt_heading_lines(content: str) -> tuple[int, ...]:
    """Return 1-based suspect lines; do not mutate content or consult files.

    Requiring exactly three stars in the entire heading avoids classifying
    valid triple emphasis or nested italic/bold closers as damaged words.
    Escapes, inline code, links and HTML are deliberately outside this narrow
    check. Only column-zero headings are considered, avoiding list-container
    ambiguity. Documents containing potential raw HTML are outside scope.
    These intentional false negatives are safer than hand-parsing Markdown.
    """
    content = str(content or "")
    if "<" in content:
        return ()
    suspect: list[int] = []
    fence_char = ""
    fence_size = 0
    for number, line in enumerate(str(content or "").splitlines(), 1):
        fence = _FENCE.match(line)
        if fence_char:
            if (fence and fence.group(1)[0] == fence_char
                    and len(fence.group(1)) >= fence_size
                    and not fence.group(2).strip()):
                fence_char = ""
            continue
        if fence:
            marker, info = fence.groups()
            if marker[0] != "`" or "`" not in info:
                fence_char, fence_size = marker[0], len(marker)
                continue
        heading = _HEADING.match(line)
        if not heading:
            continue
        text = heading.group(1)
        if any(char in text for char in ("\\", "`", "<", "[")):
            continue
        if text.count("*") == 3 and _WORD_STARS.search(text):
            suspect.append(number)
    return tuple(suspect)
