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
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE   = os.path.dirname(os.path.abspath(__file__))
_ROOT   = os.path.dirname(_HERE)            # project root
POSTS_DIR   = os.path.join(_ROOT, "content", "posts")
LOCK_FILE   = os.path.join(_HERE, ".pipeline_lock")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
LAST_ARTICLE_WARN_MINUTES = 120   # 2 h — warn if no article during daytime
DAYTIME_START_HEL = 6             # 06:00 Helsinki (UTC+2/+3)
DAYTIME_END_HEL   = 23            # 23:00 Helsinki
LOCK_STALE_MINUTES = 30           # stale lock threshold
DISK_WARN_GB       = 2.0          # warn if free < 2 GB
MEM_WARN_MB        = 200          # warn if available < 200 MB

DEFAULT_DISCORD_ALERT_CHANNEL_ID = "1482082645553713366"  # #operations
ENV_CANDIDATES = [
    Path(_ROOT) / ".env",
    Path(_ROOT) / "pipeline" / ".env",
    Path("/workspace/.env"),
    Path("/home/pertt/.openclaw/.env"),
]


def _load_env_files() -> None:
    for path in ENV_CANDIDATES:
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
        except Exception:
            continue


_load_env_files()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
DISCORD_ALERT_CHANNEL_ID = os.environ.get("DISCORD_PIPELINE_ALERT_CHANNEL_ID", DEFAULT_DISCORD_ALERT_CHANNEL_ID)
LOG_DIR_OVERRIDE = None  # set by tests

LOG_DIR = os.path.join(_HERE, "logs")
DISCORD_HTTP_USER_AGENT = "Mozilla/5.0"


def _read_env_key_from_files(key_name: str) -> str:
    for path in ENV_CANDIDATES:
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith(f"{key_name}="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            continue
    return ""


def _post_via_discord_bot(body: str) -> bool:
    token = (
        os.environ.get("OPENCLAW_DISCORD_BOT_TOKEN")
        or os.environ.get("DISCORD_BOT_TOKEN")
        or _read_env_key_from_files("OPENCLAW_DISCORD_BOT_TOKEN")
        or _read_env_key_from_files("DISCORD_BOT_TOKEN")
    )
    if not token or not DISCORD_ALERT_CHANNEL_ID:
        return False
    payload = json.dumps({"content": body[:1900]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{DISCORD_ALERT_CHANNEL_ID}/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bot {token}",
            "User-Agent": DISCORD_HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201, 204)
    except Exception as e:
        print(f"[health_check] Discord bot notify failed: {e}")
        return False


def _send_discord_message(body: str) -> bool:
    if DISCORD_WEBHOOK_URL:
        payload = json.dumps({"content": body}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": DISCORD_HTTP_USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 204):
                    return True
        except Exception as e:
            print(f"[health_check] Discord webhook notify failed: {e}")
    return _post_via_discord_bot(body)


def notify_discord_failure(step: str, error: str, context: str = "") -> bool:
    """Post a failure alert to Discord via webhook.

    Returns True if message was sent successfully.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = f"🚨 **Pipeline failure** — `{step}`\n"
    body += f"**Time:** {timestamp}\n"
    body += f"**Error:** {error[:400]}\n"
    if context:
        body += f"**Context:** {context[:300]}\n"

    sent = _send_discord_message(body)
    if not sent:
        print(f"[health_check] alert not sent for: {step}: {error}")
    return sent


def notify_discord_crash(step: str, exception: Exception, *, tb: str = "") -> bool:
    """Post a crash alert (unhandled exception) to Discord via webhook.

    Returns True if message was sent successfully.
    """
    error_str = f"{type(exception).__name__}: {exception}"
    context = tb[:600] if tb else ""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = f"💥 **Pipeline crash** — `{step}`\n"
    body += f"**Time:** {timestamp}\n"
    body += f"**Error:** {error_str[:400]}\n"
    if context:
        body += f"```\n{context[:500]}\n```\n"

    sent = _send_discord_message(body)
    if not sent:
        print(f"[health_check] CRASH [{step}]: {error_str}")
        if context:
            print(context)
    return sent


def notify_discord_warning(step: str, message: str, details: str | None = None) -> bool:
    """Post a warning (non-fatal) to Discord."""
    combined = message if not details else f"{message}\n{details}"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = f"⚠️ **Pipeline warning** — `{step}`\n"
    body += f"**Time:** {timestamp}\n"
    body += f"**Message:** {combined[:500]}\n"

    sent = _send_discord_message(body)
    if not sent:
        print(f"[health_check] WARNING [{step}]: {combined}")
    return sent


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


def _helsinki_now() -> datetime:
    now = _utc_now()
    if ZoneInfo is not None:
        try:
            return now.astimezone(ZoneInfo("Europe/Helsinki"))
        except Exception:
            pass
    return now + timedelta(hours=2)


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
    hel_now = _helsinki_now()
    hel_hour = hel_now.hour

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
            "hel_tz": getattr(hel_now.tzinfo, "key", None) or str(hel_now.tzinfo),
        },
    }


def check_pipeline_lock() -> dict:
    """Warn if .pipeline_lock is stale or points at a dead pipeline process."""
    if not os.path.exists(LOCK_FILE):
        return {
            "status": "OK",
            "message": "No pipeline lock file",
            "value": {"lock_exists": False},
        }

    age_minutes = (time.time() - os.path.getmtime(LOCK_FILE)) / 60.0

    lock_pid = None
    try:
        with open(LOCK_FILE, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
        if first_line:
            lock_pid = int(first_line)
    except Exception:
        lock_pid = None

    pid_alive = None
    if lock_pid is not None:
        try:
            os.kill(lock_pid, 0)
            pid_alive = True
        except ProcessLookupError:
            pid_alive = False
        except PermissionError:
            pid_alive = True
        except Exception:
            pid_alive = None

    if lock_pid is not None and pid_alive is False:
        try:
            os.remove(LOCK_FILE)
            return {
                "status": "OK",
                "message": f"Removed dead .pipeline_lock for PID {lock_pid}",
                "value": {
                    "lock_exists": False,
                    "dead_lock_cleared": True,
                    "age_minutes": round(age_minutes, 1),
                    "pid": lock_pid,
                    "pid_alive": False,
                },
            }
        except Exception as e:
            return {
                "status": "WARN",
                "message": f".pipeline_lock points to dead PID {lock_pid} and could not be removed: {e}",
                "value": {
                    "lock_exists": True,
                    "dead_lock_cleared": False,
                    "age_minutes": round(age_minutes, 1),
                    "pid": lock_pid,
                    "pid_alive": False,
                },
            }

    if age_minutes > LOCK_STALE_MINUTES:
        return {
            "status": "WARN",
            "message": (
                f".pipeline_lock is {age_minutes:.0f} min old "
                f"(>{LOCK_STALE_MINUTES} min — pipeline may be stuck)"
            ),
            "value": {
                "lock_exists": True,
                "age_minutes": round(age_minutes, 1),
                "pid": lock_pid,
                "pid_alive": pid_alive,
            },
        }

    return {
        "status": "OK",
        "message": f"Pipeline lock is active but fresh ({age_minutes:.0f} min old)",
        "value": {
            "lock_exists": True,
            "age_minutes": round(age_minutes, 1),
            "pid": lock_pid,
            "pid_alive": pid_alive,
        },
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
