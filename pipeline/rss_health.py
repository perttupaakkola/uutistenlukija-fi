#!/usr/bin/env python3
"""
rss_health.py — RSS feed health checker for uutistenlukija.fi

Checks all feeds from scanner.RSS_FEEDS:
  - HTTP reachability + status
  - Parse feed, count entries, newest entry date
  - Score: 🟢 fresh (<6h), 🟡 stale (6-24h), 🔴 dead (>24h), ⚫ unreachable

Outputs:
  - pipeline/logs/rss-health.json  (full results)
  - Discord alert to #operations on state changes (green→red etc.)

Usage:
    python3 pipeline/rss_health.py [--dry-run] [--force-alert]

Cron (daily 05:00 UTC):
    0 5 * * * cd /path/to/project && python3 pipeline/rss_health.py >> pipeline/logs/rss-health.log 2>&1
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
PROJECT_DIR = PIPELINE_DIR.parent
HEALTH_FILE = PIPELINE_DIR / "logs" / "rss-health.json"
STATE_FILE = PIPELINE_DIR / "logs" / "rss-health-state.json"

FRESH_HOURS = 6
STALE_HOURS = 24
REQUEST_TIMEOUT = 10
INTER_REQUEST_DELAY = 0.3   # be polite

WEBHOOK = (
    os.environ.get("DISCORD_PIPELINE_WEBHOOK")
    or os.environ.get("DISCORD_METRICS_WEBHOOK")
    or ""
)

USER_AGENT = "Uutistenlukija/1.0 (RSS health check; +https://uutistenlukija.fi)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

SCORE_FRESH = "fresh"
SCORE_STALE = "stale"
SCORE_DEAD = "dead"
SCORE_UNREACHABLE = "unreachable"

EMOJI = {
    SCORE_FRESH: "🟢",
    SCORE_STALE: "🟡",
    SCORE_DEAD: "🔴",
    SCORE_UNREACHABLE: "⚫",
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _head(url: str) -> tuple[int, dict]:
    """Return (http_status, headers). Returns (0, {}) on error."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def _get_feed(url: str) -> tuple[int, bytes]:
    """Return (http_status, body_bytes). Returns (0, b'') on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


# ── Feed parsing ──────────────────────────────────────────────────────────────

def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    # Try RFC 2822 (RSS pubDate)
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    # Try ISO 8601 (Atom)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:19], fmt[:len(raw[:19])]).replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


def _parse_feed(body: bytes) -> tuple[int, datetime | None]:
    """Return (entry_count, newest_date) from feed body."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return 0, None

    tag = root.tag.lower()
    dates: list[datetime] = []

    # RSS 2.0
    if "rss" in tag or root.tag == "rss":
        items = root.findall(".//item")
        for item in items:
            pub = item.findtext("pubDate") or item.findtext("dc:date", namespaces=NS)
            dt = _parse_date(pub)
            if dt:
                dates.append(dt)
        return len(items), max(dates) if dates else None

    # Atom
    if "feed" in root.tag:
        entries = root.findall(f"{{{NS['atom']}}}entry") or root.findall("entry")
        for entry in entries:
            updated = (
                entry.findtext(f"{{{NS['atom']}}}updated")
                or entry.findtext(f"{{{NS['atom']}}}published")
                or entry.findtext("updated")
                or entry.findtext("published")
            )
            dt = _parse_date(updated)
            if dt:
                dates.append(dt)
        return len(entries), max(dates) if dates else None

    return 0, None


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score(http_status: int, newest_date: datetime | None) -> str:
    if http_status == 0 or http_status >= 500:
        return SCORE_UNREACHABLE
    if http_status >= 400:
        return SCORE_DEAD
    if newest_date is None:
        return SCORE_STALE  # reachable but can't determine freshness

    now = datetime.now(timezone.utc)
    age_hours = (now - newest_date).total_seconds() / 3600
    if age_hours < FRESH_HOURS:
        return SCORE_FRESH
    elif age_hours < STALE_HOURS:
        return SCORE_STALE
    else:
        return SCORE_DEAD


# ── State tracking ────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Discord ───────────────────────────────────────────────────────────────────

def _post_discord(message: str, webhook: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] Discord: {message[:200]}")
        return
    if not webhook:
        print("[rss_health] No webhook — skipping alert.", file=sys.stderr)
        return
    try:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(webhook, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"[rss_health] Posted to Discord ({r.status})")
    except Exception as e:
        print(f"[rss_health] Discord post failed: {e}", file=sys.stderr)


