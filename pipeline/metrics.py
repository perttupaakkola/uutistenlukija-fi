"""
Pipeline metrics logging — appends one JSON line per run to metrics.jsonl.

Schema (each line):
    {
        "ts": "2026-03-21T10:36:00Z",
        "fetched": 12,
        "deduped": 3,
        "rewritten": 5,
        "rejected": 1,
        "published": 4,
        "avg_words": 312,
        "sources": {"yle.fi": 2, "hs.fi": 1},
        "reject_reasons": {"too_short": 1},
        "duration_s": 45
    }

Usage:
    # From code
    from metrics import append_run, print_report

    # CLI
    python3 metrics.py --metrics-report [--days 7]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

_PIPELINE_DIR = os.path.dirname(__file__)
METRICS_FILE = os.path.join(_PIPELINE_DIR, "metrics.jsonl")


def append_run(
    *,
    fetched: int,
    deduped: int,
    rewritten: int,
    rejected: int,
    published: int,
    avg_words: float,
    sources: dict,
    reject_reasons: dict,
    duration_s: float,
) -> None:
    """Append one JSON line to metrics.jsonl for this pipeline run."""
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched": fetched,
        "deduped": deduped,
        "rewritten": rewritten,
        "rejected": rejected,
        "published": published,
        "avg_words": round(avg_words, 1),
        "sources": sources,
        "reject_reasons": reject_reasons,
        "duration_s": round(duration_s, 1),
    }
    try:
        with open(METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[metrics] WARNING: could not write to {METRICS_FILE}: {e}", file=sys.stderr)


def _load_recent(days: int = 7) -> list[dict]:
    """Load runs from the last ``days`` days (default 7)."""
    if not os.path.exists(METRICS_FILE):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    records = []
    with open(METRICS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                if ts >= cutoff:
                    records.append(rec)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return records


def print_report(days: int = 7) -> None:
    """Print a human-readable summary for the last ``days`` days."""
    records = _load_recent(days)
    if not records:
        print(f"[metrics] No data found in {METRICS_FILE} for the last {days} days.")
        return

    total_runs = len(records)
    total_published = sum(r.get("published", 0) for r in records)
    total_rejected = sum(r.get("rejected", 0) for r in records)
    total_rewritten = sum(r.get("rewritten", 0) for r in records)

    # Avg words — weighted by published count
    weighted_words = sum(r.get("avg_words", 0) * r.get("published", 0) for r in records)
    avg_words = round(weighted_words / total_published, 1) if total_published else 0

    rejection_rate = round(total_rejected / total_rewritten * 100, 1) if total_rewritten else 0

    # Source aggregation
    source_totals: dict[str, int] = defaultdict(int)
    for r in records:
        for src, count in r.get("sources", {}).items():
            source_totals[src] += count
    top_sources = sorted(source_totals.items(), key=lambda x: -x[1])[:5]

    # Reject reason aggregation
    reason_totals: dict[str, int] = defaultdict(int)
    for r in records:
        for reason, count in r.get("reject_reasons", {}).items():
            reason_totals[reason] += count

    avg_duration = round(sum(r.get("duration_s", 0) for r in records) / total_runs, 1)

    sep = "─" * 50
    print(f"\n{sep}")
    print(f"  Pipeline metrics — last {days} days ({total_runs} runs)")
    print(sep)
    print(f"  Total published   : {total_published}")
    print(f"  Avg words/article : {avg_words}")
    print(f"  Rejection rate    : {rejection_rate}%  ({total_rejected}/{total_rewritten} rewritten)")
    print(f"  Avg run duration  : {avg_duration}s")
    if top_sources:
        print(f"  Top sources       :")
        for src, n in top_sources:
            print(f"    {src:<30} {n}")
    if reason_totals:
        print(f"  Reject reasons    :")
        for reason, n in sorted(reason_totals.items(), key=lambda x: -x[1]):
            print(f"    {reason:<30} {n}")
    print(sep + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline metrics tool")
    parser.add_argument(
        "--metrics-report",
        action="store_true",
        help="Print a summary of recent pipeline runs",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="Number of days to include in the report (default: 7)",
    )
    args = parser.parse_args()

    if args.metrics_report:
        print_report(days=args.days)
    else:
        parser.print_help()
