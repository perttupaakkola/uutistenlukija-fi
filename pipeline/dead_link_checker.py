#!/usr/bin/env python3
"""
dead_link_checker.py — Scan article markdown for external URLs, HEAD-check each one.

Checks:
  - External URLs in article body (https://... links in markdown)
  - Hero image URLs (image: field in frontmatter)
  - image_thumb / image_source_url fields

Reports: total unique URLs checked, 404s, 5xx errors, timeouts, OK count.
Outputs: pipeline/logs/dead-links.json
Posts summary to #operations if any 404s are found.

Usage:
    # Dry-run on 50 random articles (no Discord post)
    python3 dead_link_checker.py --dry-run --sample 50

    # Full scan, post to Discord on any 404s
    python3 dead_link_checker.py --all

    # Scan specific articles
    python3 dead_link_checker.py --all --limit 100

Environment:
    DISCORD_BOT_TOKEN — for Discord posting (loaded from pipeline/.env)
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_DIR  = SCRIPT_DIR.parent
CONTENT_DIR  = PROJECT_DIR / "content" / "posts"
LOG_DIR      = SCRIPT_DIR / "logs"
DEAD_LINKS_LOG = LOG_DIR / "dead-links.json"
ENV_FILE     = SCRIPT_DIR / ".env"

OPS_CHANNEL  = "1482082645553713366"

REQUEST_TIMEOUT = 5      # seconds per HEAD request
MAX_RETRIES     = 3
RETRY_DELAY     = 2      # seconds between retries
RATE_LIMIT_MS   = 150    # ms pause between requests to same domain

# User-agent so we're not blocked as a bot by simple filters
UA = "Mozilla/5.0 (compatible; uutistenlukija-linkchecker/1.0)"

# Domains to always skip (CDNs, known-good, or would rate-limit us hard)
SKIP_DOMAINS = {
    # Image CDNs — always alive, no value in checking
    "images.pexels.com",
    "images.unsplash.com",
    "images.kie.ai", "api.kie.ai",
    "cdn.discordapp.com",
    "fonts.googleapis.com", "fonts.gstatic.com",
    # Photo attribution pages — return 401/403 to bots but ARE alive in browsers.
    # The actual images (CDN URLs above) are what matters for readers.
    "unsplash.com", "www.unsplash.com",
    "www.pexels.com", "pexels.com",
}

# ── Env loader ────────────────────────────────────────────────────────────────

def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

# ── Frontmatter + body parser ─────────────────────────────────────────────────

FM_URL_FIELDS = ("image", "image_thumb", "image_source_url")

def extract_urls_from_article(path: Path) -> tuple[list[str], str, str]:
    """
    Returns (urls, title, slug).
    urls = all external URLs found in frontmatter image fields + body links.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    urls = []

    if text.startswith("---"):
        end = text.find("\n---", 3)
        fm_raw = text[3:end] if end != -1 else text[3:]
        body   = text[end + 4:] if end != -1 else ""

        # Extract from frontmatter fields
        title = ""
        for line in fm_raw.splitlines():
            m = re.match(r'^(\w+):\s*(.+)$', line.strip())
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip('"')
            if key == "title":
                title = val
            if key in FM_URL_FIELDS and val.startswith("http"):
                urls.append(val)
    else:
        body  = text
        title = path.stem

    # Extract from body: markdown links [text](url) and bare https://
    # Match [text](url) and direct https://... URLs
    body_urls = re.findall(
        r'https?://[^\s\)\]\"\'\<\>]+',
        body
    )
    for u in body_urls:
        u = u.rstrip(".,;:!?)")
        if u.startswith("http"):
            urls.append(u)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    return unique, title, path.stem


# ── URL checker ───────────────────────────────────────────────────────────────

