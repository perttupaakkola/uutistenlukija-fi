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
UNIFIED_FEED_HEALTH_FILE = PROJECT_DIR / "static" / "api" / "rss-feed-health.json"
STATE_FILE          = PIPELINE_DIR / "logs" / "rss-health-state.json"
EXTENDED_STATE_FILE = PIPELINE_DIR / "logs" / "rss-health-extended.json"
SCANNER_FILE        = PIPELINE_DIR / "scanner.py"

AUTO_DISABLE_CONSEC_ERRORS = 3   # consecutive 4xx/5xx checks before auto-disable
ZERO_ENTRIES_DAYS          = 7   # days with 0 entries before parser-mismatch alert

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


def _is_html(body: bytes) -> bool:
    """Return True if body looks like HTML rather than XML/RSS."""
    sniff = body[:512].lower()
    return b"<!doctype html" in sniff or b"<html" in sniff


def _parse_feed(body: bytes) -> tuple[int, datetime | None]:
    """Return (entry_count, newest_date) from feed body."""
    if _is_html(body):
        return -1, None  # sentinel: HTML response, not a feed
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

def _normalize_http_status(http_status: int | str | None) -> int:
    """Coerce probe status to an int so sentinel strings cannot crash scoring."""
    if isinstance(http_status, int):
        return http_status
    if isinstance(http_status, str):
        try:
            return int(http_status)
        except ValueError:
            return 0
    return 0


def _score(http_status: int | str | None, newest_date: datetime | None) -> str:
    status = _normalize_http_status(http_status)
    if status == 0 or status >= 500:
        return SCORE_UNREACHABLE
    if status >= 400:
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


# ── Extended state + remediation ─────────────────────────────────────────────

