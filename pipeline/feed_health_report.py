#!/usr/bin/env python3
"""
feed_health_report.py — Generate RSS feed health report.

Reads RSS_FEEDS from scanner.py, counts per-feed article contributions
from metrics data and published content, outputs static/api/feed-health.json.

Usage:
    python3 feed_health_report.py              # normal run
    python3 feed_health_report.py --dry-run    # print to stdout, don't write file
    python3 feed_health_report.py --live       # also do live HTTP check per feed

Called by auto_publish.sh post-publish chain (non-fatal).
"""
import json
import sys
import os
import re
import glob
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
OUT_FILE = PROJECT_DIR / "static" / "api" / "feed-health.json"
CONTENT_DIR = PROJECT_DIR / "content" / "posts"
METRICS_JSON = SCRIPT_DIR / "logs" / "metrics.json"
METRICS_JSONL = SCRIPT_DIR / "logs" / "metrics.jsonl"
STATE_FILE = SCRIPT_DIR / "logs" / "feed-health-state.json"
RSS_HEALTH_STATE = SCRIPT_DIR / "logs" / "rss-health-state.json"
RSS_HEALTH_LOG = SCRIPT_DIR / "logs" / "rss-health.json"
RSS_HEALTH_API = PROJECT_DIR / "static" / "api" / "rss-feed-health.json"
CANONICAL_GENERATOR = "pipeline/rss_health.py"

RSS_SCORE_TO_LEGACY_STATUS = {
    "fresh": "healthy",
    "stale": "stale",
    "dead": "dead",
    "unreachable": "dead",
}

# Import RSS_FEEDS from scanner
sys.path.insert(0, str(SCRIPT_DIR))
try:
    from scanner import RSS_FEEDS
except ImportError:
    print("[feed_health_report] ERROR: Cannot import RSS_FEEDS from scanner.py", file=sys.stderr)
    sys.exit(1)


# Map feed names to likely domain fragments for matching
FEED_DOMAIN_MAP = {}
for _f in RSS_FEEDS:
    domain = urlparse(_f["url"]).netloc.removeprefix("www.").removeprefix("feeds.")
    FEED_DOMAIN_MAP[_f["name"].lower()] = domain


def _load_state() -> dict:
    """Load persisted feed state (last success times, error counts)."""
    # Prefer our own state file, fall back to rss-health-state.json
    for path in [STATE_FILE, RSS_HEALTH_STATE]:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
    return {}


