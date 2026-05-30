#!/usr/bin/env python3
"""Validate the homepage portal CSS targets the live header/frontpage markup.

This is a narrow regression guard for the OPE-150 incident: a stylesheet aimed at
obsolete header classes can pass Hugo but leave the public homepage visually broken.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "layouts" / "partials" / "header.html"
INDEX = ROOT / "layouts" / "index.html"
CSS_FILES = [
    ROOT / "assets" / "css" / "portal-overhaul.css",
    ROOT / "static" / "css" / "portal-overhaul.css",
]

HEADER_CLASSES = [
    "portal-masthead",
    "portal-logo",
    "portal-logo__image",
    "portal-search",
    "portal-actions",
    "portal-weather",
    "portal-icon-button",
    "hamburger-btn",
    "main-nav",
]

FRONTPAGE_CLASSES = [
    "portal-front-grid",
    "portal-lead",
    "portal-center-list",
    "portal-right-rail",
]

OBSOLETE_HEADER_SELECTORS = [
    ".header-inner",
    ".header-main-row",
    ".site-logo",
    ".logo-img",
]


def require(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def main() -> int:
    header = require(HEADER)
    index = require(INDEX)
    failures: list[str] = []

    for class_name in HEADER_CLASSES:
        if class_name not in header:
            failures.append(f"header markup missing expected class: {class_name}")

    for class_name in FRONTPAGE_CLASSES:
        if class_name not in index:
            failures.append(f"homepage markup missing expected class: {class_name}")

    for css_path in CSS_FILES:
        css = require(css_path)
        label = css_path.relative_to(ROOT)

        for class_name in HEADER_CLASSES + FRONTPAGE_CLASSES:
            selector = f".{class_name}"
            if selector not in css:
                failures.append(f"{label} does not style live selector {selector}")

        for selector in OBSOLETE_HEADER_SELECTORS:
            if selector in css and selector[1:] not in header:
                failures.append(
                    f"{label} styles obsolete header selector {selector}; "
                    "update CSS to target live portal-* header markup"
                )

    if failures:
        print("Portal CSS contract validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Portal CSS contract validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