def _load_ext_state() -> dict:
    """Extended per-feed state: consecutive error counts, first-bad timestamps."""
    if EXTENDED_STATE_FILE.exists():
        try:
            return json.loads(EXTENDED_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_ext_state(state: dict) -> None:
    EXTENDED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXTENDED_STATE_FILE.write_text(json.dumps(state, indent=2))


def _auto_disable_feed(name: str, url: str, reason: str, dry_run: bool = False) -> bool:
    """Add disabled=True to a feed dict in scanner.py. Returns True if changed."""
    if not SCANNER_FILE.exists():
        print(f"[rss_health] Cannot find {SCANNER_FILE}", file=sys.stderr)
        return False

    scanner_text = SCANNER_FILE.read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    url_idx = scanner_text.find(url)
    if url_idx < 0:
        print(f"[rss_health] WARNING: cannot find URL {url} in scanner.py")
        return False

    block_start = scanner_text.rfind("{", 0, url_idx)
    block_end   = scanner_text.find("}", url_idx)
    if block_start < 0 or block_end < 0:
        print(f"[rss_health] WARNING: cannot find dict block for {name}")
        return False

    block = scanner_text[block_start : block_end + 1]
    if '"disabled"' in block or "'disabled'" in block:
        print(f"[rss_health] {name} already disabled in scanner.py")
        return False

    if dry_run:
        print(f"[rss_health] [dry-run] Would disable {name}: {reason}")
        return False

    disable_line = '        "disabled": True,  # AUTO-DISABLED ' + today + ': ' + reason
    new_block = block[:-1] + "\n" + disable_line + "\n    }"
    new_scanner = scanner_text[:block_start] + new_block + scanner_text[block_end + 1:]

    orig_mode = SCANNER_FILE.stat().st_mode
    SCANNER_FILE.write_text(new_scanner, encoding="utf-8")
    os.chmod(str(SCANNER_FILE), orig_mode)
    print(f"[rss_health] AUTO-DISABLED {name} in scanner.py: {reason}")
    return True


def _remediate(results: list[dict], ext_state: dict, dry_run: bool = False) -> tuple[dict, list[str]]:
    """
    Check consecutive HTTP errors and zero-entry streaks.
    Returns (updated_ext_state, list_of_alert_messages).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    alerts: list[str] = []

    for feed in results:
        name    = feed["name"]
        url     = feed["url"]
        http    = feed.get("http_status", 0)
        entries = feed.get("entry_count", 0)

        entry = ext_state.setdefault(name, {
            "consec_errors":       0,
            "first_error_at":      None,
            "consec_zero_entries": 0,
            "first_zero_at":       None,
            "disabled_at":         None,
        })

        # Consecutive HTTP errors (4xx/5xx) → auto-disable after threshold
        http_norm = _normalize_http_status(http)
        is_http_error = http_norm >= 400
        if is_http_error:
            if entry["consec_errors"] == 0:
                entry["first_error_at"] = now_iso
            entry["consec_errors"] += 1

            if (entry["consec_errors"] >= AUTO_DISABLE_CONSEC_ERRORS
                    and not entry.get("disabled_at")):
                reason  = "HTTP " + str(http) + " for " + str(entry["consec_errors"]) + " consecutive checks"
                changed = _auto_disable_feed(name, url, reason, dry_run)
                if changed or dry_run:
                    entry["disabled_at"] = now_iso
                    alerts.append(
                        "\U0001f6ab **Auto-disabled feed:** " + name + "\n"
                        "  Reason: " + reason + "\n"
                        "  URL: `" + url + "`"
                    )
        else:
            entry["consec_errors"]  = 0
            entry["first_error_at"] = None

        # Zero-entry streak (200 OK, 0 items) → parser mismatch alert after N days
        if entries == 0 and http_norm == 200:
            if entry["consec_zero_entries"] == 0:
                entry["first_zero_at"] = now_iso
            entry["consec_zero_entries"] += 1

            if entry["consec_zero_entries"] >= ZERO_ENTRIES_DAYS:
                alerts.append(
                    "\u26a0\ufe0f **Parser mismatch suspected:** " + name + "\n"
                    "  Zero entries for " + str(entry["consec_zero_entries"]) + " consecutive days\n"
                    "  URL: `" + url + "` \u2014 feed may have changed format"
                )
        else:
            entry["consec_zero_entries"] = 0
            entry["first_zero_at"]       = None

    return ext_state, alerts


def _write_unified_feed_health(results: list[dict]) -> None:
    """Write a stable, API-served RSS probe artifact for ops dashboards."""
    checked_at = datetime.now(timezone.utc).isoformat()
    feeds = []
    for r in results:
        status = _normalize_http_status(r.get("http_status"))
        feeds.append({
            "name": r.get("name"),
            "url": r.get("url"),
            "language": r.get("language"),
            "http_status": r.get("http_status"),
            "http_status_normalized": status,
            "entries": r.get("entry_count", 0),
            "newest_date": r.get("newest_date"),
            "newest_age_h": r.get("age_hours"),
            "score": r.get("score"),
            "checked_at": r.get("checked_at", checked_at),
        })

    counts = {score: sum(1 for r in results if r.get("score") == score)
              for score in (SCORE_FRESH, SCORE_STALE, SCORE_DEAD, SCORE_UNREACHABLE)}
    payload = {
        "generated_at": checked_at,
        "schema": "uutistenlukija.rss_feed_health.v1",
        "counts": counts,
        "feeds": feeds,
    }
    UNIFIED_FEED_HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    UNIFIED_FEED_HEALTH_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[rss_health] Written unified feed health to {UNIFIED_FEED_HEALTH_FILE}")


def _build_weekly_summary(results: list[dict], ext_state: dict) -> str:
    """Weekly feed health summary for #operations."""
    fresh   = [r for r in results if r["score"] == SCORE_FRESH]
    stale   = [r for r in results if r["score"] == SCORE_STALE]
    dead    = [r for r in results if r["score"] == SCORE_DEAD]
    unreach = [r for r in results if r["score"] == SCORE_UNREACHABLE]
    disabled_names = [n for n, e in ext_state.items() if e.get("disabled_at")]

    lines = [
        "\U0001f4e1 **Viikkoinen sy\u00f6tteen tilaraportti**",
        "",
        ("\U0001f7e2 Tuoreet: " + str(len(fresh)) + "  \U0001f7e1 Vanhentuneet: " + str(len(stale)) +
         "  \U0001f534 Kuolleet: " + str(len(dead)) + "  \u26ab Tavoittamattomat: " + str(len(unreach))),
    ]
    if disabled_names:
        lines.append("\U0001f6ab Auto-poistettu k\u00e4yt\u00f6st\u00e4: " + str(len(disabled_names)) +
                     " (" + ", ".join(disabled_names) + ")")
    if stale:
        lines += ["", "**\U0001f7e1 Vanhentunut sis\u00e4lt\u00f6:**"]
        for r in stale:
            age = str(r["age_hours"]) + "h" if r.get("age_hours") else "?"
            lines.append("  \u2022 " + r["name"] + " \u2014 viimeisin artikkeli " + age + " sitten")
    if dead:
        lines += ["", "**\U0001f534 Kuolleet sy\u00f6tteet:**"]
        for r in dead:
            lines.append("  \u2022 " + r["name"] + " (HTTP " + str(r.get("http_status", "?")) + ")")
    lines += ["", "_Generoitu " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + "_"]
    return "\n".join(lines)


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
            if entry_count == -1:
                # Feed returned HTML (paywall/redirect) — keep a string sentinel
                # in output, but scoring/remediation must normalize it safely.
                status = SCORE_UNREACHABLE
                entry_count = 0
                newest_date = None

        age_hours = None
        if newest_date:
            age_hours = round((now - newest_date).total_seconds() / 3600, 1)

        score = _score(status, newest_date)
        em = EMOJI[score]

        age_str = f"{age_hours}h" if age_hours is not None else "unknown"
        print(f"{em} status={status} entries={entry_count} age={age_str}")

        normalized_status = _normalize_http_status(status)

        results.append({
            "name": name,
            "url": url,
            "language": language,
            "http_status": status,
            "http_status_normalized": normalized_status,
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
    _write_unified_feed_health(results)

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