def head_url(url: str) -> tuple[int, str]:
    """
    HEAD request with retries. Returns (status_code, error_msg).
    status 0 = timeout/connection error.
    """
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()

    # Skip known-safe CDN domains
    if domain in SKIP_DOMAINS or any(domain.endswith("." + s) for s in SKIP_DOMAINS):
        return -1, "skipped"

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                method="HEAD",
                headers={
                    "User-Agent": UA,
                    "Accept": "*/*",
                }
            )
            resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            return resp.status, ""
        except urllib.error.HTTPError as e:
            if e.code in (405, 406):
                # Server doesn't allow HEAD — try GET with range to minimize data
                try:
                    req2 = urllib.request.Request(
                        url,
                        headers={"User-Agent": UA, "Range": "bytes=0-0"}
                    )
                    resp2 = urllib.request.urlopen(req2, timeout=REQUEST_TIMEOUT)
                    return resp2.status, ""
                except urllib.error.HTTPError as e2:
                    return e2.code, str(e2)
                except Exception as e2:
                    return 0, f"GET fallback error: {str(e2)[:60]}"
            return e.code, str(e)
        except urllib.error.URLError as e:
            reason = str(e.reason)
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return 0, "timeout"
            return 0, f"URLError: {reason[:60]}"
        except OSError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return 0, f"OSError: {str(e)[:60]}"

    return 0, "max retries exceeded"


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_articles(paths: list[Path], verbose: bool = False) -> dict:
    """
    Scan articles, check all URLs, return results dict.
    """
    # Build url → [articles] map (one URL may appear in many articles)
    url_to_articles: dict[str, list[str]] = defaultdict(list)
    article_url_count = {}

    print(f"Extracting URLs from {len(paths)} articles...")
    for path in paths:
        urls, title, slug = extract_urls_from_article(path)
        article_url_count[slug] = len(urls)
        for u in urls:
            url_to_articles[u].append(slug)

    all_urls = list(url_to_articles.keys())
    print(f"Found {len(all_urls)} unique URLs across {len(paths)} articles")

    # Group by domain for rate-limiting
    domain_last_req: dict[str, float] = {}

    results = {
        "ok":      [],
        "not_found": [],   # 404
        "server_error": [], # 5xx
        "timeout": [],
        "skipped": [],
        "other":   [],
    }
    checked = 0

    for url in all_urls:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()

        # Domain rate limiting
        now = time.monotonic()
        last = domain_last_req.get(domain, 0)
        wait = RATE_LIMIT_MS / 1000.0 - (now - last)
        if wait > 0:
            time.sleep(wait)
        domain_last_req[domain] = time.monotonic()

        status, err = head_url(url)
        checked += 1
        articles = url_to_articles[url]

        entry = {
            "url":      url,
            "status":   status,
            "error":    err,
            "articles": articles[:5],  # cap list
        }

        if status == -1:
            results["skipped"].append(entry)
        elif status == 0:
            results["timeout"].append(entry)
            if verbose:
                print(f"  TIMEOUT  {url[:70]}")
        elif status == 404:
            results["not_found"].append(entry)
            print(f"  404 ❌  {url[:70]}  (in: {articles[0]})")
        elif 500 <= status < 600:
            results["server_error"].append(entry)
            if verbose:
                print(f"  {status} ⚠  {url[:70]}")
        elif 200 <= status < 400:
            results["ok"].append(entry)
            if verbose:
                print(f"  {status} ✅  {url[:70]}")
        else:
            results["other"].append(entry)
            if verbose:
                print(f"  {status}   {url[:70]}")

        if checked % 25 == 0:
            total_issues = len(results["not_found"]) + len(results["server_error"]) + len(results["timeout"])
            print(f"  [{checked}/{len(all_urls)}] checked — {total_issues} issues so far")

    return results


# ── Discord poster ─────────────────────────────────────────────────────────────

