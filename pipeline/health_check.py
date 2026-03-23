"""
Pipeline health check & Discord failure alerting.

Usage:
    python3 pipeline/health_check.py            # print JSON to stdout
    python3 pipeline/health_check.py --alert    # also send Discord alert on warn/error

JSON output schema:
    {
      "ok": bool,           # false if any check is ERROR severity
      "timestamp": str,     # ISO-8601 UTC
      "checks": {
        "<name>": {
          "status": "OK" | "WARN" | "ERROR",
          "message": str,
          "value": <any>    # raw measured value (age_minutes, free_gb, etc.)
        }
      },
      "summary": str        # human-readable one-liner
    }
"""
import glob
import json
import os
import shutil
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE   = os.path.dirname(os.path.abspath(__file__))
_ROOT   = os.path.dirname(_HERE)            # project root
POSTS_DIR   = os.path.join(_ROOT, "content", "posts")
LOCK_FILE   = os.path.join(_ROOT, ".pipeline_lock")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
LAST_ARTICLE_WARN_MINUTES = 120   # 2 h — warn if no article during daytime
DAYTIME_START_HEL = 6             # 06:00 Helsinki (UTC+2/+3)
DAYTIME_END_HEL   = 23            # 23:00 Helsinki
LOCK_STALE_MINUTES = 30           # stale lock threshold
DISK_WARN_GB       = 2.0          # warn if free < 2 GB
MEM_WARN_MB        = 200          # warn if available < 200 MB

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
LOG_DIR_OVERRIDE = None  # set by tests

LOG_DIR = os.path.join(_HERE, "logs")


def notify_discord_failure(step: str, error: str, context: str = "") -> bool:
    """Post a failure alert to Discord via webhook.

    Returns True if message was sent successfully.
    """
    if not DISCORD_WEBHOOK_URL:
        print(f"[health_check] DISCORD_PIPELINE_WEBHOOK not set — alert not sent for: {step}: {error}")
        return False

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = f"🚨 **Pipeline failure** — `{step}`\n"
    body += f"**Time:** {timestamp}\n"
    body += f"**Error:** {error[:400]}\n"
    if context:
        body += f"**Context:** {context[:300]}\n"

    payload = json.dumps({"content": body}).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[health_check] Discord notify failed: {e}")
        return False


def notify_discord_warning(step: str, message: str) -> bool:
    """Post a warning (non-fatal) to Discord."""
    if not DISCORD_WEBHOOK_URL:
        print(f"[health_check] WARNING [{step}]: {message}")
        return False

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = f"⚠️ **Pipeline warning** — `{step}`\n"
    body += f"**Time:** {timestamp}\n"
    body += f"**Message:** {message[:500]}\n"

    payload = json.dumps({"content": body}).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[health_check] Discord warning notify failed: {e}")
        return False


