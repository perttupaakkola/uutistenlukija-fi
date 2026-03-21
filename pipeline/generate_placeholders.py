#!/usr/bin/env python3
"""
generate_placeholders.py — Blur-up image placeholder generator

Fetches each article's hero image at 20px wide, base64-encodes it,
and writes the result as `image_placeholder` in frontmatter.

Usage:
  python3 generate_placeholders.py              # Process all articles missing placeholders
  python3 generate_placeholders.py --all        # Regenerate even existing placeholders
  python3 generate_placeholders.py --dry-run    # Show what would be done, no writes
  python3 generate_placeholders.py --limit 50   # Process at most N articles
  python3 generate_placeholders.py --article path/to/article.md
"""

import argparse
import base64
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# --- Config ---
CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
PLACEHOLDER_WIDTH = 20          # px — tiny enough for ~300-byte JPEG
REQUEST_DELAY = 0.15            # seconds between requests (rate limiting)
TIMEOUT = 10                    # seconds per HTTP request
MAX_RETRIES = 3


def build_tiny_url(url: str) -> str | None:
    """Return a 20px-wide variant URL for known CDN providers, or None."""
    if "images.unsplash.com" in url:
        # Strip existing w/q/fit params, add w=20&q=60&fit=crop
        base = url.split("?")[0]
        # Preserve other params (ixid, ixlib, etc.) for Unsplash licensing
        qs_parts = []
        if "?" in url:
            for kv in url.split("?", 1)[1].split("&"):
                key = kv.split("=")[0]
                if key not in ("w", "q", "fit", "fm", "cs"):
                    qs_parts.append(kv)
        qs_parts += [f"w={PLACEHOLDER_WIDTH}", "q=60", "fit=crop", "fm=jpg"]
        return f"{base}?{'&'.join(qs_parts)}"

    elif "images.pexels.com" in url:
        base = url.split("?")[0]
        return f"{base}?auto=compress&fit=crop&w={PLACEHOLDER_WIDTH}&q=60"

    # Unknown provider — no tiny variant available
    return None


def fetch_tiny(url: str) -> bytes | None:
    """Fetch URL bytes with retries. Returns None on failure."""
    headers = {"User-Agent": "uutistenlukija-placeholder/1.0"}
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 2)
                print(f"  429 rate limit — waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP {e.code} fetching placeholder: {url}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Fetch error ({attempt+1}/{MAX_RETRIES}): {e}", file=sys.stderr)
            time.sleep(1)
    return None


def make_data_uri(data: bytes) -> str:
    """Encode bytes as a JPEG data URI."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def parse_frontmatter(content: str) -> tuple[dict, str, str]:
    """
    Split file into (frontmatter_text, body, delimiter).
    Returns (raw_fm_str, body_str, delimiter) where delimiter is '---'.
    """
    if not content.startswith("---"):
        return None, content, ""
    end = content.find("\n---", 3)
    if end == -1:
        return None, content, ""
    fm = content[3:end].strip()
    body = content[end + 4:]
    return fm, body, "---"


def get_fm_value(fm: str, key: str) -> str | None:
    """Extract a scalar frontmatter value by key."""
    pattern = rf'^{re.escape(key)}:\s*["\']?([^"\'\n]+)["\']?\s*$'
    m = re.search(pattern, fm, re.MULTILINE)
    return m.group(1).strip() if m else None


def set_fm_value(fm: str, key: str, value: str) -> str:
    """Set or replace a scalar frontmatter key."""
    pattern = rf'^{re.escape(key)}:.*$'
    new_line = f'{key}: "{value}"'
    if re.search(pattern, fm, re.MULTILINE):
        return re.sub(pattern, new_line, fm, flags=re.MULTILINE)
    # Append before end
    return fm.rstrip() + f"\n{new_line}"


def process_article(path: Path, dry_run: bool, force: bool) -> str:
    """Process one article. Returns 'skipped', 'done', 'no_image', 'error'."""
    content = path.read_text(encoding="utf-8")
    fm, body, delim = parse_frontmatter(content)
    if fm is None:
        return "skipped"

    image_url = get_fm_value(fm, "image")
    if not image_url:
        return "no_image"

    existing = get_fm_value(fm, "image_placeholder")
    if existing and not force:
        return "skipped"

    tiny_url = build_tiny_url(image_url)
    if not tiny_url:
        return "skipped"

    if dry_run:
        print(f"  [dry-run] Would fetch: {tiny_url}")
        return "done"

    data = fetch_tiny(tiny_url)
    if not data:
        return "error"

    data_uri = make_data_uri(data)
    fm_new = set_fm_value(fm, "image_placeholder", data_uri)

    new_content = f"---\n{fm_new}\n---{body}"
    path.write_text(new_content, encoding="utf-8")
    return "done"


def main():
    parser = argparse.ArgumentParser(description="Generate blur-up image placeholders")
    parser.add_argument("--all",      action="store_true", help="Regenerate existing placeholders too")
    parser.add_argument("--dry-run",  action="store_true", help="Don't write files")
    parser.add_argument("--limit",    type=int, default=0,  help="Max articles to process")
    parser.add_argument("--article",  type=str, default="", help="Process a single article file")
    args = parser.parse_args()

    if args.article:
        paths = [Path(args.article)]
    else:
        paths = sorted(CONTENT_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    stats = {"done": 0, "skipped": 0, "no_image": 0, "error": 0}
    processed = 0

    for path in paths:
        if args.limit and processed >= args.limit:
            break

        result = process_article(path, dry_run=args.dry_run, force=args.all)
        stats[result] = stats.get(result, 0) + 1

        if result == "done":
            processed += 1
            size_note = ""
            if not args.dry_run:
                # Report data URI length for the written file
                content = path.read_text(encoding="utf-8")
                fm, _, _ = parse_frontmatter(content)
                ph = get_fm_value(fm, "image_placeholder")
                if ph:
                    size_note = f" ({len(ph)} chars)"
            print(f"  ✅ {path.name}{size_note}")
            if not args.dry_run:
                time.sleep(REQUEST_DELAY)
        elif result == "error":
            print(f"  ❌ {path.name}")

    print(f"\nDone: {stats['done']} written, {stats['skipped']} skipped, "
          f"{stats['no_image']} no image, {stats['error']} errors")


if __name__ == "__main__":
    main()
