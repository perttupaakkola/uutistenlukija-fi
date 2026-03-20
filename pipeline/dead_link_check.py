#!/usr/bin/env python3
"""
dead_link_check.py — Crawl uutistenlukija.fi internal links, report broken ones.

Since Cloudflare Pages doesn't expose server logs, this script crawls the live
site (or a local Hugo build), finds internal links that return non-200 status,
and posts a weekly summary to Discord #metrics.

Usage:
    python3 dead_link_check.py                  # crawl live site
    python3 dead_link_check.py --base http://localhost:1313  # local Hugo build
    python3 dead_link_check.py --dry-run        # print without posting
    python3 dead_link_check.py --max 200        # limit pages crawled

Requirements:
    pip install requests  (stdlib urllib fallback also works)
    DISCORD_WEBHOOK_METRICS or DISCORD_BOT_TOKEN env var

History logged to pipeline/logs/dead_links.json
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://uutistenlukija.fi"
LOGS_DIR = Path(__file__).parent / "logs"
DEAD_LINK_LOG = LOGS_DIR / "dead_links.json"
METRICS_WEBHOOK = os.getenv("DISCORD_WEBHOOK_METRICS", "")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
METRICS_CHANNEL_ID = "1482720741790060554"

CRAWL_DELAY = 0.3       # seconds between requests (be polite)
REQUEST_TIMEOUT = 15    # seconds
USER_AGENT = "uutistenlukija-bot/1.0 (internal dead-link checker)"


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        href = None
        if tag == "a":
            href = attrs_dict.get("href")
        elif tag in ("link",):
            rel = attrs_dict.get("rel", "")
            if "canonical" in rel or "alternate" in rel:
                href = attrs_dict.get("href")

        if href:
            href = href.split("#")[0].strip()  # strip fragments
            if href.startswith(("http://", "https://")):
                self.links.append(href)
            elif href.startswith("/"):
                self.links.append(self.base_url.rstrip("/") + href)
            # skip relative paths, mailto:, javascript:, etc.


def fetch(url: str) -> tuple[int, str]:
    """Fetch URL, return (status_code, html_body). Returns (0, '') on error."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def is_internal(url: str, base: str) -> bool:
    parsed_url = urllib.parse.urlparse(url)
    parsed_base = urllib.parse.urlparse(base)
    return parsed_url.netloc == parsed_base.netloc or parsed_url.netloc == ""


def normalize(url: str, base: str) -> str:
    """Add trailing slash to path-only URLs, strip query for static sites."""
    p = urllib.parse.urlparse(url)
    path = p.path
    if path and not path.endswith("/") and "." not in path.split("/")[-1]:
        path = path + "/"
    return urllib.parse.urlunparse((p.scheme, p.netloc, path, "", "", ""))


def crawl(base_url: str, max_pages: int = 500) -> dict:
    """BFS crawl starting from base_url. Returns structured results."""
    visited: set[str] = set()
    queue: list[tuple[str, str]] = [(base_url + "/", "(seed)")]   # (url, found_on)
    broken: list[dict] = []
    ok_count = 0
    external_errors: list[dict] = []

    print(f"Crawling {base_url} (max {max_pages} pages)...", flush=True)

    while queue and len(visited) < max_pages:
        url, found_on = queue.pop(0)
        norm = normalize(url, base_url)

        if norm in visited:
            continue
        visited.add(norm)

        time.sleep(CRAWL_DELAY)
        status, body = fetch(norm)

        if status == 200:
            ok_count += 1
            if is_internal(norm, base_url):
                parser = LinkExtractor(base_url)
                parser.feed(body)
                for link in parser.links:
                    link_norm = normalize(link, base_url)
                    if link_norm not in visited:
                        queue.append((link_norm, norm))
        elif status in (301, 302, 303, 307, 308):
            # Redirects are warnings, not errors — skip
            ok_count += 1
        elif status == 0:
            broken.append({
                "url": norm,
                "status": "timeout/error",
                "found_on": found_on,
                "internal": is_internal(norm, base_url)
            })
        else:
            entry = {
                "url": norm,
                "status": status,
                "found_on": found_on,
                "internal": is_internal(norm, base_url)
            }
            if is_internal(norm, base_url):
                broken.append(entry)
                print(f"  💥 {status}: {norm}  (from {found_on})", flush=True)
            else:
                external_errors.append(entry)

        if len(visited) % 50 == 0:
            print(f"  … {len(visited)} pages checked, {len(broken)} broken", flush=True)

    return {
        "pages_checked": len(visited),
        "ok": ok_count,
        "broken_internal": broken,
        "broken_external": external_errors[:20],  # cap at 20 external
    }


