#!/usr/bin/env python3
"""
Pipeline metrics history consolidation.

Reads pipeline/logs/metrics.json (per-run records) and builds
pipeline/logs/metrics_history.json with daily aggregates.

Idempotent: rebuilds the full history file each run.
Cron: run daily after metrics_report.py, e.g. at 06:05 UTC.

Usage:
    python3 pipeline/metrics_history.py [--dry-run]
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
METRICS_FILE = PIPELINE_DIR / "logs" / "metrics.json"
HISTORY_FILE = PIPELINE_DIR / "logs" / "metrics_history.json"


def _load_runs() -> list[dict]:
    if not METRICS_FILE.exists():
        print(f"[metrics_history] {METRICS_FILE} not found", file=sys.stderr)
        return []
    try:
        data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[metrics_history] Failed to read metrics.json: {e}", file=sys.stderr)
        return []


def _get_day(ts_str: str) -> str:
    """Parse ISO timestamp string → UTC date string YYYY-MM-DD."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "unknown"


def _safe_step(run: dict, *step_names: str) -> dict:
    """Return first matching step dict from run, tolerating old/new key names."""
    steps = run.get("steps", {})
    for name in step_names:
        if name in steps:
            return steps[name]
    return {}


def aggregate(runs: list[dict]) -> list[dict]:
    """Group runs by UTC day and compute daily aggregates."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        day = _get_day(run.get("timestamp", ""))
        if day != "unknown":
            by_day[day].append(run)

    results = []
    for day in sorted(by_day.keys()):
        day_runs = by_day[day]
        total_runs = len(day_runs)
        success_runs = sum(1 for r in day_runs if r.get("success"))
        articles_published = sum(r.get("article_count", 0) for r in day_runs)

        # Scanner totals (newer records may have total/rss_count/firehose_count)
        scanned = sum(_safe_step(r, "scanner").get("total", 0) for r in day_runs)
        rss_in = sum(_safe_step(r, "scanner").get("rss_count", 0) for r in day_runs)
        fh_in = sum(_safe_step(r, "scanner").get("firehose_count", 0) for r in day_runs)
        after_dedup = sum(_safe_step(r, "dedup").get("remaining", 0) for r in day_runs)
        rewritten = sum(_safe_step(r, "rewriter").get("output_count", 0) for r in day_runs)

        # Image sources (handle both "image_gen" and "images" step keys)
        img_runs = [r for r in day_runs if "images" in r.get("steps", {}) or "image_gen" in r.get("steps", {})]
        img_unsplash = sum(_safe_step(r, "images", "image_gen").get("unsplash", 0) for r in img_runs)
        img_pexels   = sum(_safe_step(r, "images", "image_gen").get("pexels", 0) for r in img_runs)
        img_ai       = sum(_safe_step(r, "images", "image_gen").get("ai", 0) for r in img_runs)
        img_fallback = sum(_safe_step(r, "images", "image_gen").get("fallback", 0) for r in img_runs)
        img_total    = sum(_safe_step(r, "images", "image_gen").get("total", 0) for r in img_runs)

        # Step average durations (seconds)
        def _avg_dur(step_keys):
            vals = []
            for r in day_runs:
                for k in step_keys:
                    s = r.get("steps", {}).get(k, {})
                    if "duration_sec" in s:
                        vals.append(s["duration_sec"])
                        break
            return round(sum(vals) / len(vals), 1) if vals else None

        step_avgs = {}
        for label, keys in [
            ("scanner", ["scanner"]),
            ("dedup", ["dedup"]),
            ("rewriter", ["rewriter"]),
            ("images", ["images", "image_gen"]),
            ("publisher", ["publisher"]),
            ("build", ["build"]),
        ]:
            v = _avg_dur(keys)
            if v is not None:
                step_avgs[label] = v

        # Total run duration
        durations = [r["total_duration_sec"] for r in day_runs if "total_duration_sec" in r]
        avg_total = round(sum(durations) / len(durations), 1) if durations else None
        max_total = round(max(durations), 1) if durations else None

        # Error collection
        all_errors = []
        for r in day_runs:
            for e in r.get("errors", []):
                if e:
                    all_errors.append(str(e))

        success_rate = round(success_runs / total_runs * 100, 1) if total_runs else 0.0

        record = {
            "date": day,
            "runs": {
                "total": total_runs,
                "success": success_runs,
                "failed": total_runs - success_runs,
                "success_rate_pct": success_rate,
            },
            "content": {
                "scanned": scanned,
                "rss_in": rss_in,
                "firehose_in": fh_in,
                "after_dedup": after_dedup,
                "rewritten": rewritten,
                "published": articles_published,
            },
            "images": {
                "total": img_total,
                "unsplash": img_unsplash,
                "pexels": img_pexels,
                "ai": img_ai,
                "fallback": img_fallback,
            },
            "step_avg_sec": step_avgs,
            "duration": {
                "avg_sec": avg_total,
                "max_sec": max_total,
            },
            "error_count": len(all_errors),
            "errors_sample": all_errors[:5],
        }
        results.append(record)

    return results


def main():
    parser = argparse.ArgumentParser(description="Build daily metrics history from pipeline runs.")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON, don't write file")
    args = parser.parse_args()

    runs = _load_runs()
    if not runs:
        print("[metrics_history] No run data found.")
        return 0

    history = aggregate(runs)
    output = json.dumps(history, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(output)
        print(f"\n[metrics_history] Would write {len(history)} day(s) to {HISTORY_FILE}")
        return 0

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(output, encoding="utf-8")
    print(f"[metrics_history] Written {len(history)} day(s) of history to {HISTORY_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
