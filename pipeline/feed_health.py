#!/usr/bin/env python3
"""
feed_health.py — Track per-feed error history and auto-disable broken feeds.

Maintains `pipeline/logs/feed-health.json` with per-feed state:
  - consecutive_errors: int
  - last_error: str (HTTP status or exception message)
  - last_success: ISO timestamp
  - last_article_ts: ISO timestamp of newest article last seen
  - auto_disabled: bool (set when consecutive_errors >= DISABLE_THRESHOLD)
  - stale: bool (set when no new articles for STALE_DAYS)
  - error_history: last 10 error codes

Auto-disable rules:
  - 403 Forbidden: disable after 3 consecutive hits (permanent block)
  - 404 Not Found: disable after 3 consecutive hits (feed URL gone)
  - 5xx Server Error: disable after 5 consecutive hits (site down)
  - Timeout/ConnectionError: disable after 7 consecutive hits
  - Stale flag: set when no new articles for STALE_DAYS (7 by default)

Usage from scanner.py:
    from feed_health import FeedHealth
    health = FeedHealth()
    # After a successful fetch:
    health.record_success("Yle Uutiset", newest_article_ts=<datetime>)
    # After a failed fetch:
    health.record_error("AP News", 403, "Forbidden")
    # Check if feed should be skipped:
    if health.is_disabled("AP News"):
        continue
    health.save()

CLI:
    python3 feed_health.py           # show status of all feeds
    python3 feed_health.py --reset "Feed Name"  # re-enable a feed
    python3 feed_health.py --report  # full JSON report
"""

import argparse
import json
import os
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
HEALTH_FILE  = SCRIPT_DIR / "logs" / "feed-health.json"

# Number of consecutive errors before auto-disabling
DISABLE_THRESHOLD = {
    403: 3,   # Forbidden — permanent block, disable fast
    404: 3,   # Not Found — URL is gone
    410: 1,   # Gone — immediately disable (RFC says permanently removed)
    5:   5,   # 5xx server errors (any 5xx) — maybe temporary
    0:   7,   # Timeout / connection error (code 0)
}

# Days without new articles before flagging as stale
STALE_DAYS = 7

# Max error history entries per feed
MAX_HISTORY = 10