def write_metrics(metrics: dict) -> str:
    """Write structured metrics record to logs/metrics.json (append-style rolling file)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    metrics_file = os.path.join(LOG_DIR, "metrics.json")

    records = []
    if os.path.exists(metrics_file):
        try:
            with open(metrics_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                records = []
        except Exception:
            records = []

    records.append(metrics)
    # Keep last 200 records
    records = records[-200:]

    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    return metrics_file


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def check_last_article() -> dict:
    """Return time since last published article and warn if stale during daytime."""
    md_files = glob.glob(os.path.join(POSTS_DIR, "*.md"))
    if not md_files:
        return {
            "status": "ERROR",
            "message": "No articles found in content/posts/",
            "value": None,
        }

    newest_mtime = max(os.path.getmtime(f) for f in md_files)
    age_minutes = (time.time() - newest_mtime) / 60.0
    newest_dt = datetime.fromtimestamp(newest_mtime, tz=timezone.utc)

    # Determine if we're in Helsinki daytime.
    # Helsinki is UTC+2 (EET) or UTC+3 (EEST). Use UTC+2 as a conservative
    # estimate (if it's daytime in UTC+2, it's definitely daytime in UTC+3).
    now_utc = _utc_now()
    hel_hour = (now_utc.hour + 2) % 24  # conservative: UTC+2

    in_daytime = DAYTIME_START_HEL <= hel_hour < DAYTIME_END_HEL

    if age_minutes > LAST_ARTICLE_WARN_MINUTES and in_daytime:
        status = "WARN"
        msg = (
            f"Last article published {age_minutes:.0f} min ago "
            f"(>{LAST_ARTICLE_WARN_MINUTES} min threshold, daytime active)"
        )
    elif age_minutes > LAST_ARTICLE_WARN_MINUTES and not in_daytime:
        status = "OK"
        msg = (
            f"Last article published {age_minutes:.0f} min ago "
            f"(outside daytime hours, no alert)"
        )
    else:
        status = "OK"
        msg = f"Last article published {age_minutes:.0f} min ago"

    return {
        "status": status,
        "message": msg,
        "value": {
            "age_minutes": round(age_minutes, 1),
            "newest_file_utc": newest_dt.isoformat(),
            "in_daytime": in_daytime,
            "hel_hour": hel_hour,
        },
    }


def check_pipeline_lock() -> dict:
    """Warn if .pipeline_lock exists and is older than LOCK_STALE_MINUTES."""
    if not os.path.exists(LOCK_FILE):
        return {
            "status": "OK",
            "message": "No pipeline lock file",
            "value": {"lock_exists": False},
        }

    age_minutes = (time.time() - os.path.getmtime(LOCK_FILE)) / 60.0
    if age_minutes > LOCK_STALE_MINUTES:
        return {
            "status": "WARN",
            "message": (
                f".pipeline_lock is {age_minutes:.0f} min old "
                f"(>{LOCK_STALE_MINUTES} min — pipeline may be stuck)"
            ),
            "value": {"lock_exists": True, "age_minutes": round(age_minutes, 1)},
        }

    return {
        "status": "OK",
        "message": f"Pipeline lock is active but fresh ({age_minutes:.0f} min old)",
        "value": {"lock_exists": True, "age_minutes": round(age_minutes, 1)},
    }


def check_disk_space() -> dict:
    """Warn if disk free space drops below DISK_WARN_GB."""
    try:
        usage = shutil.disk_usage(_ROOT)
    except Exception as e:
        return {"status": "ERROR", "message": f"disk_usage failed: {e}", "value": None}

    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    used_pct = 100.0 * usage.used / usage.total

    if free_gb < DISK_WARN_GB:
        status = "WARN"
        msg = f"Disk free: {free_gb:.1f} GB (<{DISK_WARN_GB} GB threshold)"
    else:
        status = "OK"
        msg = f"Disk free: {free_gb:.1f} GB / {total_gb:.1f} GB ({used_pct:.0f}% used)"

    return {
        "status": status,
        "message": msg,
        "value": {
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_pct": round(used_pct, 1),
        },
    }


def check_memory() -> dict:
    """Warn if available memory drops below MEM_WARN_MB.

    Reads /proc/meminfo — works on Linux. Returns OK with a note on other OSes.
    """
    meminfo_path = "/proc/meminfo"
    if not os.path.exists(meminfo_path):
        return {
            "status": "OK",
            "message": "/proc/meminfo not available (non-Linux host)",
            "value": None,
        }

    try:
        meminfo: dict[str, int] = {}
        with open(meminfo_path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    try:
                        meminfo[key] = int(parts[1])  # kB
                    except ValueError:
                        pass

        # MemAvailable is the best single indicator of usable free memory.
        available_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        total_kb = meminfo.get("MemTotal", 0)
        available_mb = available_kb / 1024
        total_mb = total_kb / 1024
        used_pct = 100.0 * (1 - available_kb / total_kb) if total_kb else 0

        if available_mb < MEM_WARN_MB:
            status = "WARN"
            msg = f"Memory available: {available_mb:.0f} MB (<{MEM_WARN_MB} MB threshold)"
        else:
            status = "OK"
            msg = f"Memory available: {available_mb:.0f} MB / {total_mb:.0f} MB ({used_pct:.0f}% used)"

        return {
            "status": status,
            "message": msg,
            "value": {
                "available_mb": round(available_mb, 0),
                "total_mb": round(total_mb, 0),
                "used_pct": round(used_pct, 1),
            },
        }
    except Exception as e:
        return {"status": "ERROR", "message": f"Memory check failed: {e}", "value": None}


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def run_checks() -> dict:
    """Run all health checks and return a JSON-serialisable summary dict."""
    now = _utc_now()

    checks = {
        "last_article":   check_last_article(),
        "pipeline_lock":  check_pipeline_lock(),
        "disk_space":     check_disk_space(),
        "memory":         check_memory(),
    }

    statuses = [c["status"] for c in checks.values()]
    overall_ok = "ERROR" not in statuses
    has_warn   = "WARN" in statuses

    if not overall_ok:
        error_checks = [k for k, v in checks.items() if v["status"] == "ERROR"]
        summary = f"ERROR in: {', '.join(error_checks)}"
    elif has_warn:
        warn_checks = [k for k, v in checks.items() if v["status"] == "WARN"]
        summary = f"WARN in: {', '.join(warn_checks)}"
    else:
        summary = "All checks OK"

    return {
        "ok": overall_ok,
        "timestamp": now.isoformat(),
        "checks": checks,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline health check")
    parser.add_argument(
        "--alert", action="store_true",
        help="Send Discord alert if any check is WARN or ERROR"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress JSON output (useful when called from cron)"
    )
    args = parser.parse_args()

    result = run_checks()

    if not args.quiet:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.alert and not result["ok"]:
        notify_discord_failure(
            step="health_check",
            error=result["summary"],
            context=json.dumps(
                {k: v["message"] for k, v in result["checks"].items()
                 if v["status"] != "OK"},
                ensure_ascii=False,
            ),
        )
    elif args.alert and any(
        c["status"] == "WARN" for c in result["checks"].values()
    ):
        notify_discord_warning(
            step="health_check",
            message=result["summary"] + "\n" + json.dumps(
                {k: v["message"] for k, v in result["checks"].items()
                 if v["status"] == "WARN"},
                ensure_ascii=False,
            ),
        )

    # Exit 1 if any ERROR so cron/CI can detect failures
    sys.exit(0 if result["ok"] else 1)
