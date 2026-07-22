#!/usr/bin/env python3
"""
extract_critical_css.py — Critical CSS extractor for uutistenlukija.fi

Reads themes/uutistenlukija/static/css/style.css and emits
layouts/partials/critical-css.html containing only the rules needed
for above-the-fold rendering.

Target: ≤14KB (fits in first TCP congestion window)

Usage:
    python3 pipeline/extract_critical_css.py [--check]

    --check: exit 1 if generated output differs from existing file
             (use in CI to detect stale critical CSS)
"""

import re
import sys
import os
import textwrap
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CSS_SRC  = ROOT / "themes/uutistenlukija/static/css/style.css"
OUT_FILE = ROOT / "layouts/partials/critical-css.html"

# ── Selector patterns that are above-the-fold ─────────────────────────────────
# A rule is included if ANY selector in the rule matches one of these patterns.
# Patterns are matched against the full selector string (lowercased).
CRITICAL_SELECTOR_PATTERNS: list[str] = [
    # Reset / globals
    r"^\*",
    r"^:root",
    r"^\[data-theme",
    r"^html\b",
    r"^body\b",
    r"^a\b",
    r"^a:",
    r"^img\b",
    # Layout
    r"\.container\b",
    # Skip link
    r"\.skip-to-content",
    r"\.skip-link",
    # Reading progress bar (fixed, appears on top)
    r"\.reading-progress\b",
    # Header / nav
    r"\.site-header\b",
    r"\.header-banner\b",
    r"\.site-logo\b",
    r"\.logo-img\b",
    r"\.site-title\b",
    r"\.site-subtitle\b",
    r"\.site-date\b",
    r"\.header-inner\b",
    r"\.header-controls\b",
    r"\.main-nav\b",
    # Theme toggle (in header)
    r"\.theme-toggle\b",
    r"\.theme-toggle-icon\b",
    r"\.theme-toggle-label\b",
    # Category pills / labels — needed for first card
    r"\.category-pill\b",
    r"\.category-label\b",
    r"\.category-kotimaa\b",
    r"\.category-ulkomaat\b",
    r"\.category-talous\b",
    r"\.category-teknologia\b",
    r"\.category-urheilu\b",
    r"\.category-kulttuuri\b",
    r"\.category-tiede\b",
    # Lead article (first visible content)
    r"\.lead-article\b",
    # Pub-frequency bar (just below header)
    r"\.pub-frequency-bar\b",
    r"\.pub-freq-dot\b",
    # Highlights row (above fold on large screens)
    r"\.highlights-row\b",
    r"\.highlight-card\b",
    # Article card shell (first card in viewport)
    r"\.article-card\b",
    r"\.articles-grid\b",
    # Article image / thumbnail (image-link is above fold)
    r"\.article-image\b",
    r"\.article-image-link\b",
    # Hero image (single article pages — above fold)
    r"\.article-hero\b",
    r"\.article-hero-wrapper\b",
    r"\.article-hero-img\b",
    # Focus styles
    r":focus-visible",
    r":focus:not",
]

# ── @keyframes that critical rules reference ───────────────────────────────────
CRITICAL_KEYFRAMES: list[str] = [
    "shimmer",
    "pulse-dot",
    "spin",
]

PORTAL_OVERHAUL_CRITICAL_LOCKS = """
/* OPE-158 dark portal contrast locks; keep in sync with portal-overhaul.css. */
[data-theme="dark"] .portal-livebar time { color: #f0b8ad !important; }
[data-theme="dark"] .single-article > .category-label--badge { color: var(--portal-text, #fff) !important; }
[data-theme="dark"] .portal-kicker,
[data-theme="dark"] .portal-teaser__meta,
[data-theme="dark"] .portal-row-card .portal-kicker,
[data-theme="dark"] .portal-row-card__time,
[data-theme="dark"] .portal-section-label { color: #d7cfc3 !important; }
[data-theme="dark"] .portal-lead .portal-kicker { background: #0b49ad; color: #fff !important; }
[data-theme="dark"] .portal-newsletter,
[data-theme="dark"] .newsletter-band,
[data-theme="dark"] .newsletter-signup__inner { background: #fffdf9 !important; border-color: #ddd4c8 !important; color: #171513 !important; }
[data-theme="dark"] .portal-newsletter h2,
[data-theme="dark"] .newsletter-band__heading,
[data-theme="dark"] .newsletter-signup__title { color: #171513 !important; }
[data-theme="dark"] .portal-newsletter p,
[data-theme="dark"] .newsletter-band__text,
[data-theme="dark"] .newsletter-band__privacy,
[data-theme="dark"] .newsletter-signup__text,
[data-theme="dark"] .newsletter-signup__note { color: #6f685f !important; }
"""

