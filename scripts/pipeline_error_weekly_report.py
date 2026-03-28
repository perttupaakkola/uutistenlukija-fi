#!/usr/bin/env python3
"""pipeline_error_weekly_report.py — Weekly pipeline error summary to Discord.

Reads pipeline/logs/pipeline_errors.json and posts a 7-day summary to #operations.

Usage:
    python3 scripts/pipeline_error_weekly_report.py [--dry-run]
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import urllib.request
import urllib.error

PROJECT_DIR = Path(__file__).parent.parent
ERROR_DB = PROJECT_DIR / "pipeline" / "logs" / "pipeline_errors.json"
ENV_FILE = PROJECT_DIR / "pipeline" / ".env"

# Load .env
def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

load_env()


def post_to_discord(message: str, webhook_url: str):
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.URLError as e:
        print(f"Discord post failed: {e}")
        return None


def main():
    dry_run = "--dry-run" in sys.argv

    webhook = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
    if not webhook and not dry_run:
        print("No DISCORD_PIPELINE_WEBHOOK set — use --dry-run or set webhook")
        sys.exit(1)

    if not ERROR_DB.exists():
        print(f"No error DB at {ERROR_DB} — run pipeline_error_tracker.py first")
        sys.exit(0)

    db = json.loads(ERROR_DB.read_text())
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    week_records = [r for r in db if r.get("date", "") >= cutoff]

    if not week_records:
        print("No data for the last 7 days")
        sys.exit(0)

    total_runs = sum(r["runs"] for r in week_records)
    total_articles = sum(r["articles_deployed"] for r in week_records)
    total_errors = sum(r["total_errors"] for r in week_records)
    avg_error_rate = (total_errors / total_runs * 100) if total_runs > 0 else 0.0

    # Aggregate error categories
    all_cats: dict[str, int] = {}
    for r in week_records:
        for cat, count in r.get("error_categories", {}).items():
            all_cats[cat] = all_cats.get(cat, 0) + count

    top3 = sorted(all_cats.items(), key=lambda x: x[1], reverse=True)[:3]

    # Build message
    week_start = min(r["date"] for r in week_records)
    week_end = max(r["date"] for r in week_records)

    msg_lines = [
        f"**📊 Pipeline viikkoraportti ({week_start} – {week_end})**",
        "",
        f"🔄 Ajoja yhteensä: **{total_runs}**",
        f"📰 Artikkeleita julkaistu: **{total_articles}**",
        f"⚠️ Virheaste: **{avg_error_rate:.1f}%**",
    ]

    if top3:
        msg_lines.append("")
        msg_lines.append("**Top-3 virhekategoriat:**")
        for cat, count in top3:
            msg_lines.append(f"  • {cat}: {count} kpl")

    # Per-day summary
    msg_lines.append("")
    msg_lines.append("**Päiväkohtainen:**")
    for r in sorted(week_records, key=lambda x: x["date"]):
        status = "✅" if r["error_rate_pct"] < 10 else "⚠️"
        msg_lines.append(
            f"  {status} {r['date']}: {r['runs']} ajoa, {r['articles_deployed']} artikkelia, {r['error_rate_pct']}% virheaste"
        )

    message = "\n".join(msg_lines)
    print(message)

    if dry_run:
        print("\n[DRY RUN — not posted to Discord]")
    else:
        status = post_to_discord(message, webhook)
        if status == 204:
            print("Posted to Discord ✅")
        else:
            print(f"Discord returned status {status}")


if __name__ == "__main__":
    main()
