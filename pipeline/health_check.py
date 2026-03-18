#!/usr/bin/env python3
"""
Pipeline Health Check — monitors uutistenlukija pipeline health.

Checks:
  1. Cron running? (auto_publish logs exist and recent)
  2. Last successful run < 4h ago?
  3. Any errors in last 3 runs?
  4. Any step > 5 min (slow)?
  5. Error rate > 10% over last 20 runs?

Usage:
  python3 health_check.py          # Human-readable report
  python3 health_check.py --json   # Machine-readable output
  python3 health_check.py --brief  # One-line summary (for heartbeats)

Exit codes:
  0 = healthy
  1 = warnings (degraded)
  2 = critical (action needed)
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone, timedelta

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PIPELINE_DIR, "logs")
METRICS_FILE = os.path.join(LOG_DIR, "metrics.json")

SLOW_STEP_SEC = 300        # 5 minutes
MAX_HOURS_SINCE_RUN = 4    # alert if no successful run in this window
ERROR_RATE_WINDOW = 20     # look at last N runs for error rate
ERROR_RATE_THRESHOLD = 0.1 # 10%


def load_metrics():
    """Load metrics.json, return list of run records."""
    if not os.path.exists(METRICS_FILE):
        return []
    try:
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def check_cron_running():
    """Check if auto_publish cron is producing logs."""
    pattern = os.path.join(LOG_DIR, "auto_publish_*.log")
    logs = sorted(glob.glob(pattern))
    if not logs:
        return {
            "status": "critical",
            "message": "No auto_publish logs found — cron may not be configured",
        }

    latest = logs[-1]
    mtime = os.path.getmtime(latest)
    age_hours = (datetime.now(timezone.utc).timestamp() - mtime) / 3600

    if age_hours > MAX_HOURS_SINCE_RUN:
        return {
            "status": "warning",
            "message": f"Latest cron log is {age_hours:.1f}h old (>{MAX_HOURS_SINCE_RUN}h threshold)",
            "latest_log": os.path.basename(latest),
            "age_hours": round(age_hours, 1),
        }
    return {
        "status": "ok",
        "message": f"Cron active — latest log {age_hours:.1f}h ago",
        "latest_log": os.path.basename(latest),
        "age_hours": round(age_hours, 1),
    }


def check_last_success(metrics):
    """Check if last successful run was < 4h ago."""
    successes = [m for m in metrics if m.get("success")]
    if not successes:
        return {
            "status": "critical",
            "message": "No successful pipeline runs recorded in metrics",
        }

    latest = successes[-1]
    try:
        ts = datetime.fromisoformat(latest["timestamp"])
    except (ValueError, KeyError):
        return {
            "status": "warning",
            "message": "Could not parse timestamp of last successful run",
        }

    age = datetime.now(timezone.utc) - ts
    age_hours = age.total_seconds() / 3600

    if age_hours > MAX_HOURS_SINCE_RUN:
        return {
            "status": "warning",
            "message": f"Last success was {age_hours:.1f}h ago (>{MAX_HOURS_SINCE_RUN}h)",
            "last_success": latest["timestamp"],
            "age_hours": round(age_hours, 1),
        }
    return {
        "status": "ok",
        "message": f"Last success {age_hours:.1f}h ago",
        "last_success": latest["timestamp"],
        "age_hours": round(age_hours, 1),
        "articles": latest.get("article_count", 0),
        "duration_sec": latest.get("total_duration_sec"),
    }


def check_recent_errors(metrics):
    """Check last 3 runs for errors."""
    last3 = metrics[-3:] if len(metrics) >= 3 else metrics
    if not last3:
        return {"status": "ok", "message": "No runs to check"}

    errored_runs = []
    for run in last3:
        errors = run.get("errors", [])
        if errors or not run.get("success"):
            errored_runs.append({
                "timestamp": run.get("timestamp"),
                "errors": errors,
                "success": run.get("success", False),
            })

    if not errored_runs:
        return {"status": "ok", "message": f"Last {len(last3)} runs clean"}

    return {
        "status": "warning" if len(errored_runs) < len(last3) else "critical",
        "message": f"{len(errored_runs)}/{len(last3)} recent runs had errors",
        "errored_runs": errored_runs,
    }


def check_slow_steps(metrics):
    """Check if any steps exceeded the 5-min threshold recently."""
    last5 = metrics[-5:] if len(metrics) >= 5 else metrics
    slow_steps = []

    for run in last5:
        for step_name, step_data in run.get("steps", {}).items():
            dur = step_data.get("duration_sec", 0)
            if dur > SLOW_STEP_SEC:
                slow_steps.append({
                    "run": run.get("timestamp"),
                    "step": step_name,
                    "duration_sec": dur,
                })

    if not slow_steps:
        return {"status": "ok", "message": "No slow steps in recent runs"}

    return {
        "status": "warning",
        "message": f"{len(slow_steps)} slow step(s) detected (>{SLOW_STEP_SEC}s)",
        "slow_steps": slow_steps,
    }


def check_error_rate(metrics):
    """Check error rate over last N runs."""
    window = metrics[-ERROR_RATE_WINDOW:]
    if len(window) < 3:
        return {"status": "ok", "message": f"Not enough data ({len(window)} runs)"}

    failed = sum(1 for m in window if not m.get("success"))
    rate = failed / len(window)

    if rate > ERROR_RATE_THRESHOLD:
        return {
            "status": "critical" if rate > 0.3 else "warning",
            "message": f"Error rate {rate:.0%} ({failed}/{len(window)} runs failed) — exceeds {ERROR_RATE_THRESHOLD:.0%} threshold",
            "error_rate": round(rate, 3),
            "failed": failed,
            "total": len(window),
        }
    return {
        "status": "ok",
        "message": f"Error rate {rate:.0%} ({failed}/{len(window)}) — within threshold",
        "error_rate": round(rate, 3),
    }


def check_step_timings(metrics):
    """Get average step durations from recent runs for the report."""
    last10 = metrics[-10:] if len(metrics) >= 10 else metrics
    step_totals = {}

    for run in last10:
        for step_name, step_data in run.get("steps", {}).items():
            dur = step_data.get("duration_sec", 0)
            if step_name not in step_totals:
                step_totals[step_name] = []
            step_totals[step_name].append(dur)

    averages = {}
    for name, durations in step_totals.items():
        averages[name] = {
            "avg_sec": round(sum(durations) / len(durations), 1),
            "max_sec": round(max(durations), 1),
            "min_sec": round(min(durations), 1),
            "runs": len(durations),
        }

    return averages


def run_health_check():
    """Run all checks, return structured result."""
    metrics = load_metrics()

    checks = {
        "cron": check_cron_running(),
        "last_success": check_last_success(metrics),
        "recent_errors": check_recent_errors(metrics),
        "slow_steps": check_slow_steps(metrics),
        "error_rate": check_error_rate(metrics),
    }

    step_averages = check_step_timings(metrics)

    # Determine overall status
    statuses = [c["status"] for c in checks.values()]
    if "critical" in statuses:
        overall = "critical"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "healthy"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "total_runs_recorded": len(metrics),
        "checks": checks,
        "step_averages": step_averages,
    }


def print_report(result):
    """Print human-readable health report."""
    status_emoji = {"healthy": "✅", "warning": "⚠️", "critical": "🚨"}
    check_emoji = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}

    print("=" * 60)
    print(f"  PIPELINE HEALTH CHECK")
    print(f"  {result['timestamp']}")
    print(f"  Overall: {status_emoji.get(result['overall'], '?')} {result['overall'].upper()}")
    print(f"  Runs tracked: {result['total_runs_recorded']}")
    print("=" * 60)

    for name, check in result["checks"].items():
        emoji = check_emoji.get(check["status"], "?")
        print(f"\n  {emoji} {name.upper()}")
        print(f"     {check['message']}")

    if result["step_averages"]:
        print(f"\n  📊 STEP AVERAGES (last 10 runs)")
        for step, data in result["step_averages"].items():
            flag = " ⚠️ SLOW" if data["max_sec"] > SLOW_STEP_SEC else ""
            print(f"     {step}: avg {data['avg_sec']}s / max {data['max_sec']}s / min {data['min_sec']}s ({data['runs']} runs){flag}")

    print("\n" + "=" * 60)


def print_brief(result):
    """One-line summary for heartbeats."""
    status_emoji = {"healthy": "✅", "warning": "⚠️", "critical": "🚨"}
    issues = [
        f"{name}: {check['message']}"
        for name, check in result["checks"].items()
        if check["status"] != "ok"
    ]
    if issues:
        print(f"Pipeline {status_emoji.get(result['overall'], '?')} — {'; '.join(issues)}")
    else:
        print(f"Pipeline {status_emoji.get(result['overall'], '?')} healthy — {result['total_runs_recorded']} runs tracked")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Health Check")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--brief", action="store_true", help="One-line summary")
    args = parser.parse_args()

    result = run_health_check()

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.brief:
        print_brief(result)
    else:
        print_report(result)

    if result["overall"] == "critical":
        sys.exit(2)
    elif result["overall"] == "warning":
        sys.exit(1)
    else:
        sys.exit(0)
