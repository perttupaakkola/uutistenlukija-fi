#!/usr/bin/env python3
"""
check_links.py — Post-deploy internal link checker for uutistenlukija.fi

Crawls internal URLs from the live sitemap, HEAD-checks each one,
reports 404s and other errors. External links are skipped (too slow for CI).

Usage:
    python3 check_links.py [--base-url URL] [--limit N] [--timeout S] [--dry-run]

Env:
    DISCORD_PIPELINE_WEBHOOK — if set, posts alert when broken links found

Output:
    pipeline/logs/link_check.log  — TSV: timestamp TAB status TAB url TAB note
    exit code 0 = all ok, exit code 1 = broken links found
"""

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL      = "https://uutistenlukija.fi"
SITEMAP_URL   = f"{BASE_URL}/sitemap.xml"
LOG_DIR       = Path(__file__).parent / "logs"
LINK_LOG      = LOG_DIR / "link_check.log"
REQUEST_DELAY = 0.15   # seconds between requests (polite crawling)
DEFAULT_LIMIT = 200    # max URLs to check per run
DEFAULT_TIMEOUT = 10   # seconds per request

# Load env from .env if present
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _k, _, _v = _line.partition("=")
        if _k.strip() and not _k.startswith("#"):
            os.environ.setdefault(_k.strip(), _v.strip())

DISCORD_WEBHOOK = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")


# ── Sitemap fetch ──────────────────────────────────────────────────────────────

def fetch_sitemap_urls(sitemap_url: str, timeout: int = 10) -> list[str]:
    """Fetch and parse XML sitemap(s), return list of internal URLs."""
    urls = []
    try:
        req = urllib.request.Request(
            sitemap_url,
            headers={"User-Agent": "UutistenlukijaLinkChecker/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"[check_links] ERROR fetching sitemap {sitemap_url}: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[check_links] ERROR parsing sitemap XML: {e}", file=sys.stderr)
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Sitemap index — recursively fetch child sitemaps
    for sitemap_elem in root.findall("sm:sitemap/sm:loc", ns):
        child_url = sitemap_elem.text.strip()
        if child_url and child_url.startswith(BASE_URL):
            print(f"[check_links] Loading child sitemap: {child_url}")
            urls.extend(fetch_sitemap_urls(child_url, timeout=timeout))

    # Regular URL set
    for url_elem in root.findall("sm:url/sm:loc", ns):
        u = url_elem.text.strip() if url_elem.text else ""
        if u and u.startswith(BASE_URL):
            urls.append(u)

    return urls


# ── URL check ─────────────────────────────────────────────────────────────────

def check_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str]:
    """HEAD-check a URL. Returns (status_code, note)."""
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={
                "User-Agent": "UutistenlukijaLinkChecker/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        return e.code, str(e.reason)
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"
    except TimeoutError:
        return 0, "timeout"
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


# ── Logging ───────────────────────────────────────────────────────────────────

def log_result(ts: str, status: int, url: str, note: str = "") -> None:
    """Append one TSV line to link_check.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{ts}\t{status}\t{url}\t{note}\n"
    with open(LINK_LOG, "a", encoding="utf-8") as f:
        f.write(line)


# ── Discord alert ─────────────────────────────────────────────────────────────

def notify_discord(broken: list[tuple[int, str, str]], total_checked: int) -> None:
    """Post broken link summary to Discord webhook."""
    import json as _json
    if not DISCORD_WEBHOOK:
        print("[check_links] DISCORD_PIPELINE_WEBHOOK not set — skipping alert")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"🔗 **Broken internal links found** ({len(broken)}/{total_checked} checked)"]
    lines.append(f"**Time:** {ts}")
    for status, url, note in broken[:10]:  # cap at 10 to stay under Discord 2000 char limit
        path = url.replace(BASE_URL, "") or "/"
        lines.append(f"  `{status}` — `{path}`{' — ' + note if note else ''}")
    if len(broken) > 10:
        lines.append(f"  …and {len(broken) - 10} more (see link_check.log)")

    body = "\n".join(lines)
    payload = _json.dumps({"content": body}).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 204)
            print(f"[check_links] Discord alert sent: {resp.status}")
    except Exception as e:
        print(f"[check_links] Discord alert failed: {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Internal link checker for uutistenlukija.fi")
    parser.add_argument("--base-url",  default=BASE_URL,      help="Site base URL")
    parser.add_argument("--limit",     type=int, default=DEFAULT_LIMIT, help="Max URLs to check")
    parser.add_argument("--timeout",   type=int, default=DEFAULT_TIMEOUT, help="Request timeout (s)")
    parser.add_argument("--delay",     type=float, default=REQUEST_DELAY, help="Delay between requests (s)")
    parser.add_argument("--dry-run",   action="store_true", help="Print results, don't write log or post Discord")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord notification")
    args = parser.parse_args()

    ts_run = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[check_links] Starting at {ts_run}")
    print(f"[check_links] Fetching sitemap: {SITEMAP_URL}")

    urls = fetch_sitemap_urls(SITEMAP_URL, timeout=args.timeout)
    if not urls:
        print("[check_links] No URLs found in sitemap — aborting", file=sys.stderr)
        return 1

    # Deduplicate, sort, cap
    urls = sorted(set(urls))
    total_available = len(urls)
    if len(urls) > args.limit:
        # Prioritise homepage + recent paths; cap the rest
        priority = [u for u in urls if u in (BASE_URL, BASE_URL + "/")]
        rest = [u for u in urls if u not in priority]
        urls = priority + rest[:args.limit - len(priority)]

    print(f"[check_links] Checking {len(urls)}/{total_available} URLs (limit={args.limit})")

    broken   : list[tuple[int, str, str]] = []
    ok_count = 0
    err_count = 0

    for i, url in enumerate(urls, 1):
        status, note = check_url(url, timeout=args.timeout)
        is_ok = 200 <= status < 400

        if is_ok:
            ok_count += 1
        else:
            err_count += 1
            broken.append((status, url, note))
            print(f"[check_links] {'❌' if status == 404 else '⚠️'} {status} {url}{' — '+note if note else ''}")

        if not args.dry_run:
            note_str = note if not is_ok else ""
            log_result(ts_run, status, url, note_str)

        if i % 50 == 0:
            print(f"[check_links] Progress: {i}/{len(urls)} ({err_count} errors so far)")

        if args.delay > 0:
            time.sleep(args.delay)

    # Summary
    print(f"\n[check_links] Done: {ok_count} ok, {len(broken)} broken, {len(urls)} checked")

    if not args.dry_run and not args.no_discord and broken:
        notify_discord(broken, len(urls))

    # Write summary line to log
    summary = f"{ts_run}\tSUMMARY\t{len(urls)} checked, {ok_count} ok, {len(broken)} broken"
    if not args.dry_run:
        log_result(ts_run, 0, summary)

    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
