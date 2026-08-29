"""Shared selected-source sufficiency metrics for scanner, worker, and preflight."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any, Iterable

try:
    from .source_attribution import normalize_source_url, source_identity_key
except ImportError:  # pragma: no cover
    from source_attribution import normalize_source_url, source_identity_key


MIN_DISTINCT_SOURCE_WORDS = 200
MAX_ARTICLE_SOURCE_RATIO = 1.35
DUPLICATE_BLOCK_COVERAGE = 0.80
_WORD_RE = re.compile(r"[\wäöåÄÖÅ]+(?:[-’'][\wäöåÄÖÅ]+)*", re.UNICODE)


def word_tokens(value: Any) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _WORD_RE.findall(str(value or "")))


def word_count(value: Any) -> int:
    return len(word_tokens(value))


def _contains(container: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    if not candidate or len(candidate) > len(container):
        return False
    width = len(candidate)
    return any(
        container[index : index + width] == candidate
        for index in range(len(container) - width + 1)
    )


def _duplicate(container: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    if _contains(container, candidate):
        return True
    if not candidate or len(candidate) > len(container):
        return False
    longest = SequenceMatcher(
        a=container, b=candidate, autojunk=False
    ).find_longest_match().size
    return longest / len(candidate) >= DUPLICATE_BLOCK_COVERAGE


def deduplicated_selected_source_words(
    blocks: Iterable[dict[str, Any]], unused_urls: set[str] | None = None
) -> int:
    unused_urls = unused_urls or set()
    candidates: list[tuple[str, ...]] = []
    for block in blocks:
        url = normalize_source_url(block.get("source_url"))
        if url and url in unused_urls:
            continue
        tokens = word_tokens(block.get("text"))
        if tokens:
            candidates.append(tokens)
    candidates.sort(key=lambda tokens: (-len(tokens), tokens))
    retained: list[tuple[str, ...]] = []
    for candidate in candidates:
        if any(_duplicate(existing, candidate) for existing in retained):
            continue
        retained.append(candidate)
    return sum(len(tokens) for tokens in retained)


def selected_public_urls(blocks: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    selected: dict[str, str] = {}
    for block in blocks:
        url = normalize_source_url(block.get("source_url"))
        identity = source_identity_key(url)
        if url and identity and identity not in selected:
            selected[identity] = url
    return tuple(sorted(selected.values()))


def selected_source_admission_errors(
    packet: dict[str, Any], *, minimum_words: int = MIN_DISTINCT_SOURCE_WORDS
) -> tuple[str, ...]:
    blocks = [
        block
        for block in packet.get("clean_source_blocks") or []
        if isinstance(block, dict)
    ]
    errors: list[str] = []
    if packet.get("selected_source_provenance_error"):
        errors.append("selected_source_provenance_error")
    if packet.get("source_selection_outcome") != "usable_source_packet":
        errors.append("source_selection_outcome_not_usable")
    if not selected_public_urls(blocks):
        errors.append("selected_source_url_missing")
    if any(word_tokens(block.get("text")) and not normalize_source_url(block.get("source_url")) for block in blocks):
        errors.append("selected_source_url_invalid")
    if deduplicated_selected_source_words(blocks) < minimum_words:
        errors.append("thin_distinct_source")
    return tuple(dict.fromkeys(errors))


def article_source_ratio(
    content: Any,
    blocks: Iterable[dict[str, Any]],
    unused_urls: set[str] | None = None,
) -> float:
    source_words = deduplicated_selected_source_words(blocks, unused_urls)
    return word_count(content) / source_words if source_words else float("inf")