def _build_summary(results: list[dict]) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fresh = sum(1 for r in results if r["score"] == SCORE_FRESH)
    stale = sum(1 for r in results if r["score"] == SCORE_STALE)
    dead = sum(1 for r in results if r["score"] == SCORE_DEAD)
    unreachable = sum(1 for r in results if r["score"] == SCORE_UNREACHABLE)

    lines = [
        f"**📡 RSS Feed Health** — {now_str}",
        f"🟢 {fresh} tuore  🟡 {stale} vanhentunut  🔴 {dead} kuollut  ⚫ {unreachable} tavoittamaton",
        "",
    ]

    # Only show non-fresh feeds in detail (keep message short)
    problem_feeds = [r for r in results if r["score"] != SCORE_FRESH]
    if problem_feeds:
        lines.append("**Ongelmalliset syötteet:**")
        for r in problem_feeds:
            em = EMOJI[r["score"]]
            age = r.get("age_hours")
            age_str = f"{age:.0f}h sitten" if age is not None else "?"
            lines.append(f"  {em} **{r['name']}** — {r.get('http_status','?')} | {age_str} | {r.get('entry_count','?')} artikkelia")
    else:
        lines.append("✅ Kaikki syötteet kunnossa.")

    return "\n".join(lines)


def _build_change_alert(changed: list[tuple[str, str, str]]) -> str:
    """changed: list of (name, old_score, new_score)"""
    lines = ["⚠️ **RSS-syötteen tila muuttunut:**"]
    for name, old, new in changed:
        old_em = EMOJI.get(old, "❓")
        new_em = EMOJI.get(new, "❓")
        lines.append(f"  {old_em}→{new_em} **{name}** ({old} → {new})")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def check_feeds(dry_run: bool = False, force_alert: bool = False) -> list[dict]:
    # Import feed list from scanner
    sys.path.insert(0, str(PIPELINE_DIR))
    try:
        from scanner import RSS_FEEDS
    except ImportError as e:
        print(f"[rss_health] Cannot import scanner: {e}", file=sys.stderr)
        return []

    results = []
    now = datetime.now(timezone.utc)

    for feed in RSS_FEEDS:
        url = feed.get("url", "")
        name = feed.get("name", url)
        language = feed.get("language", "?")

        print(f"[rss_health] Checking {name}...", end=" ", flush=True)

        status, body = _get_feed(url)
        entry_count, newest_date = (0, None)

        if status in (200, 301, 302) and body:
            entry_count, newest_date = _parse_feed(body)

        age_hours = None
        if newest_date:
            age_hours = round((now - newest_date).total_seconds() / 3600, 1)

        score = _score(status, newest_date)
        em = EMOJI[score]

        age_str = f"{age_hours}h" if age_hours is not None else "unknown"
        print(f"{em} status={status} entries={entry_count} age={age_str}")

        results.append({
            "name": name,
            "url": url,
            "language": language,
            "http_status": status,
            "entry_count": entry_count,
            "newest_date": newest_date.isoformat() if newest_date else None,
            "age_hours": age_hours,
            "score": score,
            "checked_at": now.isoformat(),
        })

        time.sleep(INTER_REQUEST_DELAY)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-alert", action="store_true", help="Post summary even if no state changes")
    args = parser.parse_args()

    results = check_feeds(dry_run=args.dry_run, force_alert=args.force_alert)
    if not results:
        return 1

    # Save full results
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"[rss_health] Written to {HEALTH_FILE}")

    # State-change detection
    prev_state = _load_state()
    new_state = {r["name"]: r["score"] for r in results}
    changed = []

    for name, score in new_state.items():
        old = prev_state.get(name)
        if old and old != score:
            changed.append((name, old, score))

    first_run = not bool(prev_state)
    _save_state(new_state)

    # Determine what to post
    problem_count = sum(1 for r in results if r["score"] != SCORE_FRESH)
    webhook = WEBHOOK

    if args.dry_run:
        print("\n=== SUMMARY ===")
        print(_build_summary(results))
        if changed:
            print("\n=== CHANGES ===")
            print(_build_change_alert(changed))
        return 0

    if changed:
        _post_discord(_build_change_alert(changed), webhook)

    # Post full summary on first run, force_alert, or when problems exist + state changed
    if first_run or args.force_alert or (problem_count > 0 and changed):
        _post_discord(_build_summary(results), webhook)

    # Always log summary to stdout
    print("\n" + _build_summary(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
