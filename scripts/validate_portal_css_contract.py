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
CRITICAL_CSS = ROOT / "layouts" / "partials" / "critical-css.html"

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

MOBILE_SURFACE_LINK_GUARDS = [
    ".portal-lead h2 a",
    ".portal-save-link",
    ".portal-mobile-section-head h2",
    ".portal-teaser h3 a",
    ".portal-row-card h3 a",
]

CONTRAST_GUARDS = [
    '[data-theme="dark"] .portal-livebar time',
    '[data-theme="dark"] .portal-kicker',
    '[data-theme="dark"] .portal-newsletter',
    '[data-theme="dark"] .portal-newsletter h2',
    '[data-theme="dark"] .newsletter-signup__inner',
    '[data-theme="dark"] .newsletter-signup__title',
]


def require(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def main() -> int:
    header = require(HEADER)
    index = require(INDEX)
    css_by_path = {css_path: require(css_path) for css_path in CSS_FILES}
    critical_css = require(CRITICAL_CSS)
    failures: list[str] = []

    for class_name in HEADER_CLASSES:
        if class_name not in header:
            failures.append(f"header markup missing expected class: {class_name}")

    for class_name in FRONTPAGE_CLASSES:
        if class_name not in index:
            failures.append(f"homepage markup missing expected class: {class_name}")

    for css_path, css in css_by_path.items():
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

        for selector in MOBILE_SURFACE_LINK_GUARDS:
            if selector not in css:
                failures.append(
                    f"{label} is missing mobile light-surface color guard for {selector}"
                )

        for selector in CONTRAST_GUARDS:
            if selector not in css:
                failures.append(f"{label} is missing OPE-158 contrast guard for {selector}")

    if css_by_path[CSS_FILES[0]] != css_by_path[CSS_FILES[1]]:
        failures.append("assets/css/portal-overhaul.css and static/css/portal-overhaul.css differ")

    for selector in CONTRAST_GUARDS:
        if selector not in critical_css:
            failures.append(
                f"{CRITICAL_CSS.relative_to(ROOT)} is missing OPE-158 contrast lock for {selector}"
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
