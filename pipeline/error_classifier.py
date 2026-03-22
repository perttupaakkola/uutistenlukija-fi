#!/usr/bin/env python3
"""
error_classifier.py — Classify pipeline run failures into categories.

Reads the last N pipeline runs from logs/metrics.json (+ supplementary
auto_publish_*.log files) and classifies each failure into one of:

  no_articles_scan   — scanner returned 0 articles (all deduped, 304 cache, slow news day)
  rewriter_timeout   — LLM call timed out or took >120s
  rewriter_error     — Python/API exception in rewriter step
  hugo_build         — hugo build failed
  image_gen          — image generation failed (Pexels/Unsplash/Kie all failed)
  quality_gate       — pre-publish quality gate dropped all articles
  firehose_filter    — firehose-only run returned 0 articles
  python_error       — unhandled Python exception (NameError, ImportError etc.)
  unknown            — none of the above

Output: logs/error-classification.json
Prints summary to stdout.

Usage:
    python3 error_classifier.py              # last 50 runs
    python3 error_classifier.py --limit 100  # last 100 runs
    python3 error_classifier.py --verbose    # print each run's classification
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
LOG_DIR     = SCRIPT_DIR / "logs"
METRICS_FILE      = LOG_DIR / "metrics.json"
PUBLISH_METRICS   = LOG_DIR / "publish-metrics.json"
PIPELINE_FAILURES = LOG_DIR / "pipeline-failures.log"
OUTPUT_FILE       = LOG_DIR / "error-classification.json"

# ── Category definitions ──────────────────────────────────────────────────────

CATEGORIES = [
    "no_articles_scan",
    "rewriter_timeout",
    "rewriter_error",
    "hugo_build",
    "image_gen",
    "quality_gate",
    "firehose_filter",
    "python_error",
    "unknown",
]

CATEGORY_LABELS = {
    "no_articles_scan":  "No articles from scanner",
    "rewriter_timeout":  "Rewriter LLM timeout",
    "rewriter_error":    "Rewriter exception",
    "hugo_build":        "Hugo build failure",
    "image_gen":         "Image generation failure",
    "quality_gate":      "Quality gate dropped all",
    "firehose_filter":   "Firehose returned 0 articles",
    "python_error":      "Python/import exception",
    "unknown":           "Unknown failure",
}

# ── Log loading ────────────────────────────────────────────────────────────────

def load_metrics_runs(limit: int) -> list[dict]:
    """Load last `limit` pipeline runs from metrics.json."""
    if not METRICS_FILE.exists():
        return []
    with open(METRICS_FILE) as f:
        data = json.load(f)
    runs = data if isinstance(data, list) else data.get("runs", [])
    return runs[-limit:]


def parse_auto_publish_logs(limit: int) -> dict[str, dict]:
    """
    Parse last `limit` auto_publish_*.log files.
    Returns dict: timestamp_prefix → {text, timestamp}
    """
    logs = sorted(
        glob.glob(str(LOG_DIR / "auto_publish_*.log")),
        reverse=True
    )[:limit]

    result = {}
    for path in logs:
        name = os.path.basename(path)
        # Extract timestamp from filename: auto_publish_20260321_112001.log
        m = re.match(r"auto_publish_(\d{8}_\d{6})\.log", name)
        ts_str = m.group(1) if m else name
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        result[ts_str] = {"text": text, "path": path}
    return result


# ── Classifier ────────────────────────────────────────────────────────────────

def classify_run(run: dict, log_text: str = "") -> str:
    """
    Classify a single pipeline run dict into a category string.
    Uses both structured metrics.json data and raw log text.
    """
    steps   = run.get("steps", {})
    errors  = run.get("errors", [])
    success = run.get("success", True)

    if success:
        return None  # not a failure

    errors_lower = " ".join(errors).lower()
    log_lower    = log_text.lower()

    # ── Python/import exceptions (check log first — most specific) ────────────
    py_patterns = [
        r"NameError:", r"ImportError:", r"ModuleNotFoundError:",
        r"AttributeError:", r"TypeError:", r"SyntaxError:",
        r"Traceback \(most recent call last\)",
    ]
    if any(re.search(p, log_text) for p in py_patterns):
        return "python_error"

    # ── Hugo build failures ───────────────────────────────────────────────────
    hugo_step = steps.get("build", {})
    if hugo_step and not hugo_step.get("success", True):
        return "hugo_build"
    if any(p in log_lower for p in ["hugo build", "error building site", "hugo: error",
                                     "failed to build", "build failed"]):
        return "hugo_build"
    if "hugo_build" in errors_lower or "build failed" in errors_lower:
        return "hugo_build"

    # ── Image generation failures ─────────────────────────────────────────────
    img_step = steps.get("image_gen", steps.get("images", {}))
    if img_step and not img_step.get("success", True):
        return "image_gen"
    img_patterns = ["image generation failed", "pexels failed", "unsplash failed",
                    "kie.*failed", "all image sources failed", "[image] all"]
    if any(p in log_lower for p in img_patterns):
        return "image_gen"

    # ── Rewriter timeout ──────────────────────────────────────────────────────
    rewriter_step = steps.get("rewriter", {})
    rewriter_dur  = rewriter_step.get("duration_sec", 0)
    # Note: avoid matching "0 skipped due to timeout" from scanner summary line
    timeout_patterns = ["rewriter.*timeout", "rewriter.*timed out", "readtimeouterror",
                        "openai.*timeout", "connection.*timed", "llm.*timeout",
                        "api.*timed out", "request.*timed out"]
    if any(re.search(p, log_lower) for p in timeout_patterns):
        return "rewriter_timeout"
    if rewriter_dur and rewriter_dur > 115:
        return "rewriter_timeout"

    # ── Rewriter other errors ─────────────────────────────────────────────────
    if rewriter_step and not rewriter_step.get("success", True):
        return "rewriter_error"
    if "rewriter" in errors_lower and "0 articles" in errors_lower:
        return "rewriter_error"
    if any(p in log_lower for p in ["[writer] error", "openai error", "apierror",
                                     "ratelimit", "rate limit"]):
        return "rewriter_error"

    # ── Quality gate dropped all ───────────────────────────────────────────────
    gate_step = steps.get("quality_gate", {})
    if gate_step:
        passed  = gate_step.get("passed", 1)
        dropped = gate_step.get("dropped", 0)
        if passed == 0 and dropped > 0:
            return "quality_gate"
    if "quality gate" in errors_lower and "0" in errors_lower:
        return "quality_gate"

    # ── No articles from scanner (most common) — CHECK BEFORE firehose ──────────
    # Always check structural "no articles" signals FIRST to avoid log mismatches.
    scanner_step = steps.get("scanner", {})
    no_article_patterns = [
        "no articles found after scan",
        "no new articles",
        "0 articles after dedup",
        "no articles to process",
        "scanner returned 0",
    ]
    if any(p in errors_lower for p in no_article_patterns):
        return "no_articles_scan"

    # Structural check: scanner ran successfully but total=0
    if scanner_step.get("success") and scanner_step.get("total", -1) == 0:
        return "no_articles_scan"

    # Only scanner step ran (pipeline stopped early due to no articles)
    if list(steps.keys()) == ["scanner"] and scanner_step.get("success", True):
        return "no_articles_scan"

    # ── Firehose-only returned nothing ────────────────────────────────────────
    # Only classify as firehose_filter if BOTH rss AND firehose counts are explicitly 0.
    # Do NOT use log_lower for this — log text from adjacent runs contains "firehose"
    # and "0 articles" as normal scanner output, causing false positives.
    firehose_n = scanner_step.get("firehose_count", 0)
    rss_n      = scanner_step.get("rss_count", -1)   # -1 = field absent (old schema)
    if rss_n == 0 and firehose_n == 0 and scanner_step.get("total", 0) == 0:
        return "firehose_filter"

    # ── Fallback ──────────────────────────────────────────────────────────────
    return "unknown"


# ── Trend analysis ────────────────────────────────────────────────────────────

def calc_trend(recent: list[str], older: list[str], category: str) -> str:
    """
    Compare frequency of `category` in recent half vs older half.
    Returns 'improving', 'worsening', 'stable', or 'new'.
    """
    if not older:
        return "new" if recent.count(category) > 0 else "stable"

    recent_rate = recent.count(category) / max(len(recent), 1)
    older_rate  = older.count(category) / max(len(older), 1)

    diff = recent_rate - older_rate
    if diff > 0.05:
        return "worsening"
    if diff < -0.05:
        return "improving"
    return "stable"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Classify pipeline run failures")
    parser.add_argument("--limit",   type=int, default=50,
                        help="Number of recent runs to analyze (default: 50)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print classification for each run")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)

    # ── Load data ─────────────────────────────────────────────────────────────
    runs = load_metrics_runs(args.limit)
    print(f"[classifier] Analyzing {len(runs)} runs (limit={args.limit})")

    # Load log files for supplementary text matching
    log_texts = parse_auto_publish_logs(args.limit)

    # ── Classify each run ─────────────────────────────────────────────────────
    classified = []
    failure_categories = []

    for run in runs:
        ts = run.get("timestamp", "")
        success = run.get("success", True)

        # Try to find matching log text by timestamp
        # metrics.json timestamps look like: 2026-03-21T11:21:04.294039+00:00
        # log files look like: auto_publish_20260321_112001.log
        log_text = ""
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                # Try exact match first, then ±1min
                for delta_min in range(-2, 3):
                    candidate = (dt + timedelta(minutes=delta_min)).strftime("%Y%m%d_%H%M")
                    # Match first 11 chars of the ts prefix
                    for log_key, log_data in log_texts.items():
                        if log_key.startswith(candidate[:11]):
                            log_text = log_data["text"]
                            break
                    if log_text:
                        break
            except (ValueError, OverflowError):
                pass

        category = classify_run(run, log_text)

        # Determine outcome: "ok", "skip", or "error"
        # "skip" = no_articles_scan is expected behavior, not a real failure
        if success:
            outcome = "ok"
        elif category == "no_articles_scan":
            outcome = "skip"
        else:
            outcome = "error"

        entry = {
            "timestamp": ts,
            "success":   success,
            "outcome":   outcome,
            "category":  category,
            "article_count": run.get("article_count", 0),
            "duration_sec":  run.get("total_duration_sec", 0),
            "errors":        run.get("errors", [])[:3],
            "steps":         list(run.get("steps", {}).keys()),
        }
        classified.append(entry)

        # Only count actual errors as failures — skips are expected
        if outcome == "error" and category:
            failure_categories.append(category)
            if args.verbose:
                short_ts = ts[:16] if ts else "?"
                errs = ", ".join(run.get("errors", []))[:60]
                print(f"  {short_ts}  [{category:20s}]  {errs}")
        elif outcome == "skip" and args.verbose:
            short_ts = ts[:16] if ts else "?"
            print(f"  {short_ts}  [skip: no_articles_scan]")

    # ── Build category summary ────────────────────────────────────────────────
    counts          = Counter(failure_categories)
    total_runs      = len(runs)
    total_skips     = sum(1 for e in classified if e.get("outcome") == "skip")
    total_errors    = len(failure_categories)
    total_ok        = total_runs - total_skips - total_errors
    total_failures  = total_errors   # backward compat label, now = real errors only

    # Split into halves for trend analysis
    half = len(failure_categories) // 2
    older_cats  = failure_categories[:half]
    recent_cats = failure_categories[half:]

    # Last occurrence per category
    last_occurrence: dict[str, str] = {}
    for entry in reversed(classified):
        cat = entry.get("category")
        if cat and cat not in last_occurrence:
            last_occurrence[cat] = entry["timestamp"]

    category_summary = {}
    for cat in CATEGORIES:
        n = counts.get(cat, 0)
        if n == 0 and cat not in last_occurrence:
            continue
        category_summary[cat] = {
            "label":           CATEGORY_LABELS[cat],
            "count":           n,
            "pct_of_failures": round(100 * n / max(total_failures, 1), 1),
            "pct_of_runs":     round(100 * n / max(total_runs, 1), 1),
            "trend":           calc_trend(recent_cats, older_cats, cat),
            "last_occurrence": last_occurrence.get(cat, ""),
        }

    # ── Overall health ────────────────────────────────────────────────────────
    # Error rate = real errors / total (skips are expected, not failures)
    error_rate   = round(100 * total_errors / max(total_runs, 1), 1)
    # Publish hit rate = ok / (ok + skip) — how often a scan finds new articles
    hit_rate     = round(100 * total_ok / max(total_ok + total_skips, 1), 1)
    # Legacy success_rate (backward compat) = ok + skip = "ran without crashing"
    success_rate = round(100 * (total_ok + total_skips) / max(total_runs, 1), 1)

    # Health rating based on ERROR rate (not including skips)
    if error_rate <= 5:
        health = "good"
    elif error_rate <= 15:
        health = "degraded"
    else:
        health = "critical"

    # Top issue (real errors only)
    top_category, top_count = counts.most_common(1)[0] if counts else ("none", 0)

    output = {
        "generated_at":     now.isoformat(),
        "runs_analyzed":    total_runs,
        "total_ok":         total_ok,
        "total_skips":      total_skips,
        "total_errors":     total_errors,
        # backward compat fields
        "total_failures":   total_errors,
        "total_success":    total_ok + total_skips,
        "success_rate_pct": success_rate,
        "error_rate_pct":   error_rate,
        "publish_hit_rate_pct": hit_rate,
        "health":           health,
        "top_issue":        top_category,
        "top_issue_count":  top_count,
        "categories":       category_summary,
        "runs":             classified,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"[classifier] Saved: {OUTPUT_FILE}")

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"Pipeline Error Classification — last {total_runs} runs")
    print(f"  ✅ ok={total_ok}  ⏭ skip={total_skips}  ❌ error={total_errors}")
    print(f"{'='*55}")
    print(f"Error rate: {error_rate}% ({total_errors} real errors / {total_runs} runs)  health={health}")
    print(f"Health: {health}  |  Publish hit rate: {hit_rate}%  |  No-crash rate: {success_rate}%")
    print(f"\nReal error breakdown ({total_errors} errors — skips excluded):")
    for cat, info in sorted(category_summary.items(), key=lambda x: -x[1]["count"]):
        bar   = "█" * (info["count"] // max(1, total_failures // 20))
        trend = {"worsening": "↑", "improving": "↓", "stable": "→", "new": "★"}.get(info["trend"], "?")
        print(f"  {trend} {info['count']:3d} ({info['pct_of_failures']:5.1f}%)  "
              f"{cat:<22s}  {bar}")
        if info["last_occurrence"]:
            print(f"      last: {info['last_occurrence'][:16]}")
    print(f"{'='*55}\n")

    return output


if __name__ == "__main__":
    main()