def _save_state(state: dict):
    """Persist feed state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))


def count_from_metrics_json(days: int = 7) -> Counter:
    """Count per-source articles from metrics.json (array of run records)."""
    counts = Counter()
    if not METRICS_JSON.exists():
        return counts
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        data = json.loads(METRICS_JSON.read_text())
        runs = data if isinstance(data, list) else []
        for r in runs:
            try:
                ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except Exception:
                continue
            # Check steps for source info
            for step_data in r.get("steps", {}).values():
                if isinstance(step_data, dict):
                    for k, v in step_data.items():
                        if "source" in k.lower() and isinstance(v, dict):
                            for src, cnt in v.items():
                                counts[src.lower()] += cnt
            # Top-level sources
            for src, cnt in r.get("sources", {}).items():
                counts[src.lower()] += cnt
    except Exception:
        pass
    return counts


def count_from_metrics_jsonl(days: int = 7) -> Counter:
    """Count per-source articles from metrics.jsonl (newline-delimited)."""
    counts = Counter()
    if not METRICS_JSONL.exists():
        return counts
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for line in METRICS_JSONL.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts_str = rec.get("ts", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
                for src, cnt in rec.get("sources", {}).items():
                    counts[src.lower()] += cnt
            except Exception:
                continue
    except Exception:
        pass
    return counts


def count_from_scan_logs(days: int = 7) -> Counter:
    """Count per-source articles from scan log files."""
    counts = Counter()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y%m%d")

    log_dir = SCRIPT_DIR / "logs"
    for scan_file in sorted(log_dir.glob("*_scanned.json")):
        # Extract date from filename: 20260326_043140_scanned.json
        fname = scan_file.name
        file_date = fname[:8]
        if file_date < cutoff_str:
            continue
        try:
            data = json.loads(scan_file.read_text())
            articles = data if isinstance(data, list) else data.get("articles", [])
            for art in articles:
                domain = art.get("source_domain", "")
                if domain:
                    counts[domain.lower()] += 1
        except Exception:
            continue
    return counts


def count_from_content(days: int = 7) -> Counter:
    """Count articles per source from content/posts/ frontmatter."""
    counts = Counter()
    if not CONTENT_DIR.exists():
        return counts
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    for md_file in CONTENT_DIR.glob("*.md"):
        try:
            # Quick date check from filename: 2026-03-26-slug.md
            fname = md_file.name
            if len(fname) > 10 and fname[4] == "-" and fname[7] == "-":
                file_date = fname[:10]
                if file_date < cutoff_str:
                    continue

            text = md_file.read_text(errors="replace")[:2000]
            if not text.startswith("---"):
                continue
            end = text.find("---", 3)
            if end == -1:
                continue
            fm = text[3:end]

            # Look for source fields
            for field in ("source_name", "source_domain", "source"):
                match = re.search(rf'{field}:\s*["\']?([^"\'\n]+)', fm)
                if match:
                    counts[match.group(1).strip().lower()] += 1
                    break
        except Exception:
            continue
    return counts


def live_check(url: str, timeout: int = 10) -> dict:
    """Do a live HTTP HEAD/GET check on a feed URL."""
    import urllib.request
    import urllib.error

    result = {"reachable": False, "status_code": None, "error": None}
    headers = {"User-Agent": "Uutistenlukija/1.0 (feed-health-check)"}
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        result["reachable"] = True
        result["status_code"] = resp.status
    except urllib.error.HTTPError as e:
        result["status_code"] = e.code
        result["error"] = f"HTTP {e.code}"
    except Exception as e:
        result["error"] = str(e)[:100]
    return result


def _match_feed_contribution(feed_name: str, feed_domain: str, source_counts: Counter) -> int:
    """Match a feed to its article count using fuzzy domain matching."""
    total = 0
    name_lower = feed_name.lower()
    domain_parts = feed_domain.lower().split(".")

    for src, count in source_counts.items():
        src_lower = src.lower()
        # Direct domain match
        if feed_domain in src_lower or src_lower in feed_domain:
            total += count
            continue
        # Root domain match (e.g., "kauppalehti" matches "kauppalehti.fi")
        for part in domain_parts:
            if len(part) > 3 and part in src_lower:
                total += count
                break
    return total



def _feed_key(name: str) -> str:
    return name.lower().replace(" ", "_")


def _load_canonical_rss_health() -> dict:
    """Load rss_health.py's API artifact or raw probe log as canonical reachability.

    feed_health_report.py historically inferred feed health from contribution
    counts. That creates false dead-feed alerts for live feeds that simply did
    not contribute published articles in the last seven days. Prefer the live
    RSS probe artifact whenever it exists.
    """
    for path in (RSS_HEALTH_API, RSS_HEALTH_LOG):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("feeds"), list):
            feeds = data["feeds"]
            return {
                "generated_at": data.get("generated_at"),
                "schema": data.get("schema"),
                "feeds_by_name": {str(feed.get("name") or "").lower(): feed for feed in feeds},
            }
        if isinstance(data, list):
            return {
                "generated_at": max((str(feed.get("checked_at") or "") for feed in data), default=None),
                "schema": "uutistenlukija.rss_health.raw_log.v1",
                "feeds_by_name": {str(feed.get("name") or "").lower(): feed for feed in data},
            }
    return {"generated_at": None, "schema": None, "feeds_by_name": {}}


def _canonical_feed_status(feed_name: str, canonical: dict) -> tuple[str | None, dict | None]:
    feed = canonical.get("feeds_by_name", {}).get(feed_name.lower())
    if not feed:
        return None, None
    score = feed.get("score")
    status = RSS_SCORE_TO_LEGACY_STATUS.get(str(score or ""))
    return status, feed


def _rss_last_success(canonical_feed: dict | None, fallback_last_success: str | None) -> str | None:
    if not canonical_feed:
        return fallback_last_success
    if canonical_feed.get("checked_at") and str(canonical_feed.get("score")) in {"fresh", "stale"}:
        return canonical_feed.get("checked_at")
    return fallback_last_success


def build_report(do_live: bool = False) -> dict:
    """Build the feed health report."""
    now = datetime.now(timezone.utc)
    state = _load_state()
    canonical = _load_canonical_rss_health()

    # Gather article counts from all available sources
    source_counts = Counter()
    source_counts.update(count_from_metrics_json(days=7))
    source_counts.update(count_from_metrics_jsonl(days=7))
    source_counts.update(count_from_scan_logs(days=7))
    source_counts.update(count_from_content(days=7))

    feeds = []
    summary = {"total": 0, "healthy": 0, "stale": 0, "dead": 0, "disabled": 0}

    for feed_info in RSS_FEEDS:
        name = feed_info["name"]
        url = feed_info["url"]
        domain = urlparse(url).netloc.removeprefix("www.").removeprefix("feeds.")
        disabled = feed_info.get("disabled", False)
        feed_key = _feed_key(name)

        # Get persisted state for this feed
        feed_state = state.get(feed_key, {})
        last_success = feed_state.get("last_success")
        consecutive_errors = feed_state.get("consecutive_errors", 0)

        # Count contributions (skip for disabled feeds)
        contrib = 0 if disabled else _match_feed_contribution(name, domain, source_counts)
        canonical_status, canonical_feed = _canonical_feed_status(name, canonical)

        # Determine status
        if disabled:
            status = "disabled"
        elif canonical_status:
            status = canonical_status
        elif consecutive_errors >= 10:
            status = "dead"
        elif contrib == 0 and last_success:
            try:
                last_dt = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
                if (now - last_dt).total_seconds() > 48 * 3600:
                    status = "dead"
                else:
                    status = "stale"
            except Exception:
                status = "stale"
        elif contrib == 0:
            # No state and no articles — check scan logs for evidence of this feed working
            status = "stale"
        else:
            status = "healthy"
            feed_state["last_success"] = now.isoformat()
            feed_state["consecutive_errors"] = 0

        if canonical_feed and status in {"healthy", "stale"}:
            feed_state["last_success"] = _rss_last_success(canonical_feed, last_success)
            feed_state["consecutive_errors"] = 0
            last_success = feed_state.get("last_success")
            consecutive_errors = 0

        entry = {
            "name": name,
            "url": url,
            "domain": domain,
            "language": feed_info.get("language", "?"),
            "category": feed_info.get("category_hint"),
            "disabled": disabled,
            "status": status,
            "contrib_7d": contrib,
            "consecutive_errors": consecutive_errors,
            "last_success": last_success,
            "canonical_source": CANONICAL_GENERATOR if canonical_feed else "contribution_counts",
            "rss_score": canonical_feed.get("score") if canonical_feed else None,
            "rss_checked_at": canonical_feed.get("checked_at") if canonical_feed else None,
            "rss_http_status": canonical_feed.get("http_status") if canonical_feed else None,
            "rss_entries": canonical_feed.get("entries", canonical_feed.get("entry_count")) if canonical_feed else None,
            "rss_newest_age_h": canonical_feed.get("newest_age_h", canonical_feed.get("age_hours")) if canonical_feed else None,
        }

        if do_live and not disabled:
            entry["live_check"] = live_check(url)

        feeds.append(entry)
        summary["total"] += 1
        summary[status] += 1

        state[feed_key] = feed_state

    # Sort: dead first, then disabled, then stale, then by contribution desc
    status_order = {"dead": 0, "disabled": 1, "stale": 2, "healthy": 3}
    feeds.sort(key=lambda f: (status_order.get(f["status"], 9), -f["contrib_7d"]))

    report = {
        "generated_at": now.isoformat(),
        "period_days": 7,
        "summary": summary,
        "total_articles_tracked": sum(source_counts.values()),
        "canonical_source": CANONICAL_GENERATOR if canonical.get("feeds_by_name") else "contribution_counts",
        "canonical_generated_at": canonical.get("generated_at"),
        "feeds": feeds,
    }

    _save_state(state)
    return report


def main():
    dry_run = "--dry-run" in sys.argv
    do_live = "--live" in sys.argv

    report = build_report(do_live=do_live)

    if dry_run:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )

    s = report["summary"]
    print(f"[feed_health_report] Written: {OUT_FILE.relative_to(PROJECT_DIR)}"
          f" — {s['healthy']} healthy, {s['stale']} stale, {s['dead']} dead, {s['disabled']} disabled"
          f" ({report['total_articles_tracked']} articles tracked)")

    # Alert if any feeds are dead (not just disabled)
    dead_feeds = [f["name"] for f in report["feeds"] if f["status"] == "dead"]
    if dead_feeds:
        webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        if webhook:
            import urllib.request
            msg = f"🚨 **Dead RSS feeds detected:** {', '.join(dead_feeds)}\nCheck /api/feed-health.json for details."
            data = json.dumps({"content": msg}).encode()
            req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        print(f"[feed_health_report] ⚠️  Dead feeds: {', '.join(dead_feeds)}")


if __name__ == "__main__":
    main()
