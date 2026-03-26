#!/usr/bin/env python3
"""
validate_structured_data.py — validate JSON-LD blocks in generated HTML.

Scans public/**/*.html for <script type="application/ld+json"> blocks and
validates common structured-data invariants.

Checks:
- valid JSON
- every JSON-LD node has @type
- NewsArticle has headline, datePublished, author, publisher, image
- NewsArticle headline <= 110 chars
- datePublished is valid ISO 8601
- isAccessibleForFree is boolean, not string
- image URL is absolute
- WebSite has name, url, and potentialAction with SearchAction

Usage:
    python3 pipeline/validate_structured_data.py
    python3 pipeline/validate_structured_data.py --public-dir public
    python3 pipeline/validate_structured_data.py --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_PUBLIC_DIR = PROJECT_DIR / "public"
JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ValidationResult:
    path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    block_count: int = 0


@dataclass
class Summary:
    pages_checked: int = 0
    blocks_found: int = 0
    issues: int = 0


def is_absolute_url(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_iso8601(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_types(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def extract_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            graph = value.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    visit(item)
                extra = {k: v for k, v in value.items() if k != "@graph"}
                if extra:
                    nodes.append(extra)
            else:
                nodes.append(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return nodes


def has_search_action(value: Any) -> bool:
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        types = normalize_types(candidate.get("@type"))
        if "SearchAction" in types:
            return True
    return False


def validate_image(node: dict[str, Any], node_label: str, errors: list[str]) -> None:
    image = node.get("image")
    if image is None:
        return

    urls: list[str] = []
    if isinstance(image, str):
        urls.append(image)
    elif isinstance(image, dict):
        if isinstance(image.get("url"), str):
            urls.append(image["url"])
    elif isinstance(image, list):
        for item in image:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and isinstance(item.get("url"), str):
                urls.append(item["url"])

    if not urls:
        errors.append(f"{node_label}: image present but no absolute URL found")
        return

    for url in urls:
        if not is_absolute_url(url):
            errors.append(f"{node_label}: image URL is not absolute: {url}")


def validate_node(node: dict[str, Any], page_label: str, block_index: int, node_index: int, errors: list[str]) -> None:
    label = f"{page_label} block #{block_index} node #{node_index}"
    types = normalize_types(node.get("@type"))

    if not types:
        errors.append(f"{label}: missing @type")
        return

    if "isAccessibleForFree" in node and not isinstance(node["isAccessibleForFree"], bool):
        errors.append(f"{label}: isAccessibleForFree must be boolean, got {type(node['isAccessibleForFree']).__name__}")

    validate_image(node, label, errors)

    if "NewsArticle" in types:
        for field_name in ("headline", "datePublished", "author", "publisher", "image"):
            if field_name not in node:
                errors.append(f"{label}: NewsArticle missing {field_name}")

        headline = node.get("headline")
        if isinstance(headline, str):
            if len(headline) > 110:
                errors.append(f"{label}: NewsArticle headline exceeds 110 chars ({len(headline)})")
        elif "headline" in node:
            errors.append(f"{label}: NewsArticle headline must be string")

        date_published = node.get("datePublished")
        if isinstance(date_published, str):
            if parse_iso8601(date_published) is None:
                errors.append(f"{label}: datePublished is not valid ISO 8601: {date_published}")
        elif "datePublished" in node:
            errors.append(f"{label}: datePublished must be string")

    if "WebSite" in types:
        for field_name in ("name", "url", "potentialAction"):
            if field_name not in node:
                errors.append(f"{label}: WebSite missing {field_name}")

        url = node.get("url")
        if isinstance(url, str):
            if not is_absolute_url(url):
                errors.append(f"{label}: WebSite url is not absolute: {url}")
        elif "url" in node:
            errors.append(f"{label}: WebSite url must be string")

        if "potentialAction" in node and not has_search_action(node.get("potentialAction")):
            errors.append(f"{label}: WebSite potentialAction missing SearchAction")


def validate_page(path: Path) -> ValidationResult:
    result = ValidationResult(path=path)
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = JSONLD_RE.findall(text)
    result.block_count = len(blocks)

    page_label = str(path)
    for block_index, block in enumerate(blocks, start=1):
        payload_text = block.strip()
        if not payload_text:
            result.errors.append(f"{page_label} block #{block_index}: empty JSON-LD block")
            continue

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            result.errors.append(f"{page_label} block #{block_index}: invalid JSON: {exc}")
            continue

        nodes = extract_nodes(payload)
        if not nodes:
            result.errors.append(f"{page_label} block #{block_index}: no JSON-LD object nodes found")
            continue

        for node_index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                result.errors.append(f"{page_label} block #{block_index} node #{node_index}: node is not an object")
                continue
            validate_node(node, page_label, block_index, node_index, result.errors)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate JSON-LD structured data in generated HTML.")
    parser.add_argument("--public-dir", default=str(DEFAULT_PUBLIC_DIR), help="Directory containing generated public HTML files.")
    parser.add_argument("--verbose", action="store_true", help="Print clean pages too.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    public_dir = Path(args.public_dir)
    if not public_dir.is_absolute():
        public_dir = PROJECT_DIR / public_dir

    if not public_dir.exists():
        print(f"[schema] public dir not found: {public_dir}")
        return 1

    html_pages = sorted(public_dir.rglob("*.html"))
    if not html_pages:
        print(f"[schema] no HTML files found under {public_dir}")
        return 1

    results: list[ValidationResult] = []
    summary = Summary(pages_checked=len(html_pages))

    for path in html_pages:
        result = validate_page(path)
        results.append(result)
        summary.blocks_found += result.block_count
        summary.issues += len(result.errors) + len(result.warnings)

    print("═" * 60)
    print(" Structured Data Validation")
    print("═" * 60)
    print(f"[schema] Public dir: {public_dir}")

    for result in results:
        if args.verbose or result.errors or result.warnings:
            try:
                rel = result.path.relative_to(PROJECT_DIR)
            except ValueError:
                rel = result.path
            print(
                f"[schema] {rel} — blocks={result.block_count}, errors={len(result.errors)}, warnings={len(result.warnings)}"
            )
        for warning in result.warnings:
            print(f"[schema]   WARN {warning}")
        for error in result.errors:
            print(f"[schema]   ERR  {error}")

    total_errors = sum(len(result.errors) for result in results)
    total_warnings = sum(len(result.warnings) for result in results)

    print("[schema] ─────────────────────────────────────────────")
    print(f"[schema] Pages checked: {summary.pages_checked}")
    print(f"[schema] JSON-LD blocks found: {summary.blocks_found}")
    print(f"[schema] Issues: {summary.issues}")
    print(f"[schema] Errors: {total_errors}")
    print(f"[schema] Warnings: {total_warnings}")

    if total_errors:
        print("[schema] Validation failed")
        return 1

    print("[schema] Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
