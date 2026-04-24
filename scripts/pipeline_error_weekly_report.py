#!/usr/bin/env python3
"""
pipeline_error_weekly_report.py — Weekly pipeline error summary for #operations

Reads pipeline/logs/pipeline_errors.json (written by pipeline_error_tracker.py),
computes 7-day stats, and posts a Discord summary to #operations via webhook.

Run Mondays 09:05 UTC via cron.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
ERRORS_FILE = PROJECT_DIR / "pipeline" / "logs" / "pipeline_errors.json"
ENV_FILES   = [
    PROJECT_DIR / ".env",
    PROJECT_DIR / "pipeline" / ".env",
    Path("/workspace/.env"),
]

OPERATIONS_WEBHOOK_ENV = "DISCORD_OPERATIONS_WEBHOOK"
WINDOW_DAYS = 7


def load_env(paths) -> dict[str, str]:
    env: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_errors() -> list[dict]:
    if not ERRORS_FILE.exists():
        return []
    try:
        with ERRORS_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def post_to_discord(webhook_url: str, message: str) -> bool:
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"[weekly_report] Discord webhook error: {e.code} {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[weekly_report] Discord webhook error: {e}", file=sys.stderr)
        return False


def format_report(window: list[dict], week_start: str, week_end: str) -> str:
    if not window:
        return (
            f"⚙️ **Pipeline virheraportti** — {week_start} → {week_end}\n"
            "_Ei dataa saatavilla tältä ajanjaksolta._"
        )

    total_runs   = sum(d.get("runs", 0) for d in window)
    total_ok     = sum(d.get("ok_runs", 0) for d in window)
    total_skip   = sum(d.get("skip_runs", 0) for d in window)
    total_err    = sum(d.get("error_runs", 0) for d in window)
    total_pub    = sum(d.get("published", 0) for d in window)
    error_rate   = total_err / total_runs if total_runs else 0

    # Aggregate error categories
    cat_totals: dict[str, int] = defaultdict(int)
    for d in window:
        for cat, count in d.get("error_categories", {}).items():
            cat_totals[cat] += count

    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:3]

    # Status emoji
    if error_rate < 0.05:
        status = "✅"
    elif error_rate < 0.15:
        status = "⚠️"
    else:
        status = "🔴"

    lines = [
        f"⚙️ **Pipeline-virheraportti** — {week_start} → {week_end}",
        "",
        f"{'Ajoja yhteensä:':<22} **{total_runs}**",
        f"{'Onnistuneet (julkaisua):':<22} **{total_ok}** ({total_pub} artikkelia julkaistu)",
        f"{'Ohitetut (ei uutta):':<22} **{total_skip}**",
        f"{'Virheet:':<22} **{total_err}** ({error_rate:.0%}) {status}",
    ]

    if top_cats:
        lines.append("")
        lines.append("**Top virhekategoriat:**")
        cat_labels = {
            "no_articles_fetched": "Ei artikkeleita haettu",
            "rewrite_failed":      "Kirjoitus epäonnistui",
            "quality_gate":        "Laadunvalvonta hylkäsi",
            "dedup_rejected":      "Duplikaatti hylätty",
            "publish_blocked":     "Julkaisu estyi (muu)",
            "timeout_suspected":   "Timeout epäilty",
        }
        for i, (cat, count) in enumerate(top_cats, 1):
            label = cat_labels.get(cat, cat)
            lines.append(f"{i}. {label} — **{count}** kertaa")

    # Per-day breakdown (compact)
    lines.append("")
    lines.append("**Päivittäin:**")
    for d in window:
        runs = d.get("runs", 0)
        errs = d.get("error_runs", 0)
        pub  = d.get("published", 0)
        rate = d.get("error_rate", 0)
        flag = "🔴" if rate >= 0.15 else ("⚠️" if rate >= 0.05 else "✅")
        lines.append(f"`{d['date']}` — {runs} ajoa, {pub} julkaistu, {errs} virh. {flag}")

    return "\n".join(lines)


def main() -> int:
    env = load_env(ENV_FILES)
    # Also check process environment
    webhook_url = os.environ.get(OPERATIONS_WEBHOOK_ENV) or env.get(OPERATIONS_WEBHOOK_ENV, "")

    now = datetime.now(timezone.utc)
    week_end   = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")

    errors = load_errors()
    window = [e for e in errors if week_start <= e.get("date", "") <= week_end]

    report = format_report(window, week_start, week_end)
    print(report)

    if not webhook_url:
        print(f"\n[weekly_report] {OPERATIONS_WEBHOOK_ENV} not set — printed to stdout only.")
        return 0

    ok = post_to_discord(webhook_url, report)
    if ok:
        print(f"\n[weekly_report] Posted to Discord #operations ✓")
    else:
        print(f"\n[weekly_report] Discord post failed", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