def post_to_discord(message: str, channel_id: str) -> bool:
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not bot_token:
        print(f"\n[discord] No BOT_TOKEN — message:\n{message}")
        return False
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps({"content": message[:2000]}).encode()
    req = urllib.request.Request(
        url, payload,
        {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        print(f"[discord] Posted ✅ HTTP {resp.status}")
        return True
    except urllib.error.HTTPError as e:
        print(f"[discord] HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return False


# ── Report formatter ──────────────────────────────────────────────────────────

def format_report(results: dict, scanned_articles: int, elapsed: float) -> str:
    total_checked = sum(len(v) for v in results.values())
    n_ok          = len(results["ok"])
    n_404         = len(results["not_found"])
    n_5xx         = len(results["server_error"])
    n_timeout     = len(results["timeout"])
    n_skipped     = len(results["skipped"])

    status = "✅" if (n_404 + n_5xx) == 0 else "⚠️"

    lines = [
        f"{status} **Dead Link Check — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}**",
        f"",
        f"Articles scanned: {scanned_articles} | Unique URLs checked: {total_checked - n_skipped} | Skipped (CDN): {n_skipped}",
        f"✅ OK: {n_ok} | ❌ 404: {n_404} | ⚠️ 5xx: {n_5xx} | ⏱ Timeout: {n_timeout}",
        f"Elapsed: {elapsed:.0f}s",
    ]

    if n_404 > 0:
        lines.append(f"\n**404 Not Found ({n_404}):**")
        for entry in results["not_found"][:10]:
            art = entry["articles"][0] if entry["articles"] else "?"
            lines.append(f"  `{entry['url'][:70]}`")
            lines.append(f"    → in: `{art}`")
        if n_404 > 10:
            lines.append(f"  ... and {n_404 - 10} more (see logs/dead-links.json)")

    if n_5xx > 0:
        lines.append(f"\n**5xx Server Errors ({n_5xx}):**")
        for entry in results["server_error"][:5]:
            lines.append(f"  `{entry['status']}` {entry['url'][:60]}")

    if n_timeout > 0:
        lines.append(f"\n**Timeouts ({n_timeout}):** (may be temporary)")
        for entry in results["timeout"][:3]:
            lines.append(f"  `{entry['url'][:70]}`")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all",     action="store_true", help="Scan all articles")
    parser.add_argument("--sample",  type=int, default=50, help="Random sample size (default 50)")
    parser.add_argument("--limit",   type=int, default=None, help="Hard limit on articles")
    parser.add_argument("--dry-run", action="store_true", help="Don't post to Discord")
    parser.add_argument("--verbose", action="store_true", help="Print every URL result")
    parser.add_argument("--no-post", action="store_true", help="Never post to Discord")
    args = parser.parse_args()

    load_env()
    LOG_DIR.mkdir(exist_ok=True)

    all_paths = sorted(CONTENT_DIR.glob("*.md"))

    if args.all:
        paths = all_paths
    else:
        paths = random.sample(all_paths, min(args.sample, len(all_paths)))

    if args.limit:
        paths = paths[:args.limit]

    print(f"\n{'='*60}")
    print(f"DEAD LINK CHECKER — {len(paths)} articles")
    if args.dry_run:
        print("MODE: dry-run (no Discord post)")
    print(f"{'='*60}\n")

    t_start = time.monotonic()
    results = scan_articles(paths, verbose=args.verbose)
    elapsed = time.monotonic() - t_start

    # Save JSON log
    log_entry = {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "articles_scanned": len(paths),
        "elapsed_sec":      round(elapsed, 1),
        "summary": {
            "ok":           len(results["ok"]),
            "not_found":    len(results["not_found"]),
            "server_error": len(results["server_error"]),
            "timeout":      len(results["timeout"]),
            "skipped":      len(results["skipped"]),
            "other":        len(results["other"]),
        },
        "not_found":    results["not_found"],
        "server_error": results["server_error"],
        "timeout":      results["timeout"][:20],
    }
    DEAD_LINKS_LOG.write_text(json.dumps(log_entry, indent=2, ensure_ascii=False))
    print(f"\nSaved: {DEAD_LINKS_LOG}")

    report = format_report(results, len(paths), elapsed)
    print("\n" + report)

    # Post to Discord if there are 404s (or always if --all)
    should_post = (
        not args.dry_run
        and not args.no_post
        and (len(results["not_found"]) > 0 or args.all)
    )
    if should_post:
        post_to_discord(report, OPS_CHANNEL)
    elif args.dry_run:
        print("\n[dry-run] Discord post skipped")


if __name__ == "__main__":
    main()