# ── @media that we must include (mobile critical overrides) ───────────────────
# Only media blocks where ALL rules inside are critical — we filter rule-by-rule.
CRITICAL_MEDIA_MAX_WIDTH_PX = 900  # include breakpoints up to this value

# ── Minification helpers ───────────────────────────────────────────────────────

def minify_css(css: str) -> str:
    """Light minification: remove comments, collapse whitespace."""
    # Strip block comments
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    # Normalise newlines
    css = re.sub(r"\r\n|\r", "\n", css)
    # Collapse runs of whitespace to single space
    css = re.sub(r"[ \t]+", " ", css)
    # Remove newlines around punctuation
    css = re.sub(r"\s*\{\s*", "{", css)
    css = re.sub(r"\s*\}\s*", "}", css)
    css = re.sub(r"\s*;\s*", ";", css)
    css = re.sub(r"\s*:\s*", ":", css)
    css = re.sub(r"\s*,\s*", ",", css)
    # Remove last semicolon before closing brace
    css = re.sub(r";}", "}", css)
    # Strip leading/trailing whitespace
    css = css.strip()
    return css


# ── CSS block parser ───────────────────────────────────────────────────────────

class CSSBlock:
    """Represents a top-level CSS block (rule, @keyframes, @media, etc.)"""
    def __init__(self, raw: str):
        self.raw = raw.strip()

    def is_rule(self) -> bool:
        return not self.raw.startswith("@")

    def is_keyframes(self) -> bool:
        return self.raw.startswith("@keyframes")

    def is_media(self) -> bool:
        return self.raw.startswith("@media")

    def is_other_at_rule(self) -> bool:
        return self.raw.startswith("@") and not self.is_keyframes() and not self.is_media()

    def selector(self) -> str:
        """Return everything before the first '{' (the selector string)."""
        idx = self.raw.find("{")
        return self.raw[:idx].strip() if idx >= 0 else ""

    def keyframe_name(self) -> str:
        m = re.match(r"@keyframes\s+(\S+)", self.raw)
        return m.group(1) if m else ""

    def media_query(self) -> str:
        m = re.match(r"(@media[^{]+)", self.raw)
        return m.group(1).strip() if m else ""

    def inner_rules(self) -> list[str]:
        """Extract individual rules from inside a @media block."""
        start = self.raw.find("{")
        end   = self.raw.rfind("}")
        if start < 0 or end < 0:
            return []
        inner = self.raw[start+1:end]
        return _split_top_level_blocks(inner)


