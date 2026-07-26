#!/usr/bin/env python3
"""Guide front matter and lifecycle contracts.

Guides are fast-changing utility content. Invalid or expired guides must fail
closed from discovery while keeping their stable HTML URL available.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


MIN_BODY_WORDS = 900
MAX_BODY_WORDS = 1500
MAX_REVIEW_DAYS = 14
MAX_EXPIRY_DAYS = 30

REQUIRED_FIELDS = (
    "title",
    "description",
    "date",
    "reviewed_at",
    "updated_at",
    "next_review_at",
    "expires_at",
    "correction_url",
    "search_terms",
)


@dataclass(frozen=True)
class GuideLifecycle:
    state: str
    discoverable: bool
    promoted: bool
    errors: tuple[str, ...]
    word_count: int


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "~"}:
        return None
    if value.startswith(('"', "'", "[")):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            pass
    return value.strip("\"'")


def parse_guide_document(text: str) -> tuple[dict, str]:
    """Parse the small, explicit YAML subset used by guide documents."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text

    meta: dict = {}
    current_list: list | None = None
    current_item: dict | None = None

    for raw_line in match.group(1).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        top_level = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw_line)
        if top_level:
            key, raw_value = top_level.groups()
            if raw_value.strip():
                meta[key] = _parse_scalar(raw_value)
                current_list = None
            else:
                current_list = []
                meta[key] = current_list
            current_item = None
            continue

        item_start = re.match(
            r"^\s{2}-\s+([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw_line
        )
        if item_start and current_list is not None:
            key, raw_value = item_start.groups()
            current_item = {key: _parse_scalar(raw_value)}
            current_list.append(current_item)
            continue

        item_field = re.match(
            r"^\s{4}([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw_line
        )
        if item_field and current_item is not None:
            key, raw_value = item_field.groups()
            current_item[key] = _parse_scalar(raw_value)
            continue

        scalar_item = re.match(r"^\s{2}-\s+(.*)$", raw_line)
        if scalar_item and current_list is not None:
            current_list.append(_parse_scalar(scalar_item.group(1)))
            current_item = None

    return meta, match.group(2).strip()


def load_guide(path: Path) -> tuple[dict, str]:
    return parse_guide_document(path.read_text(encoding="utf-8"))


def as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("empty date")
    return date.fromisoformat(text[:10])


def supported_word_count(markdown: str) -> int:
    """Count supported body prose, excluding Markdown syntax and URL targets."""
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+>]\s+", "", text)
    return len(
        re.findall(
            r"[0-9A-Za-zÅÄÖåäö]+(?:[-’'][0-9A-Za-zÅÄÖåäö]+)*",
            text,
        )
    )


