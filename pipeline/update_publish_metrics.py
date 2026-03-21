#!/usr/bin/env python3
"""
update_publish_metrics.py — append latest pipeline run stats to publish-metrics.json

Reads the last record from pipeline/logs/metrics.json and appends a compact
summary line to pipeline/logs/publish-metrics.json (newline-delimited JSON).

Called by auto_publish.sh after each run. Safe to call even if metrics.json
has no new records (idempotent — deduplicates by timestamp).

Output record schema:
  {
    "ts":        "<ISO timestamp of pipeline run>",
    "attempted": <articles that passed dedup>,
    "published": <articles actually written to content/>,
    "failed":    <attempted - published>,
    "success":   <bool — did the run exit cleanly>
  }
"""
import json
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent  # script lives inside pipeline/
METRICS_FILE  = PIPELINE_DIR / "logs" / "metrics.json"
PUBLISH_FILE  = PIPELINE_DIR / "logs" / "publish-metrics.json"


def load_last_run() -> dict | None:
    if not METRICS_FILE.exists():
        return None
    try:
        data = json.loads(METRICS_FILE.read_text())
        runs = data if isinstance(data, list) else []
        return runs[-1] if runs else None
    except Exception as e:
        print(f"[update_publish_metrics] Failed to read metrics.json: {e}", file=sys.stderr)
        return None


def load_existing_timestamps() -> set:
    if not PUBLISH_FILE.exists():
        return set()
    seen = set()
    for line in PUBLISH_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            seen.add(rec.get("ts", ""))
        except Exception:
            pass
    return seen


def main():
    run = load_last_run()
    if not run:
        print("[update_publish_metrics] No runs in metrics.json — nothing to do.")
        return

    ts = run.get("timestamp", "")
    seen = load_existing_timestamps()
    if ts in seen:
        print(f"[update_publish_metrics] Already recorded {ts} — skipping.")
        return

    steps = run.get("steps", {})
    dedup = steps.get("dedup", {})
    attempted = dedup.get("remaining", 0)
    published = run.get("article_count", 0)
    failed = max(0, attempted - published)

    record = {
        "ts":        ts,
        "attempted": attempted,
        "published": published,
        "failed":    failed,
        "success":   run.get("success", False),
    }

    PUBLISH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PUBLISH_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[update_publish_metrics] Logged: attempted={attempted} published={published} failed={failed} success={record['success']}")


if __name__ == "__main__":
    main()