def _split_top_level_blocks(css: str) -> list[str]:
    """Split CSS text into top-level blocks, respecting nested braces."""
    blocks = []
    depth = 0
    start = 0
    i = 0
    while i < len(css):
        c = css[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                block = css[start:i+1].strip()
                if block:
                    blocks.append(block)
                start = i + 1
        i += 1
    return blocks


def _selector_is_critical(selector: str) -> bool:
    """Return True if the selector matches any critical pattern."""
    sel_lower = selector.lower()
    for pattern in CRITICAL_SELECTOR_PATTERNS:
        if re.search(pattern, sel_lower):
            return True
    return False


def _media_max_width(media_query: str) -> int | None:
    """Extract max-width value in px from a media query, or None."""
    m = re.search(r"max-width\s*:\s*(\d+)px", media_query)
    return int(m.group(1)) if m else None


# ── Main extraction logic ──────────────────────────────────────────────────────

def extract_critical(css_src: str) -> str:
    """
    Parse css_src and return a minified string of critical CSS rules.
    """
    # Remove comments first
    css_src = re.sub(r"/\*.*?\*/", "", css_src, flags=re.DOTALL)

    blocks = _split_top_level_blocks(css_src)
    critical_parts: list[str] = []

    for raw in blocks:
        block = CSSBlock(raw)

        if block.is_rule():
            if _selector_is_critical(block.selector()):
                critical_parts.append(raw)

        elif block.is_keyframes():
            if block.keyframe_name() in CRITICAL_KEYFRAMES:
                critical_parts.append(raw)

        elif block.is_media():
            mq = block.media_query()
            max_w = _media_max_width(mq)
            # Include media blocks up to CRITICAL_MEDIA_MAX_WIDTH_PX
            # Filter rules inside to only critical selectors
            if max_w is None or max_w <= CRITICAL_MEDIA_MAX_WIDTH_PX:
                inner_rules = block.inner_rules()
                critical_inner = [
                    r for r in inner_rules
                    if _selector_is_critical(CSSBlock(r).selector())
                ]
                if critical_inner:
                    inner_css = " ".join(critical_inner)
                    critical_parts.append(f"{mq} {{ {inner_css} }}")

        # @charset, @import, other at-rules: skip

    combined = "\n".join([*critical_parts, PORTAL_OVERHAUL_CRITICAL_LOCKS])
    return minify_css(combined)


# ── Partial template wrapper ───────────────────────────────────────────────────

PARTIAL_HEADER = """\
{{/*
  critical-css.html — Above-the-fold critical CSS (auto-generated)

  Generated by: pipeline/extract_critical_css.py
  Source:       themes/uutistenlukija/static/css/style.css

  DO NOT EDIT MANUALLY — regenerate with:
      python3 pipeline/extract_critical_css.py

  Target: ≤14KB (first TCP round-trip)
  Covers: reset, CSS vars, header, nav, category pills, lead article,
          article card shell, hero image, highlights row, focus styles,
          reading progress bar, pub-frequency bar.

  The full stylesheet is loaded asynchronously after first paint.
*/}}
<style>
"""

PARTIAL_FOOTER = """
</style>
"""


def wrap_partial(css: str) -> str:
    return PARTIAL_HEADER + css + PARTIAL_FOOTER


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    check_mode = "--check" in sys.argv

    if not CSS_SRC.exists():
        print(f"ERROR: CSS source not found: {CSS_SRC}", file=sys.stderr)
        sys.exit(1)

    css_src = CSS_SRC.read_text(encoding="utf-8")
    critical_css = extract_critical(css_src)
    byte_size = len(critical_css.encode("utf-8"))

    output = wrap_partial(critical_css)

    if check_mode:
        if OUT_FILE.exists():
            existing = OUT_FILE.read_text(encoding="utf-8")
            if existing != output:
                print(f"STALE: {OUT_FILE} differs from generated output.", file=sys.stderr)
                print(f"Run: python3 pipeline/extract_critical_css.py", file=sys.stderr)
                sys.exit(1)
            else:
                print("OK: critical-css.html is up-to-date.")
                sys.exit(0)
        else:
            print(f"MISSING: {OUT_FILE}", file=sys.stderr)
            sys.exit(1)

    # Write output
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(output, encoding="utf-8")

    print(f"Written: {OUT_FILE}")
    print(f"Critical CSS size: {byte_size:,} bytes ({byte_size / 1024:.1f} KB)")

    if byte_size > 14 * 1024:
        print(f"WARNING: exceeds 14KB target ({byte_size / 1024:.1f} KB > 14 KB)", file=sys.stderr)
        print("Consider removing less-critical selectors from CRITICAL_SELECTOR_PATTERNS.")
    else:
        print(f"OK: within 14KB limit.")


if __name__ == "__main__":
    main()