def validate_guide(meta: dict, body: str) -> tuple[list[str], int]:
    errors: list[str] = []
    word_count = supported_word_count(body)

    for field in REQUIRED_FIELDS:
        if not meta.get(field):
            errors.append(f"missing required field: {field}")

    if not MIN_BODY_WORDS <= word_count <= MAX_BODY_WORDS:
        errors.append(
            f"supported body word count {word_count} is outside "
            f"{MIN_BODY_WORDS}-{MAX_BODY_WORDS}"
        )

    parsed_dates: dict[str, date] = {}
    for field in ("date", "reviewed_at", "updated_at", "next_review_at", "expires_at"):
        if not meta.get(field):
            continue
        try:
            parsed_dates[field] = as_date(meta[field])
        except ValueError:
            errors.append(f"invalid date: {field}")

    reviewed = parsed_dates.get("reviewed_at")
    next_review = parsed_dates.get("next_review_at")
    expires = parsed_dates.get("expires_at")
    published = parsed_dates.get("date")
    updated = parsed_dates.get("updated_at")

    if published and updated and updated < published:
        errors.append("updated_at precedes date")
    if updated and reviewed and updated > reviewed:
        errors.append("updated_at follows reviewed_at")
    if reviewed and next_review:
        review_days = (next_review - reviewed).days
        if not 1 <= review_days <= MAX_REVIEW_DAYS:
            errors.append(
                f"next_review_at must be 1-{MAX_REVIEW_DAYS} days after reviewed_at"
            )
    if reviewed and expires:
        expiry_days = (expires - reviewed).days
        if not 1 <= expiry_days <= MAX_EXPIRY_DAYS:
            errors.append(
                f"expires_at must be 1-{MAX_EXPIRY_DAYS} days after reviewed_at"
            )
    if next_review and expires and next_review > expires:
        errors.append("next_review_at follows expires_at")

    correction_url = str(meta.get("correction_url", ""))
    if correction_url and not (
        correction_url.startswith("mailto:") or correction_url.startswith("https://")
    ):
        errors.append("correction_url must be mailto: or https://")

    sources = meta.get("sources")
    if not isinstance(sources, list) or len(sources) < 3:
        errors.append("at least three official sources are required")
        sources = []

    checker_count = 0
    domains: set[str] = set()
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            errors.append(f"source {index} must be a mapping")
            continue
        if not source.get("name"):
            errors.append(f"source {index} is missing name")
        source_url = str(source.get("url", ""))
        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            errors.append(f"source {index} must use an https URL")
        elif parsed_url.netloc in domains:
            errors.append(f"source {index} duplicates an official domain")
        else:
            domains.add(parsed_url.netloc)
        if source.get("official") is not True:
            errors.append(f"source {index} is not marked official")
        if source.get("authoritative_checker") is True:
            checker_count += 1
        try:
            checked_at = as_date(source.get("source_checked_at"))
        except (TypeError, ValueError):
            errors.append(f"source {index} has invalid source_checked_at")
        else:
            if reviewed and checked_at != reviewed:
                errors.append(
                    f"source {index} source_checked_at must equal reviewed_at"
                )

    if checker_count != 1:
        errors.append("exactly one source must be the authoritative checker")

    return errors, word_count


def evaluate_guide(
    meta: dict,
    body: str,
    *,
    today: date | None = None,
) -> GuideLifecycle:
    errors, word_count = validate_guide(meta, body)
    if errors:
        return GuideLifecycle(
            state="invalid",
            discoverable=False,
            promoted=False,
            errors=tuple(errors),
            word_count=word_count,
        )

    for exclusion_state in ("draft", "noindex"):
        if meta.get(exclusion_state) is True:
            return GuideLifecycle(
                state=exclusion_state,
                discoverable=False,
                promoted=False,
                errors=(),
                word_count=word_count,
            )

    today = today or date.today()
    if today >= as_date(meta["expires_at"]):
        return GuideLifecycle(
            state="expired",
            discoverable=False,
            promoted=False,
            errors=(),
            word_count=word_count,
        )
    if today >= as_date(meta["next_review_at"]):
        return GuideLifecycle(
            state="review_due",
            discoverable=True,
            promoted=False,
            errors=(),
            word_count=word_count,
        )
    return GuideLifecycle(
        state="current",
        discoverable=True,
        promoted=True,
        errors=(),
        word_count=word_count,
    )


def main() -> int:
    guides_dir = Path(__file__).resolve().parents[1] / "content" / "oppaat"
    failures: list[str] = []
    checked = 0
    for path in sorted(guides_dir.glob("*.md")):
        if path.name == "_index.md":
            continue
        checked += 1
        meta, body = load_guide(path)
        lifecycle = evaluate_guide(meta, body)
        if lifecycle.errors:
            failures.extend(f"{path}: {error}" for error in lifecycle.errors)
        print(
            f"[guide-lifecycle] {path.name}: state={lifecycle.state} "
            f"words={lifecycle.word_count}"
        )
    if failures:
        for failure in failures:
            print(f"[guide-lifecycle] ERROR: {failure}")
        return 1
    print(f"[guide-lifecycle] PASS: {checked} guide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