def load_history() -> list:
    if DEAD_LINK_LOG.exists():
        try:
            return json.loads(DEAD_LINK_LOG.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_history(history: list, result: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pages_checked": result["pages_checked"],
        "broken_count": len(result["broken_internal"]),
        "broken": result["broken_internal"][:50],  # keep last 50 per run
    }
    history.append(entry)
    history = history[-20:]  # keep 20 weekly runs
    DEAD_LINK_LOG.write_text(json.dumps(history, indent=2))


def format_discord_message(result: dict, previous_broken: int | None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    broken = result["broken_internal"]
    n = len(broken)
    pages = result["pages_checked"]

    delta_str = ""
    if previous_broken is not None:
        diff = n - previous_broken
        if diff > 0:
            delta_str = f" (+{diff} uutta)"
        elif diff < 0:
            delta_str = f" ({diff} korjattu)"
        else:
            delta_str = " (ei muutosta)"

    if n == 0:
        status_line = f"✅ Ei rikkinäisiä linkkejä — {pages} sivua tarkistettu"
    elif n <= 5:
        status_line = f"⚠️ {n} rikkinäistä linkkiä{delta_str} — {pages} sivua tarkistettu"
    else:
        status_line = f"🔴 {n} rikkinäistä linkkiä{delta_str} — {pages} sivua tarkistettu"

    lines = [f"## 🔗 Dead Link Check — {now}", status_line]

    if broken:
        lines.append("")
        lines.append("**Rikkinäiset sisäiset linkit:**")
        # Group by status code
        by_status = defaultdict(list)
        for b in broken:
            by_status[b["status"]].append(b)

        for status_code, items in sorted(by_status.items(), key=lambda x: str(x[0])):
            lines.append(f"**HTTP {status_code}** ({len(items)} kpl):")
            for item in items[:10]:
                url_path = urllib.parse.urlparse(item["url"]).path
                found_path = urllib.parse.urlparse(item["found_on"]).path or "(seed)"
                lines.append(f"- `{url_path}` ← {found_path}")
            if len(items) > 10:
                lines.append(f"  _…ja {len(items) - 10} muuta_")

    if result.get("broken_external"):
        n_ext = len(result["broken_external"])
        lines.append("")
        lines.append(f"**Ulkoiset linkkiongelmat:** {n_ext} kpl (näytetään #metrics-lokissa)")

    return "\n".join(lines)


def post_to_discord(message: str) -> bool:
    if METRICS_WEBHOOK:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            METRICS_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            print(f"Webhook error: {e.code}", file=sys.stderr)

    if BOT_TOKEN:
        url = f"https://discord.com/api/v10/channels/{METRICS_CHANNEL_ID}/messages"
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {BOT_TOKEN}",
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201)
        except urllib.error.HTTPError as e:
            print(f"Bot token error: {e.code}", file=sys.stderr)

    return False


def main():
    dry_run = "--dry-run" in sys.argv
    max_pages = 500
    base_url = BASE_URL

    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        if idx + 1 < len(sys.argv):
            max_pages = int(sys.argv[idx + 1])

    if "--base" in sys.argv:
        idx = sys.argv.index("--base")
        if idx + 1 < len(sys.argv):
            base_url = sys.argv[idx + 1].rstrip("/")

    print(f"🔗 Dead link checker starting — base: {base_url}, max: {max_pages} pages")

    history = load_history()
    previous_broken = history[-1]["broken_count"] if history else None

    result = crawl(base_url, max_pages)

    print(f"\n✓ Done. {result['pages_checked']} pages, {len(result['broken_internal'])} broken internal.")

    message = format_discord_message(result, previous_broken)
    print(f"\n--- Discord message ---\n{message}\n---")

    if not dry_run:
        save_history(history, result)
        ok = post_to_discord(message)
        if ok:
            print("✅ Posted to #metrics")
        else:
            print("⚠️  Discord post failed (no webhook/token configured)")
    else:
        print("(dry-run: not posting)")


if __name__ == "__main__":
    main()
