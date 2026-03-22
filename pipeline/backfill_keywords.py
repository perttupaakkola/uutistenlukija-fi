#!/usr/bin/env python3
"""
Backfill 'keywords' frontmatter into existing articles that are missing it.

Reads each article's category, looks up seo_keywords.json, and inserts
'keywords:' frontmatter (top 3 primary) before the closing '---'.

Usage:
    python3 pipeline/backfill_keywords.py            # dry-run
    python3 pipeline/backfill_keywords.py --apply    # write changes
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

POSTS_DIR = Path(__file__).parent.parent / "content" / "posts"
SEO_KEYWORDS_PATH = Path(__file__).parent / "seo_keywords.json"


def load_keywords() -> dict:
    with open(SEO_KEYWORDS_PATH) as f:
        return json.load(f)


def get_frontmatter_bounds(text: str):
    """Return (start, end) line indices (inclusive) of the YAML frontmatter block.
    Returns None if no frontmatter found.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return (0, i)
    return None


def parse_frontmatter_value(lines: list, key: str):
    """Extract a simple scalar value for 'key:' from frontmatter lines."""
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+)$")
    for line in lines:
        m = pattern.match(line.rstrip())
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def parse_category(lines: list) -> str | None:
    """Extract first category from frontmatter (handles YAML list format)."""
    in_categories = False
    for line in lines:
        stripped = line.strip()
        if stripped == "categories:":
            in_categories = True
            continue
        if in_categories:
            if stripped.startswith("-"):
                return stripped.lstrip("- ").strip().strip('"').strip("'")
            if stripped and not stripped.startswith("#"):
                break
    return None


def has_keywords(lines: list) -> bool:
    """Check if frontmatter already has a 'keywords:' key."""
    for line in lines:
        if re.match(r"^keywords\s*:", line):
            return True
    return False


def build_keywords_block(keywords: list) -> str:
    """Build the YAML keywords block string."""
    lines = ["keywords:\n"]
    for kw in keywords:
        escaped = kw.replace('"', '\\"')
        lines.append(f'  - "{escaped}"\n')
    return "".join(lines)


def process_file(path: Path, kw_data: dict, apply: bool) -> str | None:
    """Process one article file. Returns category name if updated, None if skipped."""
    text = path.read_text(encoding="utf-8")
    bounds = get_frontmatter_bounds(text)
    if bounds is None:
        return None

    start, end = bounds
    lines = text.splitlines(keepends=True)
    fm_lines = lines[start + 1:end]  # lines between the two '---'

    if has_keywords(fm_lines):
        return None  # already has keywords

    category = parse_category(fm_lines)
    if not category:
        return None

    cat_data = kw_data.get(category)
    if not cat_data:
        return None

    primary_kws = cat_data.get("primary", [])[:3]
    if not primary_kws:
        return None

    # Insert keywords block just before the closing '---'
    keywords_block = build_keywords_block(primary_kws)
    new_lines = lines[:end] + [keywords_block] + lines[end:]
    new_text = "".join(new_lines)

    if apply:
        path.write_text(new_text, encoding="utf-8")

    return category


def main():
    parser = argparse.ArgumentParser(description="Backfill keywords frontmatter into articles.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()

    kw_data = load_keywords()

    posts = sorted(POSTS_DIR.glob("*.md"))
    if not posts:
        print(f"No articles found in {POSTS_DIR}")
        sys.exit(1)

    updated_by_category: dict[str, int] = defaultdict(int)
    skipped = 0
    total = len(posts)

    for path in posts:
        cat = process_file(path, kw_data, apply=args.apply)
        if cat:
            updated_by_category[cat] += 1
        else:
            skipped += 1

    updated_total = sum(updated_by_category.values())
    mode = "APPLIED" if args.apply else "DRY RUN"

    print(f"\n{'=' * 50}")
    print(f"Backfill keywords — {mode}")
    print(f"{'=' * 50}")
    print(f"Total articles scanned : {total}")
    print(f"Articles to update     : {updated_total}")
    print(f"Already have keywords  : {skipped}")
    print()
    if updated_by_category:
        print("By category:")
        for cat in sorted(updated_by_category):
            print(f"  {cat:<15} {updated_by_category[cat]}")
    else:
        print("Nothing to update.")

    if not args.apply and updated_total > 0:
        print(f"\nRun with --apply to write {updated_total} files.")


if __name__ == "__main__":
    main()
