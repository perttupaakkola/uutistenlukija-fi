#!/usr/bin/env python3
"""
cron_health_monitor.py — Detect silently failing scheduled jobs.

Reads data/cron_registry.json, checks mtime of marker files,
and reports stale jobs to Discord #operations.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import glob
import re
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
DISCORD_WEBHOOK_URL = (
    os.environ.get("DISCORD_OPERATIONS_WEBHOOK")
    or os.environ.get("DISCORD_PIPELINE_WEBHOOK")
    or os.environ.get("DISCORD_WEBHOOK_OPS")
    or ""
)
DISCORD_HTTP_USER_AGENT = "Hermes-Uutistenlukija/1.0"
UNRESOLVED_ENV_PLACEHOLDER_RE = re.compile(r"\$\{[^}]+\}")

def configured_value(value):
    normalized = str(value or "").strip()
    if not normalized or UNRESOLVED_ENV_PLACEHOLDER_RE.search(normalized):
        return ""
    return normalized

def post_to_discord(content):
    payload = json.dumps({"content": content}).encode()
    webhook_url = configured_value(DISCORD_WEBHOOK_URL)
    bot_token = configured_value(DISCORD_BOT_TOKEN)
    if webhook_url:
        req = urllib.request.Request(
            webhook_url,
            payload,
            {
                "Content-Type": "application/json",
                "User-Agent": DISCORD_HTTP_USER_AGENT,
            },
            method="POST",
        )
    elif bot_token:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{OPERATIONS_CHANNEL}/messages",
            payload,
            {
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json",
                "User-Agent": DISCORD_HTTP_USER_AGENT,
            },
            method="POST",
        )
    else:
        print("[cron-health] Missing Discord webhook and bot token", file=sys.stderr)
        return False
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"[cron-health] Discord post failed: {e}", file=sys.stderr)
        return False

def nonempty_lines(path):
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    return [line for line in lines if line.strip()]

def latest_nonempty_line(path):
    lines = nonempty_lines(path)
    return lines[-1] if lines else ""

def pattern_matches(pattern, text):
    return re.search(pattern, text) is not None

def latest_marker_context(path, required_pattern):
    """Return the latest required marker line plus later lines for crash checks."""
    lines = nonempty_lines(path)
    if not required_pattern:
        return (lines[-1] if lines else "", [])
    for index in range(len(lines) - 1, -1, -1):
        if pattern_matches(required_pattern, lines[index]):
            return lines[index], lines[index + 1:]
    return (lines[-1] if lines else "", [])

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check registered cron markers and report unhealthy jobs."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the health report without posting to Discord.",
    )
    return parser.parse_args(argv)

def main(argv=None):
    args = parse_args(argv)

    if not REGISTRY_FILE.exists():
        print(f"Registry file not found: {REGISTRY_FILE}")
        return 1

    with open(REGISTRY_FILE, "r") as f:
        registry = json.load(f)

    now = time.time()
    stale_jobs = []
    missing_jobs = []
    failing_jobs = []
    deferred_jobs = []
    ok_count = 0
    now_utc_hour = datetime.now(timezone.utc).hour

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
            grace_until = job.get("missing_marker_not_due_before_utc_hour")
            if isinstance(grace_until, int) and now_utc_hour < grace_until:
                deferred_jobs.append(name)
                ok_count += 1
                continue
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
            required_latest = job.get("latest_line_required_pattern")
            latest_line, lines_after_marker = latest_marker_context(marker_path, required_latest)
            forbidden_latest = job.get("latest_line_forbidden_patterns", [])
            failure_reason = ""
            if required_latest and not pattern_matches(required_latest, latest_line):
                failure_reason = f"latest marker line did not match /{required_latest}/"
            for pattern in forbidden_latest:
                lines_to_check = [latest_line, *lines_after_marker]
                if any(pattern_matches(pattern, line) for line in lines_to_check):
                    failure_reason = f"latest marker line matched forbidden /{pattern}/"
                    break

            if failure_reason:
                failing_jobs.append({
                    "name": name,
                    "reason": failure_reason,
                    "latest_line": latest_line[-160:] if latest_line else "<empty>",
                })
            else:
                ok_count += 1

    if not stale_jobs and not missing_jobs and not failing_jobs:
        suffix = ""
        if deferred_jobs:
            suffix = f" ({len(deferred_jobs)} missing marker(s) not due yet: {', '.join(deferred_jobs)})"
        print(f"All {ok_count} jobs healthy{suffix}.")
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

    if failing_jobs:
        report += "\n❌ **Failing Jobs:**\n"
        for job in failing_jobs:
            report += f"- `{job['name']}`: {job['reason']}; latest `{job['latest_line']}`\n"

    report += f"\nTotal healthy: {ok_count}"
    
    print(report)
    if not args.dry_run:
        post_to_discord(report)
    return 1

if __name__ == "__main__":
    sys.exit(main())
