#!/usr/bin/env python3
"""
Source diversity report.

Parses the last 7 days of pipeline/metrics.jsonl entries.
Calculates per-source article counts, % of total, last seen timestamp.
Flags sources with 0 articles in past 3 days as stale.
Writes results to static/api/source-stats.json.
Posts a summary to #metrics Discord channel via webhook.

Usage:
    python3 pipeline/source_stats.py [--dry-run] [--days 7]

Cron: run daily, e.g. 07:00 UTC
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import urllib.request
import urllib.error

PIPELINE_DIR = Path(__file__).parent
PROJECT_DIR = PIPELINE_DIR.parent
METRICS_FILE = PIPELINE_DIR / "metrics.jsonl"
STAGED_PUBLISHED_DIR = PIPELINE_DIR / "queues" / "staged" / "published"
OUTPUT_FILE = PROJECT_DIR / "static" / "api" / "source-stats.json"
DISCORD_WEBHOOK_ENV = "DISCORD_METRICS_WEBHOOK"


def load_entries(days: int = 7) -> list[dict]:
    """Load metrics.jsonl entries from the last `days` days."""
    if not METRICS_FILE.exists():
        print(f"[source_stats] {METRICS_FILE} not found", file=sys.stderr)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []
    with METRICS_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("ts", "")
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if dt >= cutoff:
                    entries.append({"dt": dt, **entry})
            except Exception:
                continue
    return entries


def _source_key_from_url(url: str) -> str:
    """Return a stable source key from a URL when no source label exists."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _staged_source_name(artifact: dict) -> str:
    """Extract the best source name from a staged published artifact."""
    for section_name in ("article", "packet", "original_article", "payload"):
        section = artifact.get(section_name) or {}
        if not isinstance(section, dict):
            continue
        for key in ("source", "source_name", "source_domain"):
            value = section.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        source_names = section.get("source_names")
        if isinstance(source_names, list):
            for value in source_names:
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("source_url", "link", "url"):
            value = section.get(key)
            if isinstance(value, str) and value.strip():
                host = _source_key_from_url(value)
                if host:
                    return host
    return ""


def load_staged_published_entries(days: int = 7, staged_dir: Path = STAGED_PUBLISHED_DIR) -> list[dict]:
    """Load source metric entries from staged published queue artifacts."""
    if not staged_dir.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []
    for path in staged_dir.glob("*.json"):
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            ts_str = artifact.get("published_at") or artifact.get("completed_at") or artifact.get("created_at") or ""
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt < cutoff:
                continue
            source = _staged_source_name(artifact)
            if source:
                entries.append({"dt": dt, "ts": ts_str, "sources": {source: 1}, "metric_source": "staged_published", "artifact": path.name})
        except Exception:
            continue
    return entries


def compute_stats(entries: list[dict], stale_days: int = 3) -> dict:
    """Compute per-source stats from entries."""
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)

    source_totals: dict[str, int] = defaultdict(int)
    source_last_seen: dict[str, datetime] = {}
    total_articles = 0

    for entry in entries:
        dt = entry["dt"]
        sources = entry.get("sources", {})
        for source, count in sources.items():
            if count > 0:
                source_totals[source] += count
                if source not in source_last_seen or dt > source_last_seen[source]:
                    source_last_seen[source] = dt
                total_articles += count

    stats = []
    for source, count in sorted(source_totals.items(), key=lambda x: -x[1]):
        last_seen = source_last_seen.get(source)
        last_seen_iso = last_seen.isoformat() if last_seen else None
        is_stale = (last_seen is None) or (last_seen < stale_cutoff)
        stats.append({
            "source": source,
            "count": count,
            "pct": round(count / total_articles * 100, 1) if total_articles else 0,
            "last_seen": last_seen_iso,
            "stale": is_stale,
        })

    stale_count = sum(1 for s in stats if s["stale"])

    metric_sources = sorted({entry.get("metric_source", "metrics_jsonl") for entry in entries})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 7,
        "metric_sources": metric_sources,
        "total_articles": total_articles,
        "source_count": len(stats),
        "stale_count": stale_count,
        "sources": stats,
    }


def build_discord_message(report: dict) -> str:
    """Build a compact Discord summary."""
    top5 = report["sources"][:5]
    lines = [
        f"📊 **Source diversity report** (last {report['window_days']}d)",
        f"Total articles fetched: **{report['total_articles']}** from **{report['source_count']}** sources",
        f"Stale sources (0 articles in 3d): **{report['stale_count']}**",
        "",
        "**Top 5 sources:**",
    ]
    for s in top5:
        stale_marker = " ⚠️ STALE" if s["stale"] else ""
        lines.append(f"• `{s['source']}` — {s['count']} articles ({s['pct']}%){stale_marker}")

    stale_sources = [s["source"] for s in report["sources"] if s["stale"]]
    if stale_sources:
        lines.append(f"\n⚠️ **Stale:** {', '.join(stale_sources[:10])}")

    return "\n".join(lines)


def post_to_discord(message: str, webhook_url: str) -> bool:
    """POST message to Discord webhook."""
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Hermes-Uutistenlukija/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[source_stats] Discord webhook error {e.code}: {e.read()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[source_stats] Discord webhook failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Source diversity report")
    parser.add_argument("--dry-run", action="store_true", help="Print output, don't write files or post")
    parser.add_argument("--days", type=int, default=7, help="Days of history to analyze")
    args = parser.parse_args()

    print(f"[source_stats] Loading last {args.days} days from {METRICS_FILE}...")
    metrics_entries = load_entries(days=args.days)
    print(f"[source_stats] Found {len(metrics_entries)} metrics.jsonl entries")

    staged_entries = load_staged_published_entries(days=args.days)
    print(f"[source_stats] Found {len(staged_entries)} staged published entries")

    entries = metrics_entries + staged_entries
    report = compute_stats(entries, stale_days=3)

    print(f"[source_stats] Total articles: {report['total_articles']}, sources: {report['source_count']}, stale: {report['stale_count']}")

    if args.dry_run:
        print("[source_stats] DRY RUN — not writing output file")
        print(json.dumps(report, indent=2))
    else:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[source_stats] Written to {OUTPUT_FILE}")

    # Post to Discord
    message = build_discord_message(report)
    print("\n--- Discord message ---")
    print(message)
    print("---")

    webhook_url = os.environ.get(DISCORD_WEBHOOK_ENV, "")
    if args.dry_run:
        print(f"[source_stats] DRY RUN — not posting to Discord")
    elif webhook_url:
        ok = post_to_discord(message, webhook_url)
        print(f"[source_stats] Discord post: {'OK' if ok else 'FAILED'}")
    else:
        print(f"[source_stats] No {DISCORD_WEBHOOK_ENV} set — skipping Discord post")

    return 0


if __name__ == "__main__":
    sys.exit(main())
