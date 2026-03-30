#!/usr/bin/env python3
"""
Validate JSON-LD structured data in generated HTML.

Scans generated HTML files, extracts <script type="application/ld+json"> blocks,
and validates the schema for common rich-result types used by Uutistenlukija.

Default behavior is warn-only: validation issues are reported but do NOT fail the
pipeline. Use --strict to return a non-zero exit code when errors are found.

Supported schema checks:
- NewsArticle / Article
- BreadcrumbList
- FAQPage
- WebSite (homepage SearchAction sanity)

Usage:
    python3 scripts/validate_structured_data.py
    python3 scripts/validate_structured_data.py --public-dir public --verbose
    python3 scripts/validate_structured_data.py --strict
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

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PUBLIC_DIR = PROJECT_DIR / "public"
JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
ARTICLE_PATH_RE = re.compile(r"/posts/.+/index\.html$")


@dataclass
class ValidationResult:
    path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    block_count: int = 0
    validated_nodes: int = 0


@dataclass
class Summary:
    pages_checked: int = 0
    article_pages_checked: int = 0
    blocks_found: int = 0
    validated_nodes: int = 0
    warnings: int = 0
    errors: int = 0


REQUIRED_BY_TYPE: dict[str, tuple[str, ...]] = {
    "NewsArticle": ("headline", "datePublished", "dateModified", "author", "publisher", "image", "mainEntityOfPage"),
    "Article": ("headline", "datePublished", "dateModified", "author", "publisher", "image", "mainEntityOfPage"),
    "BreadcrumbList": ("itemListElement",),
    "FAQPage": ("mainEntity",),
    "WebSite": ("name", "url", "potentialAction"),
}


def is_absolute_url(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_iso8601(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
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


def find_type(types: list[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in types:
            return candidate
    return None


def validate_image(node: dict[str, Any], label: str, errors: list[str]) -> None:
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
        errors.append(f"{label}: image present but no usable URL found")
        return

    for url in urls:
        if not is_absolute_url(url):
            errors.append(f"{label}: image URL is not absolute: {url}")


def validate_author(author: Any, label: str, errors: list[str], warnings: list[str]) -> None:
    if isinstance(author, str):
        if not author.strip():
            errors.append(f"{label}: author must not be empty")
        return
    if isinstance(author, dict):
        if not author.get("name"):
            errors.append(f"{label}: author object missing name")
        return
    if isinstance(author, list):
        if not author:
            errors.append(f"{label}: author list is empty")
            return
        for idx, item in enumerate(author, start=1):
            if isinstance(item, str) and item.strip():
                continue
            if isinstance(item, dict) and item.get("name"):
                continue
            errors.append(f"{label}: author entry #{idx} invalid")
        return
    warnings.append(f"{label}: author has unusual type {type(author).__name__}")


def validate_publisher(publisher: Any, label: str, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(publisher, dict):
        errors.append(f"{label}: publisher must be an object")
        return
    if not publisher.get("name"):
        errors.append(f"{label}: publisher missing name")
    logo = publisher.get("logo")
    if logo is None:
        warnings.append(f"{label}: publisher logo missing")
    elif isinstance(logo, dict):
        if not is_absolute_url(str(logo.get("url", ""))):
            errors.append(f"{label}: publisher logo url must be absolute")
    else:
        warnings.append(f"{label}: publisher logo should be object")


def validate_main_entity(node: dict[str, Any], label: str, errors: list[str], warnings: list[str]) -> None:
    entity = node.get("mainEntityOfPage")
    if isinstance(entity, str):
        if not is_absolute_url(entity):
            errors.append(f"{label}: mainEntityOfPage string must be absolute URL")
        return
    if isinstance(entity, dict):
        entity_id = entity.get("@id") or entity.get("url")
        if not isinstance(entity_id, str) or not is_absolute_url(entity_id):
            errors.append(f"{label}: mainEntityOfPage object missing absolute @id/url")
        return
    warnings.append(f"{label}: mainEntityOfPage has unusual type {type(entity).__name__}")


def has_search_action(value: Any) -> bool:
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "SearchAction" in normalize_types(candidate.get("@type")):
            return True
    return False


def validate_breadcrumbs(node: dict[str, Any], label: str, errors: list[str], warnings: list[str]) -> None:
    items = node.get("itemListElement")
    if not isinstance(items, list) or not items:
        errors.append(f"{label}: BreadcrumbList itemListElement must be non-empty list")
        return

    last_position = 0
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"{label}: breadcrumb item #{idx} must be object")
            continue
        if item.get("@type") != "ListItem":
            warnings.append(f"{label}: breadcrumb item #{idx} @type should be ListItem")
        position = item.get("position")
        name = item.get("name")
        url = item.get("item") or item.get("url")
        if not isinstance(position, int):
            errors.append(f"{label}: breadcrumb item #{idx} missing integer position")
        else:
            if position <= last_position:
                warnings.append(f"{label}: breadcrumb positions not strictly increasing at #{idx}")
            last_position = position
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}: breadcrumb item #{idx} missing name")
        if not isinstance(url, str) or not is_absolute_url(url):
            errors.append(f"{label}: breadcrumb item #{idx} missing absolute item/url")


def validate_faq(node: dict[str, Any], label: str, errors: list[str], warnings: list[str]) -> None:
    entities = node.get("mainEntity")
    if not isinstance(entities, list) or not entities:
        errors.append(f"{label}: FAQPage mainEntity must be non-empty list")
        return

    for idx, item in enumerate(entities, start=1):
        if not isinstance(item, dict):
            errors.append(f"{label}: FAQ item #{idx} must be object")
            continue
        if item.get("@type") != "Question":
            warnings.append(f"{label}: FAQ item #{idx} @type should be Question")
        name = item.get("name")
        answer = item.get("acceptedAnswer")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}: FAQ item #{idx} missing question name")
        if not isinstance(answer, dict):
            errors.append(f"{label}: FAQ item #{idx} missing acceptedAnswer object")
            continue
        if answer.get("@type") != "Answer":
            warnings.append(f"{label}: FAQ item #{idx} acceptedAnswer @type should be Answer")
        text = answer.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{label}: FAQ item #{idx} acceptedAnswer missing text")


def validate_article_node(node: dict[str, Any], schema_type: str, label: str, errors: list[str], warnings: list[str]) -> None:
    for field_name in REQUIRED_BY_TYPE[schema_type]:
        if field_name not in node:
            errors.append(f"{label}: {schema_type} missing {field_name}")

    headline = node.get("headline")
    if isinstance(headline, str):
        if len(headline) > 110:
            warnings.append(f"{label}: headline exceeds 110 chars ({len(headline)})")
    elif headline is not None:
        errors.append(f"{label}: headline must be string")

    for field_name in ("datePublished", "dateModified"):
        value = node.get(field_name)
        if isinstance(value, str):
            if parse_iso8601(value) is None:
                errors.append(f"{label}: {field_name} is not valid ISO 8601: {value}")
        elif value is not None:
            errors.append(f"{label}: {field_name} must be string")

    if "datePublished" in node and "dateModified" in node:
        published = parse_iso8601(node.get("datePublished"))
        modified = parse_iso8601(node.get("dateModified"))
        if published and modified and modified < published:
            errors.append(f"{label}: dateModified is earlier than datePublished")

    if "isAccessibleForFree" in node and not isinstance(node["isAccessibleForFree"], bool):
        errors.append(f"{label}: isAccessibleForFree must be boolean")

    validate_author(node.get("author"), label, errors, warnings)
    validate_publisher(node.get("publisher"), label, errors, warnings)
    validate_image(node, label, errors)
    validate_main_entity(node, label, errors, warnings)

    url = node.get("url")
    if isinstance(url, str):
        if not is_absolute_url(url):
            errors.append(f"{label}: url must be absolute")
    elif url is not None:
        errors.append(f"{label}: url must be string")


def validate_website(node: dict[str, Any], label: str, errors: list[str], warnings: list[str]) -> None:
    for field_name in REQUIRED_BY_TYPE["WebSite"]:
        if field_name not in node:
            errors.append(f"{label}: WebSite missing {field_name}")

    url = node.get("url")
    if isinstance(url, str):
        if not is_absolute_url(url):
            errors.append(f"{label}: WebSite url must be absolute")
    elif url is not None:
        errors.append(f"{label}: WebSite url must be string")

    if "potentialAction" in node and not has_search_action(node.get("potentialAction")):
        errors.append(f"{label}: WebSite potentialAction missing SearchAction")

    publisher = node.get("publisher")
    if publisher is not None:
        validate_publisher(publisher, label, errors, warnings)


def validate_node(node: dict[str, Any], page_label: str, block_index: int, node_index: int, errors: list[str], warnings: list[str]) -> bool:
    label = f"{page_label} block #{block_index} node #{node_index}"
    types = normalize_types(node.get("@type"))
    if not types:
        errors.append(f"{label}: missing @type")
        return False

    schema_type = find_type(types, ("NewsArticle", "Article", "BreadcrumbList", "FAQPage", "WebSite"))
    if schema_type is None:
        return False

    if schema_type in {"NewsArticle", "Article"}:
        validate_article_node(node, schema_type, label, errors, warnings)
    elif schema_type == "BreadcrumbList":
        validate_breadcrumbs(node, label, errors, warnings)
    elif schema_type == "FAQPage":
        validate_faq(node, label, errors, warnings)
    elif schema_type == "WebSite":
        validate_website(node, label, errors, warnings)

    return True


def validate_page(path: Path) -> ValidationResult:
    result = ValidationResult(path=path)
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = JSONLD_RE.findall(text)
    result.block_count = len(blocks)

    page_label = str(path)
    for block_index, block in enumerate(blocks, start=1):
        payload_text = block.strip()
        if not payload_text:
            result.warnings.append(f"{page_label} block #{block_index}: empty JSON-LD block")
            continue

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            result.errors.append(f"{page_label} block #{block_index}: invalid JSON: {exc}")
            continue

        nodes = extract_nodes(payload)
        if not nodes:
            result.warnings.append(f"{page_label} block #{block_index}: no JSON-LD object nodes found")
            continue

        for node_index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                result.errors.append(f"{page_label} block #{block_index} node #{node_index}: node is not an object")
                continue
            if validate_node(node, page_label, block_index, node_index, result.errors, result.warnings):
                result.validated_nodes += 1

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate JSON-LD structured data in generated HTML.")
    parser.add_argument("--public-dir", default=str(DEFAULT_PUBLIC_DIR), help="Directory containing generated site HTML.")
    parser.add_argument("--verbose", action="store_true", help="Print clean pages too.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero exit code if validation errors are found.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    public_dir = Path(args.public_dir)
    if not public_dir.is_absolute():
        public_dir = PROJECT_DIR / public_dir

    if not public_dir.exists():
        print(f"[schema] public dir not found: {public_dir}")
        return 1 if args.strict else 0

    html_pages = sorted(public_dir.rglob("*.html"))
    if not html_pages:
        print(f"[schema] no HTML files found under {public_dir}")
        return 1 if args.strict else 0

    results: list[ValidationResult] = []
    summary = Summary(pages_checked=len(html_pages))

    for path in html_pages:
        result = validate_page(path)
        results.append(result)
        summary.blocks_found += result.block_count
        summary.validated_nodes += result.validated_nodes
        summary.warnings += len(result.warnings)
        summary.errors += len(result.errors)
        if ARTICLE_PATH_RE.search(path.as_posix()):
            summary.article_pages_checked += 1

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
                f"[schema] {rel} — blocks={result.block_count}, validated={result.validated_nodes}, warnings={len(result.warnings)}, errors={len(result.errors)}"
            )
        for warning in result.warnings:
            print(f"[schema]   WARN {warning}")
        for error in result.errors:
            print(f"[schema]   ERR  {error}")

    print("[schema] ─────────────────────────────────────────────")
    print(f"[schema] Pages checked: {summary.pages_checked}")
    print(f"[schema] Article pages checked: {summary.article_pages_checked}")
    print(f"[schema] JSON-LD blocks found: {summary.blocks_found}")
    print(f"[schema] Validated nodes: {summary.validated_nodes}")
    print(f"[schema] Summary: {summary.validated_nodes} validated, {summary.warnings} warnings, {summary.errors} errors")

    if summary.errors:
        print("[schema] Validation completed with errors (warn-only mode)")
    elif summary.warnings:
        print("[schema] Validation completed with warnings")
    else:
        print("[schema] Validation passed cleanly")

    if args.strict and summary.errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
