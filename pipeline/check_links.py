#!/usr/bin/env python3
"""
check_links.py — Internal link checker for the Hugo public/ build output.

Scans every HTML file under public/, finds all <a href="..."> internal links,
and verifies that the target file or directory index exists on disk.

Usage:
    python3 pipeline/check_links.py [--public-dir /path/to/public]
                                    [--fail-on-broken]

Exit codes:
    0 — no broken links (or public/ not found)
    1 — broken links found (only when --fail-on-broken is set)

Output:
    pipeline/logs/link_check.log  — always written
    Discord webhook alert          — sent only when broken links are found
                                     and DISCORD_PIPELINE_WEBHOOK is set
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ── Config ────────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "link_check.log"

# Anchor-only links and mailto/tel/javascript are never internal page links
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "javascript:", "ftp://", "//")
# Common Hugo output patterns that signal a valid path even without an index
# e.g. /rss.xml, /sitemap.xml, /manifest.json, /favicon.ico, /robots.txt
KNOWN_ASSET_EXTENSIONS = {
    ".xml", ".json", ".txt", ".ico", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".svg", ".css", ".js", ".woff", ".woff2",
    ".ttf", ".eot", ".pdf", ".mp4", ".mp3", ".zip",
}


# ── HTML parser ───────────────────────────────────────────────────────────────

class LinkExtractor(HTMLParser):
    """Extracts href values from <a> tags."""

    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


# ── Core logic ────────────────────────────────────────────────────────────────

def extract_links(html_content: str) -> List[str]:
    parser = LinkExtractor()
    parser.feed(html_content)
    return parser.links


def is_internal(href: str) -> bool:
    """Return True if href is an internal link (starts with / or is relative)."""
    href = href.strip()
    if not href or href.startswith("#"):
        return False
    for scheme in SKIP_SCHEMES:
        if href.startswith(scheme):
            return False
    return True


def normalise_href(href: str) -> str:
    """Strip query string and fragment, keep path only."""
    href = href.split("?")[0].split("#")[0]
    return href


def resolve_target(href: str, public_dir: Path) -> Path:
    """
    Map a root-relative href to the expected file in public/.

    Hugo outputs:
      /foo/bar/   →  public/foo/bar/index.html
      /foo/bar    →  public/foo/bar (exact file) OR public/foo/bar/index.html
      /rss.xml    →  public/rss.xml
    """
    # Strip leading slash for joining
    rel = href.lstrip("/")
    target = public_dir / rel

    # If the path has a known asset extension, check it directly
    if target.suffix.lower() in KNOWN_ASSET_EXTENSIONS:
        return target

    # Prefer directory index
    if target.is_dir():
        return target / "index.html"

    # Try adding index.html
    if (target / "index.html").exists():
        return target / "index.html"

    # Exact file match (no extension, Hugo sometimes outputs extensionless)
    return target


def check_links(public_dir: Path) -> Dict[str, List[str]]:
    """
    Walk all .html files in public_dir, check internal links.

    Returns dict: source_file_path → [broken_href, ...]
    Only includes files that have at least one broken link.
    """
    broken: Dict[str, List[str]] = defaultdict(list)
    # Collect all hrefs seen to avoid re-checking duplicates
    checked_cache: Dict[str, bool] = {}

    html_files = list(public_dir.rglob("*.html"))
    total_files = len(html_files)
    total_links = 0
    total_broken = 0

    for html_file in html_files:
        try:
            content = html_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        links = extract_links(content)
        for raw_href in links:
            if not is_internal(raw_href):
                continue

            href = normalise_href(raw_href)
            if not href:
                continue

            total_links += 1

            if href in checked_cache:
                if not checked_cache[href]:
                    broken[str(html_file)].append(href)
                    total_broken += 1
                continue

            target = resolve_target(href, public_dir)
            exists = target.exists()
            checked_cache[href] = exists

            if not exists:
                broken[str(html_file)].append(href)
                total_broken += 1

    return dict(broken), total_files, total_links, total_broken


# ── Discord alert ─────────────────────────────────────────────────────────────

def notify_discord(broken: Dict[str, List[str]], total_broken: int) -> None:
    if not DISCORD_WEBHOOK_URL:
        print("[check_links] DISCORD_PIPELINE_WEBHOOK not set — skipping alert")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build a compact summary (Discord 2000-char limit)
    lines = [
        f"🔗 **Broken internal links found** — `{total_broken}` broken links in {len(broken)} file(s)",
        f"**Time:** {timestamp}",
        "",
        "**Sample broken links:**",
    ]
    sample_count = 0
    for src_file, hrefs in sorted(broken.items()):
        src_short = "/" + "/".join(Path(src_file).parts[-3:])  # last 3 path components
        for href in hrefs[:3]:  # max 3 per file
            lines.append(f"  `{src_short}` → `{href}`")
            sample_count += 1
            if sample_count >= 10:
                break
        if sample_count >= 10:
            if total_broken > 10:
                lines.append(f"  … and {total_broken - 10} more. See link_check.log for full list.")
            break

    body = "\n".join(lines)[:1900]  # safety margin

    payload = json.dumps({"content": body}).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                print("[check_links] Discord alert sent")
            else:
                print(f"[check_links] Discord alert got HTTP {resp.status}")
    except Exception as exc:
        print(f"[check_links] Discord alert failed: {exc}")


# ── Logging ───────────────────────────────────────────────────────────────────

def write_log(
    broken: Dict[str, List[str]],
    total_files: int,
    total_links: int,
    total_broken: int,
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"Link check run: {timestamp}\n")
        f.write(f"Files scanned:  {total_files}\n")
        f.write(f"Internal links: {total_links}\n")
        f.write(f"Broken links:   {total_broken}\n")
        f.write(f"{'='*70}\n")

        if not broken:
            f.write("✅ All internal links OK\n")
        else:
            f.write(f"❌ {total_broken} broken link(s) found:\n\n")
            for src_file in sorted(broken):
                f.write(f"  {src_file}\n")
                for href in broken[src_file]:
                    f.write(f"    → {href}\n")
                f.write("\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Check internal links in Hugo public/ output")
    parser.add_argument(
        "--public-dir",
        default=str(Path(__file__).parent.parent / "public"),
        help="Path to Hugo public/ directory (default: ../public relative to this script)",
    )
    parser.add_argument(
        "--fail-on-broken",
        action="store_true",
        help="Exit with code 1 if broken links are found",
    )
    args = parser.parse_args()

    public_dir = Path(args.public_dir)

    if not public_dir.exists():
        print(f"[check_links] public/ dir not found at {public_dir} — skipping")
        # Write a note to the log so the step is traceable
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(LOG_FILE, "a") as f:
            f.write(f"\n{'='*70}\n")
            f.write(f"Link check run: {timestamp}\n")
            f.write(f"SKIPPED — public/ not found at {public_dir}\n")
        return 0

    print(f"[check_links] Scanning {public_dir} ...")
    broken, total_files, total_links, total_broken = check_links(public_dir)

    write_log(broken, total_files, total_links, total_broken)

    if broken:
        print(f"[check_links] ❌ {total_broken} broken link(s) in {len(broken)} file(s)")
        notify_discord(broken, total_broken)
    else:
        print(f"[check_links] ✅ All {total_links} internal links OK across {total_files} files")

    if args.fail_on_broken and broken:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
