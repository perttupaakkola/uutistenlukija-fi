#!/usr/bin/env python3
"""
pipeline_error_tracker.py — Daily pipeline error log for uutistenlukija.fi

Reads pipeline/metrics.jsonl, aggregates per-day stats, and appends/updates
a rolling 30-day record in pipeline/logs/pipeline_errors.json.

Run daily via cron (e.g. 06:10 UTC) after the pipeline has had time to run.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
METRICS_FILE   = PROJECT_DIR / "pipeline" / "metrics.jsonl"
OUTPUT_FILE    = PROJECT_DIR / "pipeline" / "logs" / "pipeline_errors.json"
ROLLING_DAYS   = 30


def load_metrics() -> list[dict]:
    if not METRICS_FILE.exists():
        return []
    records = []
    with METRICS_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def classify_run(run: dict) -> str:
    """Return error category for a run that had 0 published."""
    reject = run.get("reject_reasons", {})
    if reject.get("quality_gate", 0) > 0:
        return "quality_gate"
    if reject.get("dedup", 0) > 0 or reject.get("duplicate", 0) > 0:
        return "dedup_rejected"
    if run.get("fetched", 0) == 0:
        return "no_articles_fetched"
    if run.get("rewritten", 0) == 0 and run.get("fetched", 0) > 0:
        return "rewrite_failed"
    if run.get("duration_s", 0) > 300:
        return "timeout_suspected"
    # Generic catch-all: fetched something but published nothing
    return "publish_blocked"


def aggregate_by_day(records: list[dict], cutoff: datetime) -> dict[str, dict]:
    """Group metrics records by UTC date, return day → stats dict."""
    days: dict[str, dict] = defaultdict(lambda: {
        "runs": 0,
        "published": 0,
        "fetched": 0,
        "error_runs": 0,
        "skip_runs": 0,
        "ok_runs": 0,
        "error_categories": defaultdict(int),
    })

    for r in records:
        ts_str = r.get("ts", "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < cutoff:
            continue

        day = ts.strftime("%Y-%m-%d")
        d = days[day]
        d["runs"] += 1
        published = r.get("published", 0)
        d["published"] += published
        d["fetched"] += r.get("fetched", 0)

        # Classify run outcome
        if published > 0:
            d["ok_runs"] += 1
        elif r.get("fetched", 0) == 0 and r.get("rewritten", 0) == 0:
            d["skip_runs"] += 1
        else:
            d["error_runs"] += 1
            cat = classify_run(r)
            d["error_categories"][cat] += 1

    # Convert defaultdicts to plain dicts
    return {
        day: {
            **stats,
            "error_categories": dict(stats["error_categories"]),
            "error_rate": round(stats["error_runs"] / stats["runs"], 3) if stats["runs"] else 0,
        }
        for day, stats in sorted(days.items())
    }


def load_existing() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        with OUTPUT_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(days=ROLLING_DAYS)
    records = load_metrics()

    if not records:
        print("[pipeline_error_tracker] No metrics.jsonl records found — nothing to track.")
        return 0

    print(f"[pipeline_error_tracker] Loaded {len(records)} records from metrics.jsonl")
    daily = aggregate_by_day(records, cutoff)

    # Merge with existing (existing entries overwritten by fresh aggregation)
    existing = load_existing()
    existing_by_day = {e["date"]: e for e in existing if "date" in e}

    for day, stats in daily.items():
        existing_by_day[day] = {"date": day, **stats}

    # Prune to rolling window
    final = sorted(existing_by_day.values(), key=lambda x: x["date"])
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    final = [e for e in final if e["date"] >= cutoff_str]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)

    # Summary for log
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_stats = daily.get(today, {})
    runs  = today_stats.get("runs", 0)
    errs  = today_stats.get("error_runs", 0)
    rate  = today_stats.get("error_rate", 0)
    pub   = today_stats.get("published", 0)

    print(f"[pipeline_error_tracker] {today}: {runs} runs, {pub} published, "
          f"{errs} errors ({rate:.0%} error rate)")
    print(f"[pipeline_error_tracker] Written {len(final)} days to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
