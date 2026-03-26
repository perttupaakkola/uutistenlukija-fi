#!/usr/bin/env python3
"""
validate_feeds.py — validate generated RSS feeds from Hugo output.

Checks:
- main feed: public/index.xml
- category feeds: public/categories/*/index.xml

Validation:
- RSS 2.0 required channel elements
- required item elements
- RFC 2822 pubDate parsing
- non-empty title/link fields
- at least one item per feed
- duplicate guid values
- malformed URLs in link fields
- stale items older than 90 days (warning)

Usage:
    python3 pipeline/validate_feeds.py
    python3 pipeline/validate_feeds.py --public-dir public
    python3 pipeline/validate_feeds.py --verbose
"""

from __future__ import annotations

import argparse
import html
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_PUBLIC_DIR = PROJECT_DIR / "public"
STALE_DAYS = 90


@dataclass
class FeedResult:
    path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    item_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def child_text(parent: ET.Element | None, name: str) -> str:
    if parent is None:
        return ""
    for child in list(parent):
        if local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def child_exists(parent: ET.Element | None, name: str) -> bool:
    if parent is None:
        return False
    return any(local_name(child.tag) == name for child in list(parent))


def iter_children(parent: ET.Element | None, name: str):
    if parent is None:
        return
    for child in list(parent):
        if local_name(child.tag) == name:
            yield child


