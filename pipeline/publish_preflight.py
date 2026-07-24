#!/usr/bin/env python3
"""Fail-closed checks for completed Monica records before staged publishing."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

try:
    from .description_projection import project_public_description
    from .publisher import CANONICAL_CATEGORIES, effective_category
except ImportError:  # pragma: no cover - direct script/test execution from pipeline cwd
    from description_projection import project_public_description
    from publisher import CANONICAL_CATEGORIES, effective_category


MIN_DISTINCT_SOURCE_WORDS = 200
MAX_ARTICLE_SOURCE_RATIO = 1.35
DUPLICATE_BLOCK_COVERAGE = 0.80

_WORD_RE = re.compile(r"[\wäöåÄÖÅ]+(?:[-’'][\wäöåÄÖÅ]+)*", re.UNICODE)
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
_SENSITIVE_PUBLIC_SAFETY_RE = re.compile(
    r"\b(?:"
    r"rikos\w*|murh\w*|kuol\w*|surm\w*|ampu\w*|raiska\w*|sieppa\w*|"
    r"hyökkä\w*|isku(?!tilavuus)\w*|sota\w*|uhri\w*|onnettom\w*|tulipalo\w*|"
    r"palovamm\w*|pelast\w*|miina\w*|nälkä\w*|jano\w*|lunna\w*|"
    r"kidut\w*|terror\w*|"
    r"crime\w*|murder\w*|death\w*|shoot\w*|rape\w*|abduct\w*|kidnap\w*|"
    r"attack\w*|wars?|warfare|victim\w*|casualt\w*|disaster\w*|accident\w*|"
    r"fires?|wildfire\w*|rescue\w*|mines?|hunger\w*|thirst\w*|ransom\w*|"
    r"torture\w*|terror\w*|emergency\w*"
    r")\b",
    re.IGNORECASE,
)
_ENTERTAINMENT_CATEGORY_TAGS = frozenset({"kulttuuri", "viihde"})
_ENTERTAINMENT_PERFORMANCE_RE = re.compile(
    r"\b(?:concert\w*|konsert\w*|perform\w*|esiinty\w*|"
    r"(?:musiikki|väliaika|lava)esity\w*|half[- ]time show\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PublishPreflightResult:
    action: str
    requires_monica_review: bool
    reasons: tuple[str, ...]
    categories: tuple[str, str, str]
    selected_source_urls: tuple[str, ...]
    public_source_urls: tuple[str, ...]
    hidden_source_urls: tuple[str, ...]
    distinct_source_words: int
    article_words: int
    article_source_ratio: float
    sensitive: bool


def _canonical_category(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    return next((category for category in CANONICAL_CATEGORIES if category.casefold() == raw), "")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolved_categories(record: dict[str, Any]) -> tuple[str, str, str]:
    packet = _mapping(record.get("packet"))
    payload = _mapping(record.get("payload"))
    article = _mapping(record.get("article"))
    packet_category = _canonical_category(packet.get("category"))
    payload_category = _canonical_category(payload.get("category"))
    raw_article_category = _canonical_category(article.get("category"))
    article_category = _canonical_category(effective_category(article)) if raw_article_category else ""
    return packet_category, payload_category, article_category


def _normalize_url(value: Any) -> str:
    raw = str(value or "").strip().rstrip(".,;:!?")
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return ""
    hostname = parts.hostname.casefold().removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        return ""
    if port and not ((parts.scheme.casefold() == "http" and port == 80) or (parts.scheme.casefold() == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.casefold(), hostname, path, parts.query, ""))


def _url_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if re.fullmatch(r"https?://\S+", value.strip(), flags=re.IGNORECASE):
            direct = _normalize_url(value)
            if direct:
                yield direct
        for match in _URL_RE.findall(value):
            normalized = _normalize_url(match.rstrip(")]}>"))
            if normalized:
                yield normalized
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _url_values(item)


def _public_source_urls(article: dict[str, Any]) -> tuple[str, ...]:
    """Return URLs exposed by the publisher's exact article projection.

    ``journalist_note`` is deliberately excluded: it is not the article's
    source-attribution surface and cannot make a hidden selected source public.
    """
    description = project_public_description(article.get("description", ""))

    raw_summary_bullets = article.get("summary_bullets", [])
    summary_bullets = (
        [str(point).strip() for point in raw_summary_bullets if str(point).strip()][:4]
        if isinstance(raw_summary_bullets, list)
        else []
    )
    raw_key_points = article.get("key_points", [])
    key_points = (
        [str(point).strip() for point in raw_key_points if str(point).strip()][:3]
        if isinstance(raw_key_points, list)
        else []
    )

    values: list[Any] = [
        article.get("source_url") or article.get("link"),
        article.get("title"),
        description,
        article.get("summary"),
        article.get("content"),
        summary_bullets,
        key_points,
    ]
    return tuple(sorted({url for value in values for url in _url_values(value)}))


def _explicitly_unused_urls(packet: dict[str, Any]) -> set[str]:
    """Accept only structured unused declarations with an explicit empty claim list."""
    rows = packet.get("source_usage")
    if not isinstance(rows, list):
        return set()
    unused: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("used") is not False:
            continue
        if row.get("dependent_claims") != []:
            continue
        url = _normalize_url(row.get("source_url"))
        if url:
            unused.add(url)
    return unused


def _block_word_tokens(block: dict[str, Any]) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _WORD_RE.findall(str(block.get("text") or "")))


def _contains_tokens(container: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    if not candidate or len(candidate) > len(container):
        return False
    width = len(candidate)
    return any(container[index : index + width] == candidate for index in range(len(container) - width + 1))


def _is_duplicate_block(container: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    if _contains_tokens(container, candidate):
        return True
    if not candidate or len(candidate) > len(container):
        return False
    # Feed extraction can retain one complete block plus slightly wrapped
    # halves. Treat strong contiguous coverage as duplicated evidence so CTA or
    # wrapper words cannot inflate the source floor.
    longest = SequenceMatcher(a=container, b=candidate, autojunk=False).find_longest_match().size
    return longest / len(candidate) >= DUPLICATE_BLOCK_COVERAGE


def _deduplicated_source_words(blocks: list[dict[str, Any]], unused_urls: set[str]) -> int:
    candidates: list[tuple[str, ...]] = []
    for block in blocks:
        block_url = _normalize_url(block.get("source_url"))
        if block_url and block_url in unused_urls:
            continue
        tokens = _block_word_tokens(block)
        if tokens:
            candidates.append(tokens)
    candidates.sort(key=lambda tokens: (-len(tokens), tokens))
    retained: list[tuple[str, ...]] = []
    for candidate in candidates:
        if any(_is_duplicate_block(existing, candidate) for existing in retained):
            continue
        retained.append(candidate)
    return sum(len(tokens) for tokens in retained)


def _article_word_count(article: dict[str, Any]) -> int:
    return len(_WORD_RE.findall(str(article.get("content") or "")))


def _is_sensitive(record: dict[str, Any]) -> bool:
    packet = _mapping(record.get("packet"))
    article = _mapping(record.get("article"))
    if packet.get("sensitive") is True or packet.get("public_safety") is True:
        return True
    values = [
        packet.get("headline_seed"),
        packet.get("description_seed"),
        article.get("title"),
        article.get("description"),
        article.get("summary"),
        article.get("content"),
    ]
    return bool(_SENSITIVE_PUBLIC_SAFETY_RE.search(" ".join(str(value or "") for value in values)))


def _requires_entertainment_category_review(
    record: dict[str, Any], categories: tuple[str, str, str]
) -> bool:
    if not all(categories) or len(set(categories)) != 1 or categories[0] == "Kulttuuri":
        return False
    packet = _mapping(record.get("packet"))
    payload = _mapping(record.get("payload"))
    article = _mapping(record.get("article"))
    tags = {
        str(tag).strip().casefold()
        for value in (payload.get("tags"), article.get("tags"))
        if isinstance(value, (list, tuple))
        for tag in value
        if str(tag).strip()
    }
    if not tags.intersection(_ENTERTAINMENT_CATEGORY_TAGS):
        return False
    values = [
        packet.get("headline_seed"),
        packet.get("description_seed"),
        packet.get("source_text"),
        payload.get("title"),
        payload.get("content"),
        article.get("title"),
        article.get("content"),
    ]
    return bool(
        _ENTERTAINMENT_PERFORMANCE_RE.search(
            " ".join(str(value or "") for value in values)
        )
    )


def evaluate_publish_preflight(record: dict[str, Any]) -> PublishPreflightResult:
    """Classify one completed Monica record without changing it or its queue."""
    packet = _mapping(record.get("packet"))
    article = _mapping(record.get("article"))
    blocks = [block for block in packet.get("clean_source_blocks") or [] if isinstance(block, dict)]
    categories = _resolved_categories(record)
    unused_urls = _explicitly_unused_urls(packet)
    selected_urls = tuple(
        sorted(
            {
                normalized
                for block in blocks
                if (normalized := _normalize_url(block.get("source_url"))) and normalized not in unused_urls
            }
        )
    )
    public_urls = _public_source_urls(article)
    hidden_urls = tuple(url for url in selected_urls if url not in set(public_urls))
    missing_selected_url = any(
        _block_word_tokens(block)
        and not _normalize_url(block.get("source_url"))
        for block in blocks
    )
    distinct_source_words = _deduplicated_source_words(blocks, unused_urls)
    article_words = _article_word_count(article)
    ratio = article_words / distinct_source_words if distinct_source_words else float("inf")
    sensitive = _is_sensitive(record)

    hard_reasons: list[str] = []
    review_reasons: list[str] = []
    if any(not category for category in categories):
        hard_reasons.append("category_unresolved")
    elif len(set(categories)) != 1:
        hard_reasons.append("category_disagreement")
    if missing_selected_url:
        hard_reasons.append("selected_source_url_missing")
    if hidden_urls:
        hard_reasons.append("selected_source_not_public")
    if _requires_entertainment_category_review(record, categories):
        review_reasons.append("entertainment_category_review")
    if distinct_source_words < MIN_DISTINCT_SOURCE_WORDS:
        review_reasons.append("thin_distinct_source")
    if ratio > MAX_ARTICLE_SOURCE_RATIO:
        review_reasons.append("article_source_ratio_exceeded")
    if sensitive and (
        "thin_distinct_source" in review_reasons
        or "article_source_ratio_exceeded" in review_reasons
    ):
        review_reasons.append("sensitive_thin_story")

    reasons = tuple([*hard_reasons, *review_reasons])
    action = "reject" if hard_reasons else "monica_review" if review_reasons else "publish"
    return PublishPreflightResult(
        action=action,
        requires_monica_review=bool(review_reasons),
        reasons=reasons,
        categories=categories,
        selected_source_urls=selected_urls,
        public_source_urls=public_urls,
        hidden_source_urls=hidden_urls,
        distinct_source_words=distinct_source_words,
        article_words=article_words,
        article_source_ratio=ratio,
        sensitive=sensitive,
    )
