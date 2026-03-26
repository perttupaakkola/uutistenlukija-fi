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
    "success":   <bool — backward compat: True if outcome is "ok" or "skip">,
    "outcome":   <"ok" | "skip" | "error">
  }

outcome values:
  "ok"    — pipeline ran and published ≥1 article
  "skip"  — pipeline ran cleanly but found 0 new articles (deduped / quiet news cycle)
  "error" — pipeline crashed, timed out, or failed mid-run
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


def _is_empty_scan(run: dict, steps: dict) -> bool:
    """
    Return True if this run failed only because the scanner found 0 new articles.
    This is expected behavior (deduplication, quiet news cycle) — not a real error.

    Signals:
    - Only the scanner step ran (pipeline stopped early — nothing to process)
    - Scanner step itself succeeded (no crash), just returned 0 articles
    - No error messages that indicate a real crash
    """
    step_names = list(steps.keys())

    # Pattern 1: only scanner step present → pipeline exited because scan returned 0
    if step_names == ["scanner"]:
        scanner = steps.get("scanner", {})
        # If scanner itself crashed, it's an error — but if it succeeded and returned 0, it's a skip
        if scanner.get("success", True):
            return True

    # Pattern 2: scanner + dedup ran but rewriter got 0 articles (all filtered post-dedup)
    if set(step_names) <= {"scanner", "dedup", "research"} and not run.get("success", True):
        errors = " ".join(run.get("errors", [])).lower()
        if "no articles" in errors or "0 article" in errors or "nothing to" in errors:
            return True

    # Pattern 3: explicit error message about no articles
    errors_lower = " ".join(run.get("errors", [])).lower()
    no_article_phrases = (
        "no articles found",
        "no new articles",
        "scanner returned 0",
        "0 articles after dedup",
        "nothing to publish",
    )
    if any(p in errors_lower for p in no_article_phrases):
        return True

    return False


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
    run_success = run.get("success", False)

    # Classify outcome:
    # "ok"    — clean run with ≥1 article published
    # "skip"  — clean run, 0 articles (all deduped / quiet news cycle)
    # "error" — crash, timeout, or mid-run failure
    if run_success and published > 0:
        outcome = "ok"
    elif run_success and published == 0:
        # Pipeline completed successfully but nothing new to publish.
        # This includes: all articles deduped, kw_dedup dropped duplicates,
        # quiet news cycle, empty scan. Not an error.
        outcome = "skip"
    elif _is_empty_scan(run, steps):
        outcome = "skip"
    else:
        outcome = "error"

    record = {
        "ts":        ts,
        "attempted": attempted,
        "published": published,
        "failed":    failed,
        # backward compat: success=True for ok + skip (not a real error)
        "success":   outcome != "error",
        "outcome":   outcome,
    }

    PUBLISH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PUBLISH_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[update_publish_metrics] Logged: attempted={attempted} published={published} outcome={outcome}")


if __name__ == "__main__":
    main()
