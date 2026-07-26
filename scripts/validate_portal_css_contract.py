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
    "portal-day-digest",
]

LAYOUT_GUARDS = [
    ".portal-right-rail { display: grid; grid-column: 3; grid-row: 1 / span 2;",
    ".portal-day-digest {\n  grid-column: 1 / 3;\n  grid-row: 2;",
    "@media (max-width: 1180px)",
    "@media (max-width: 1020px)",
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

OPE_446_DARK_CONTRAST_GUARDS = [
    '[data-theme="dark"] .portal-livebar__all',
    '[data-theme="dark"] .portal-market dd',
    '[data-theme="dark"] .bc-current',
    '[data-theme="dark"] .portal-list-feature__body > p',
    '[data-theme="dark"] .portal-feed-item p',
    '[data-theme="dark"] .single-article > .category-label--badge',
]

OPE_446_CRITICAL_BADGE_GUARD = (
    '[data-theme="dark"] .single-article>.category-label--badge'
)

OPE_363_ARTICLE_BADGE_GUARD = (
    ".single-article > .category-label--badge.category-label--talous {\n"
    "  color: #071329 !important;\n"
    "}"
)
OPE_363_CRITICAL_ARTICLE_BADGE_GUARD = (
    ".single-article>.category-label--badge.category-label--talous"
    "{color:#071329!important}"
)

MOBILE_CONTAINER_WIDTH_GUARD = (
    ".container, main.container { width: 100% !important; max-width: 100% !important;"
)
CRITICAL_MOBILE_CONTAINER_WIDTH_GUARD = (
    "main.container,.container{width:100%!important;max-width:100%!important}"
)


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

        for selector in OPE_446_DARK_CONTRAST_GUARDS:
            if selector not in css:
                failures.append(f"{label} is missing OPE-446 contrast guard for {selector}")

        if OPE_363_ARTICLE_BADGE_GUARD not in css:
            failures.append(
                f"{label} is missing the OPE-363 article badge contrast guard"
            )

        for snippet in LAYOUT_GUARDS:
            if snippet not in css:
                failures.append(f"{label} is missing OPE-162 layout guard {snippet!r}")

        if MOBILE_CONTAINER_WIDTH_GUARD not in css:
            failures.append(
                f"{label} is missing the OPE-355 mobile 100% container width guard"
            )

    if css_by_path[CSS_FILES[0]] != css_by_path[CSS_FILES[1]]:
        failures.append("assets/css/portal-overhaul.css and static/css/portal-overhaul.css differ")

    for selector in CONTRAST_GUARDS:
        if selector not in critical_css:
            failures.append(
                f"{CRITICAL_CSS.relative_to(ROOT)} is missing OPE-158 contrast lock for {selector}"
            )

    if OPE_446_CRITICAL_BADGE_GUARD not in critical_css:
        failures.append(
            f"{CRITICAL_CSS.relative_to(ROOT)} is missing the OPE-446 article badge "
            "contrast lock"
        )

    if OPE_363_CRITICAL_ARTICLE_BADGE_GUARD not in critical_css:
        failures.append(
            f"{CRITICAL_CSS.relative_to(ROOT)} is missing the OPE-363 Talous article badge "
            "contrast lock"
        )

    if CRITICAL_MOBILE_CONTAINER_WIDTH_GUARD not in critical_css:
        failures.append(
            f"{CRITICAL_CSS.relative_to(ROOT)} is missing the OPE-355 critical mobile "
            "100% container width guard"
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