class FeedHealth:
    """Per-feed health tracker. Load once per pipeline run, save at end."""

    def __init__(self):
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict:
        if HEALTH_FILE.exists():
            try:
                return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def save(self):
        HEALTH_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )

    def _entry(self, feed_name: str) -> dict:
        if feed_name not in self._data:
            self._data[feed_name] = {
                "consecutive_errors": 0,
                "last_error": None,
                "last_success": None,
                "last_article_ts": None,
                "auto_disabled": False,
                "auto_disabled_reason": None,
                "stale": False,
                "error_history": [],
            }
        return self._data[feed_name]

    def record_success(self, feed_name: str, newest_article_ts: Optional[datetime] = None):
        """Call after a feed fetches successfully (even if 0 new articles)."""
        e = self._entry(feed_name)
        now = datetime.now(timezone.utc).isoformat()
        e["consecutive_errors"] = 0
        e["last_error"] = None
        e["last_success"] = now

        if newest_article_ts:
            e["last_article_ts"] = newest_article_ts.isoformat()

        # Re-enable if it was auto-disabled (feed started working again)
        if e.get("auto_disabled"):
            print(f"[feed_health] ✅ {feed_name}: re-enabled (was auto-disabled, now responding)")
            e["auto_disabled"] = False
            e["auto_disabled_reason"] = None

        # Update stale flag
        self._update_stale(feed_name, e)

    def record_error(self, feed_name: str, http_code: int, message: str = ""):
        """Call after a feed fetch fails.
        
        Args:
            feed_name: Feed name from RSS_FEEDS
            http_code: HTTP status code, or 0 for network/timeout errors
            message: Short error description
        """
        e = self._entry(feed_name)
        now = datetime.now(timezone.utc).isoformat()

        e["consecutive_errors"] = e.get("consecutive_errors", 0) + 1
        e["last_error"] = f"{http_code}: {message}" if message else str(http_code)

        # Append to rolling history
        hist = deque(e.get("error_history", []), maxlen=MAX_HISTORY)
        hist.append({"ts": now, "code": http_code, "msg": message[:80]})
        e["error_history"] = list(hist)

        # Check auto-disable threshold
        threshold = self._get_threshold(http_code)
        n = e["consecutive_errors"]

        if n >= threshold and not e.get("auto_disabled"):
            reason = f"{n}× consecutive {http_code or 'timeout'} ({message[:60]})"
            e["auto_disabled"] = True
            e["auto_disabled_reason"] = reason
            print(f"[feed_health] 🚫 AUTO-DISABLED {feed_name}: {reason}")

    def _get_threshold(self, code: int) -> int:
        if code in DISABLE_THRESHOLD:
            return DISABLE_THRESHOLD[code]
        if 500 <= code < 600:
            return DISABLE_THRESHOLD[5]
        return DISABLE_THRESHOLD[0]

    def _update_stale(self, feed_name: str, e: dict):
        """Mark feed as stale if no new articles in STALE_DAYS days."""
        last_ts = e.get("last_article_ts")
        if not last_ts:
            return
        try:
            last = datetime.fromisoformat(last_ts)
            age = datetime.now(timezone.utc) - last
            was_stale = e.get("stale", False)
            e["stale"] = age > timedelta(days=STALE_DAYS)
            if e["stale"] and not was_stale:
                days = age.days
                print(f"[feed_health] ⚠️  STALE {feed_name}: no new articles for {days}d")
        except (ValueError, TypeError):
            pass

    def is_disabled(self, feed_name: str) -> tuple[bool, str]:
        """Return (disabled, reason). Returns (False, '') if healthy."""
        e = self._data.get(feed_name, {})
        if e.get("auto_disabled"):
            return True, e.get("auto_disabled_reason", "auto-disabled")
        return False, ""

    def is_stale(self, feed_name: str) -> bool:
        return self._data.get(feed_name, {}).get("stale", False)

    def get_stats(self) -> dict:
        total = len(self._data)
        disabled = sum(1 for e in self._data.values() if e.get("auto_disabled"))
        stale    = sum(1 for e in self._data.values() if e.get("stale"))
        healthy  = total - disabled - stale
        return {"total": total, "healthy": healthy, "disabled": disabled, "stale": stale}

    def reset(self, feed_name: str):
        """Manually re-enable a feed (clear auto_disabled + error count)."""
        if feed_name in self._data:
            self._data[feed_name]["auto_disabled"] = False
            self._data[feed_name]["auto_disabled_reason"] = None
            self._data[feed_name]["consecutive_errors"] = 0
            self._data[feed_name]["stale"] = False
            print(f"[feed_health] Reset: {feed_name}")
        else:
            print(f"[feed_health] No data for: {feed_name}")

    def print_report(self):
        stats = self.get_stats()
        print(f"\nFeed Health Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'─'*60}")
        print(f"  Total tracked: {stats['total']} | Healthy: {stats['healthy']} | "
              f"Disabled: {stats['disabled']} | Stale: {stats['stale']}")
        print()

        # Show disabled first, then stale, then healthy
        for status_label, filter_fn in [
            ("🚫 AUTO-DISABLED", lambda e: e.get("auto_disabled")),
            ("⚠️  STALE",        lambda e: e.get("stale") and not e.get("auto_disabled")),
            ("✅ Healthy",       lambda e: not e.get("auto_disabled") and not e.get("stale")),
        ]:
            feeds = [(n, e) for n, e in self._data.items() if filter_fn(e)]
            if not feeds:
                continue
            print(f"  {status_label} ({len(feeds)}):")
            for name, entry in sorted(feeds, key=lambda x: x[0]):
                last_ok  = (entry.get("last_success") or "never")[:16]
                last_art = (entry.get("last_article_ts") or "unknown")[:16]
                errs     = entry.get("consecutive_errors", 0)
                reason   = entry.get("auto_disabled_reason", "")
                print(f"    {name}")
                print(f"      last_success={last_ok}  last_article={last_art}  errors={errs}")
                if reason:
                    print(f"      reason: {reason}")
            print()


# ── Integration helpers ────────────────────────────────────────────────────────

# Singleton for use within a pipeline run
_global_health: Optional[FeedHealth] = None


def get_global_health() -> FeedHealth:
    """Return or create the singleton FeedHealth instance."""
    global _global_health
    if _global_health is None:
        _global_health = FeedHealth()
    return _global_health


def save_global_health():
    """Save the singleton (call once at end of scanner run)."""
    if _global_health is not None:
        _global_health.save()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Feed health tracker")
    parser.add_argument("--report", action="store_true", help="Print full report")
    parser.add_argument("--reset", metavar="FEED", help="Re-enable a disabled feed")
    parser.add_argument("--json",  action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    health = FeedHealth()

    if args.reset:
        health.reset(args.reset)
        health.save()
        print("Saved.")
        return

    if args.json:
        print(json.dumps(health._data, indent=2, ensure_ascii=False, default=str))
        return

    health.print_report()


if __name__ == "__main__":
    main()
