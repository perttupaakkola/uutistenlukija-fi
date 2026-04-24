#!/usr/bin/env python3
"""
cron_health_monitor.py — Detect silently failing scheduled jobs.

Reads data/cron_registry.json, checks mtime of marker files,
and reports stale jobs to Discord #operations.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import glob
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = ROOT / "data" / "cron_registry.json"
OPERATIONS_CHANNEL = "1482082645553713366"
ENV_FILES = [
    ROOT / ".env",
    ROOT / "pipeline" / ".env",
    Path("/workspace/.env"),
]

# Load environment variables for Discord token
for ENV_FILE in ENV_FILES:
    if not ENV_FILE.exists():
        continue
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("OPENCLAW_DISCORD_BOT_TOKEN", "")

def post_to_discord(content):
    if not DISCORD_BOT_TOKEN:
        print("[cron-health] Missing Discord bot token (DISCORD_BOT_TOKEN / OPENCLAW_DISCORD_BOT_TOKEN)", file=sys.stderr)
        return False
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{OPERATIONS_CHANNEL}/messages",
        payload,
        {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"[cron-health] Discord post failed: {e}", file=sys.stderr)
        return False

def main():
    dry_run = "--dry-run" in sys.argv[1:]

    if not REGISTRY_FILE.exists():
        print(f"Registry file not found: {REGISTRY_FILE}")
        return 1

    with open(REGISTRY_FILE, "r") as f:
        registry = json.load(f)

    now = time.time()
    stale_jobs = []
    missing_jobs = []
    ok_count = 0

    for job in registry:
        if job.get("enabled") is False:
            continue

        name = job["name"]
        interval_h = job["expected_interval_hours"]
        marker_rel = job.get("marker_file_path")
        marker_glob_rel = job.get("marker_glob_path")
        if marker_rel:
            marker_path = ROOT / marker_rel
        elif marker_glob_rel:
            matches = [Path(p) for p in glob.glob(str(ROOT / marker_glob_rel))]
            marker_path = max(matches, key=lambda p: p.stat().st_mtime) if matches else None
        else:
            marker_path = None

        if marker_path is None or not marker_path.exists():
            missing_jobs.append(name)
            continue

        mtime = marker_path.stat().st_mtime
        age_h = (now - mtime) / 3600

        # Flag if age > 1.5x interval
        if age_h > (interval_h * 1.5):
            stale_jobs.append({
                "name": name,
                "age_h": round(age_h, 2),
                "limit_h": round(interval_h * 1.5, 2)
            })
        else:
            ok_count += 1

    if not stale_jobs and not missing_jobs:
        print(f"All {ok_count} jobs healthy.")
        return 0

    # Build report
    report = "⏰ **Cron Health Report**\n"
    if stale_jobs:
        report += "\n⚠️ **Stale Jobs:**\n"
        for job in stale_jobs:
            report += f"- `{job['name']}`: {job['age_h']}h old (limit {job['limit_h']}h)\n"
    
    if missing_jobs:
        report += "\n🚫 **Missing Marker Files:**\n"
        for name in missing_jobs:
            report += f"- `{name}`\n"

    report += f"\nTotal healthy: {ok_count}"
    
    print(report)
    if not dry_run:
        post_to_discord(report)
    return 0

if __name__ == "__main__":
    sys.exit(main())