def is_valid_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_rfc2822(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def discover_feeds(public_dir: Path) -> list[Path]:
    feeds: list[Path] = []
    main_feed = public_dir / "index.xml"
    if main_feed.exists():
        feeds.append(main_feed)

    categories_dir = public_dir / "categories"
    nested_category_feeds = sorted(categories_dir.glob("*/index.xml")) if categories_dir.exists() else []
    if nested_category_feeds:
        feeds.extend(nested_category_feeds)
    else:
        # Fallback for older flat category feed layouts.
        feeds.extend(sorted(path for path in public_dir.glob("*/index.xml") if path.name == "index.xml"))

    seen: set[Path] = set()
    deduped: list[Path] = []
    for feed in feeds:
        resolved = feed.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(feed)
    return deduped


def load_xml_root(feed_path: Path) -> ET.Element:
    text = feed_path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("&lt;?xml"):
        text = "<?xml" + text[len("&lt;?xml"):]
    if text.startswith("&amp;lt;?xml"):
        text = html.unescape(text)
    return ET.fromstring(text)


def validate_feed(feed_path: Path, now: datetime) -> FeedResult:
    result = FeedResult(path=feed_path)

    try:
        root = load_xml_root(feed_path)
    except ET.ParseError as exc:
        result.errors.append(f"XML parse error: {exc}")
        return result
    except OSError as exc:
        result.errors.append(f"Read error: {exc}")
        return result

    if local_name(root.tag) != "rss":
        result.errors.append(f"Root element is <{local_name(root.tag)}>, expected <rss>")
        return result

    channel = None
    for child in list(root):
        if local_name(child.tag) == "channel":
            channel = child
            break

    if channel is None:
        result.errors.append("Missing required <channel> element")
        return result

    for field_name in ("title", "link", "description"):
        if not child_exists(channel, field_name):
            result.errors.append(f"Missing required channel <{field_name}> element")

    channel_title = child_text(channel, "title")
    channel_link = child_text(channel, "link")

    if child_exists(channel, "title") and not channel_title:
        result.errors.append("Channel <title> is empty")
    if child_exists(channel, "link") and not channel_link:
        result.errors.append("Channel <link> is empty")
    if channel_link and not is_valid_url(channel_link):
        result.errors.append(f"Channel <link> is malformed: {channel_link}")

    items = list(iter_children(channel, "item"))
    result.item_count = len(items)
    if not items:
        result.errors.append("Feed has no <item> entries")
        return result

    guid_seen: dict[str, int] = {}
    stale_items: list[str] = []

    for idx, item in enumerate(items, start=1):
        item_title = child_text(item, "title")
        item_link = child_text(item, "link")
        item_pubdate = child_text(item, "pubDate")
        item_desc_exists = child_exists(item, "description")
        item_guid = child_text(item, "guid")

        label = item_title or f"item #{idx}"

        for required_field in ("title", "link", "pubDate"):
            if not child_exists(item, required_field):
                result.errors.append(f"{label}: missing required <{required_field}> element")

        if not item_desc_exists:
            result.errors.append(f"{label}: missing required <description> element")

        if child_exists(item, "title") and not item_title:
            result.errors.append(f"item #{idx}: empty <title>")
        if child_exists(item, "link") and not item_link:
            result.errors.append(f"{label}: empty <link>")
        if item_link and not is_valid_url(item_link):
            result.errors.append(f"{label}: malformed <link>: {item_link}")

        parsed_pubdate = parse_rfc2822(item_pubdate)
        if item_pubdate and parsed_pubdate is None:
            result.errors.append(f"{label}: invalid RFC 2822 <pubDate>: {item_pubdate}")
        if parsed_pubdate is not None and parsed_pubdate < now - timedelta(days=STALE_DAYS):
            stale_items.append(label)

        if item_guid:
            guid_seen[item_guid] = guid_seen.get(item_guid, 0) + 1

    duplicate_guids = sorted(guid for guid, count in guid_seen.items() if count > 1)
    for guid in duplicate_guids:
        result.errors.append(f"Duplicate <guid> detected: {guid}")

    if stale_items:
        preview = ", ".join(stale_items[:5])
        suffix = "" if len(stale_items) <= 5 else f" (+{len(stale_items) - 5} more)"
        result.warnings.append(
            f"{len(stale_items)} item(s) older than {STALE_DAYS} days: {preview}{suffix}"
        )

    latest_pubdates = []
    for item in items:
        dt = parse_rfc2822(child_text(item, "pubDate"))
        if dt is not None:
            latest_pubdates.append(dt)
    if latest_pubdates:
        newest = max(latest_pubdates)
        if newest < now - timedelta(days=STALE_DAYS):
            result.warnings.append(
                f"Feed appears stale: newest item is older than {STALE_DAYS} days ({newest.date().isoformat()})"
            )

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated RSS feeds in public/.")
    parser.add_argument("--public-dir", default=str(DEFAULT_PUBLIC_DIR), help="Directory containing generated public feed XML files.")
    parser.add_argument("--verbose", action="store_true", help="Print per-feed success lines even when fully clean.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    public_dir = Path(args.public_dir)
    if not public_dir.is_absolute():
        public_dir = PROJECT_DIR / public_dir

    if not public_dir.exists():
        print(f"[feeds] public dir not found: {public_dir}")
        return 1

    feed_paths = discover_feeds(public_dir)
    if not feed_paths:
        print(f"[feeds] no feed XML files found under {public_dir}")
        return 1

    now = datetime.now(timezone.utc)
    results = [validate_feed(path, now) for path in feed_paths]

    total_errors = sum(len(result.errors) for result in results)
    total_warnings = sum(len(result.warnings) for result in results)

    print("═" * 60)
    print(" RSS Feed Validation")
    print("═" * 60)
    print(f"[feeds] Public dir: {public_dir}")
    print(f"[feeds] Feeds checked: {len(results)}")

    for result in results:
        try:
            rel = result.path.relative_to(PROJECT_DIR)
        except ValueError:
            rel = result.path
        if args.verbose or result.errors or result.warnings:
            print(f"[feeds] {rel} — items={result.item_count}, errors={len(result.errors)}, warnings={len(result.warnings)}")
        for warning in result.warnings:
            print(f"[feeds]   WARN {warning}")
        for error in result.errors:
            print(f"[feeds]   ERR  {error}")

    print("[feeds] ──────────────────────────────────────────────")
    print(f"[feeds] Total errors: {total_errors}")
    print(f"[feeds] Total warnings: {total_warnings}")

    if total_errors:
        print("[feeds] Validation failed")
        return 1

    print("[feeds] Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
