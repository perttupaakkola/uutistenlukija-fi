#!/usr/bin/env python3
"""pipeline_error_tracker.py — Parse pipeline logs and track daily error stats.

Reads pipeline/logs/cron.log, extracts per-run stats, and appends to
pipeline/logs/pipeline_errors.json (rolling 30 days).

Usage:
    python3 scripts/pipeline_error_tracker.py [--date YYYY-MM-DD]
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
LOG_FILE = PROJECT_DIR / "pipeline" / "logs" / "cron.log"
ERROR_DB = PROJECT_DIR / "pipeline" / "logs" / "pipeline_errors.json"

# Error category patterns (order matters — first match wins)
ERROR_PATTERNS = [
    ("openai_quota", re.compile(r"insufficient_quota|rate.limit|RateLimitError|openai.*error", re.I)),
    ("fetch_error", re.compile(r"ConnectionError|TimeoutError|requests\.exceptions|URLError|HTTPError", re.I)),
    ("parse_error", re.compile(r"JSONDecodeError|ParseError|parse.*fail|invalid.*json", re.I)),
    ("rewrite_error", re.compile(r"rewrite.*error|rewriter.*error|failed.*rewrite", re.I)),
    ("publish_error", re.compile(r"publish.*error|publisher.*error|failed.*publish", re.I)),
    ("build_error", re.compile(r"hugo.*error|build.*fail|FAILED", re.I)),
    ("other", re.compile(r"(Error|Exception|Traceback)", re.I)),
]


def categorize_error(line: str) -> str:
    for name, pattern in ERROR_PATTERNS:
        if pattern.search(line):
            return name
    return "other"


def parse_log(log_path: Path, target_date: str | None = None) -> list[dict]:
    """Parse cron.log and return list of run summaries."""
    if not log_path.exists():
        return []

    runs = []
    current_run: dict | None = None
    errors: list[str] = []

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            # Run start
            m = re.match(r"=== Auto-publish started at (.+) ===", line)
            if m:
                if current_run:
                    current_run["errors"] = errors
                    runs.append(current_run)
                current_run = {
                    "start": m.group(1),
                    "date": None,
                    "articles_deployed": 0,
                    "errors": [],
                    "error_categories": defaultdict(int),
                    "success": False,
                }
                errors = []
                # Parse date from timestamp
                try:
                    dt = datetime.strptime(m.group(1), "%a %b %d %I:%M:%S %p UTC %Y")
                    current_run["date"] = dt.strftime("%Y-%m-%d")
                except ValueError:
                    try:
                        dt = datetime.strptime(m.group(1), "%a %b %d %H:%M:%S UTC %Y")
                        current_run["date"] = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        current_run["date"] = "unknown"
                continue

            if current_run is None:
                continue

            # Run end
            if "=== Auto-publish completed" in line:
                current_run["success"] = True
                current_run["errors"] = errors
                runs.append(current_run)
                current_run = None
                errors = []
                continue

            # Articles deployed
            m = re.search(r"Deployed (\d+) new articles", line)
            if m and current_run:
                current_run["articles_deployed"] = int(m.group(1))

            # Error lines
            if re.search(r"(Error|Exception|Traceback|FAILED|failed)", line, re.I):
                errors.append(line)
                if current_run:
                    cat = categorize_error(line)
                    current_run["error_categories"][cat] = current_run["error_categories"].get(cat, 0) + 1

    # Handle unclosed run
    if current_run:
        current_run["errors"] = errors
        runs.append(current_run)

    # Filter by date if requested
    if target_date:
        runs = [r for r in runs if r.get("date") == target_date]

    return runs


def aggregate_by_date(runs: list[dict]) -> dict:
    """Aggregate runs by date."""
    by_date: dict[str, dict] = defaultdict(lambda: {
        "runs": 0,
        "successful_runs": 0,
        "articles_deployed": 0,
        "total_errors": 0,
        "error_categories": defaultdict(int),
    })

    for run in runs:
        date = run.get("date", "unknown")
        day = by_date[date]
        day["runs"] += 1
        if run.get("success"):
            day["successful_runs"] += 1
        day["articles_deployed"] += run.get("articles_deployed", 0)
        err_count = sum(run.get("error_categories", {}).values())
        day["total_errors"] += err_count
        for cat, count in run.get("error_categories", {}).items():
            day["error_categories"][cat] = day["error_categories"].get(cat, 0) + count

    return dict(by_date)


def load_db() -> list[dict]:
    if ERROR_DB.exists():
        try:
            return json.loads(ERROR_DB.read_text())
        except Exception:
            return []
    return []


def save_db(records: list[dict]):
    ERROR_DB.parent.mkdir(parents=True, exist_ok=True)
    # Keep only last 30 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    records = [r for r in records if r.get("date", "") >= cutoff]
    records.sort(key=lambda r: r.get("date", ""))
    ERROR_DB.write_text(json.dumps(records, indent=2))


def main():
    target_date = None
    if len(sys.argv) > 2 and sys.argv[1] == "--date":
        target_date = sys.argv[2]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if target_date is None:
        target_date = today

    print(f"Parsing pipeline logs for {target_date}...")
    runs = parse_log(LOG_FILE, target_date=target_date)

    if not runs:
        print(f"No pipeline runs found for {target_date}")
        return

    aggregated = aggregate_by_date(runs)

    # Load existing DB, update/insert today's record
    db = load_db()
    # Remove existing entry for this date
    db = [r for r in db if r.get("date") != target_date]

    for date, stats in aggregated.items():
        error_rate = (stats["total_errors"] / stats["runs"] * 100) if stats["runs"] > 0 else 0.0
        record = {
            "date": date,
            "runs": stats["runs"],
            "successful_runs": stats["successful_runs"],
            "articles_deployed": stats["articles_deployed"],
            "total_errors": stats["total_errors"],
            "error_rate_pct": round(error_rate, 1),
            "error_categories": dict(stats["error_categories"]),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        db.append(record)
        print(f"Date: {date}")
        print(f"  Runs: {stats['runs']} ({stats['successful_runs']} successful)")
        print(f"  Articles deployed: {stats['articles_deployed']}")
        print(f"  Error rate: {error_rate:.1f}%")
        if stats["error_categories"]:
            print(f"  Error categories: {dict(stats['error_categories'])}")

    save_db(db)
    print(f"Updated {ERROR_DB}")


if __name__ == "__main__":
    main()
