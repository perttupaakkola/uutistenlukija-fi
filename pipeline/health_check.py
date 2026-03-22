"""
Pipeline health check & Discord failure alerting.
"""
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


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


def notify_discord_crash(step: str, exc: Exception, slug: str = "", tb: str = "") -> bool:
    """Post a crash alert with traceback to Discord.

    Intended for unexpected exceptions (not quality-gate rejections).
    Call from except blocks: notify_discord_crash("publisher", e, slug=article_slug, tb=traceback.format_exc())

    Returns True if message was sent successfully.
    """
    import traceback as _tb
    if not DISCORD_WEBHOOK_URL:
        print(f"[health_check] DISCORD_PIPELINE_WEBHOOK not set — crash alert not sent for: {step}: {exc}")
        return False

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    exc_type = type(exc).__name__

    body = f"💥 **Pipeline crash** — `{step}`\n"
    body += f"**Time:** {timestamp}\n"
    body += f"**Exception:** `{exc_type}: {str(exc)[:200]}`\n"
    if slug:
        body += f"**Article:** `{slug}`\n"
    if tb:
        # Keep last 3 frames of traceback, strip full paths
        lines = [l for l in tb.strip().splitlines() if l.strip()]
        snippet = "\n".join(lines[-8:])  # last 8 lines covers ~3 frames
        body += f"**Traceback:**\n```\n{snippet[:800]}\n```\n"

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
        print(f"[health_check] Discord crash notify failed: {e}")
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
