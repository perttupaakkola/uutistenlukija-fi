#!/usr/bin/env python3
"""daily_traffic_card.py — Post yesterday's GA4 traffic summary to Discord #metrics.

Posts: pageviews, sessions, new users, avg session duration, bounce rate,
compared to 7-day rolling average. Alerts if sessions drop >40%.

Usage:
    python3 scripts/daily_traffic_card.py [--dry-run]

Cron (daily 07:00 UTC):
    0 7 * * * cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && python3 scripts/daily_traffic_card.py >> pipeline/logs/daily-traffic-card.log 2>&1
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
# Try multiple candidate paths (same pattern as weekly-metrics-digest.py)
_SECRETS_CANDIDATES = [
    PROJECT_DIR / ".secrets" / "analytics-tokens.json",
    PROJECT_DIR.parent / ".secrets" / "analytics-tokens.json",
    Path.home() / ".openclaw" / "workspace" / "projects" / "uutistenlukija" / ".secrets" / "analytics-tokens.json",
]
ANALYTICS_TOKENS = next((p for p in _SECRETS_CANDIDATES if p.exists()), _SECRETS_CANDIDATES[0])
ENV_FILE = PROJECT_DIR / "pipeline" / ".env"
GA4_PROPERTY = "529369568"
METRICS_CHANNEL = "1482720741790060554"  # #metrics

def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()


def get_ga4_token() -> str:
    if not ANALYTICS_TOKENS.exists():
        raise FileNotFoundError(f"Analytics tokens not found. Tried: {[str(p) for p in _SECRETS_CANDIDATES]}")
    data = json.loads(ANALYTICS_TOKENS.read_text())
    token = data.get("access_token", "")
    # Try refresh if needed
    if not token:
        raise ValueError("No access_token in analytics-tokens.json — refresh token first")
    return token


def ga4_report(token: str, start: str, end: str, metrics: list[str], dimensions: list[str] | None = None) -> dict:
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:runReport"
    payload = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "metrics": [{"name": m} for m in metrics],
    }
    if dimensions:
        payload["dimensions"] = [{"name": d} for d in dimensions]
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GA4 API error {e.code}: {body[:300]}")


def extract_metric(report: dict, name: str) -> float:
    """Extract a single metric value from a GA4 report."""
    rows = report.get("rows", [])
    if not rows:
        return 0.0
    metric_headers = [h["name"] for h in report.get("metricHeaders", [])]
    if name not in metric_headers:
        return 0.0
    idx = metric_headers.index(name)
    try:
        return float(rows[0]["metricValues"][idx]["value"])
    except (IndexError, KeyError, ValueError):
        return 0.0


def post_to_discord(message: str, webhook: str):
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(webhook, data=payload,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.URLError as e:
        print(f"Discord post failed: {e}")
        return None


def fmt_duration(seconds: float) -> str:
    secs = int(seconds)
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}min {secs % 60}s"


def pct_change(current: float, baseline: float) -> str:
    if baseline == 0:
        return "N/A"
    change = (current - baseline) / baseline * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def main():
    dry_run = "--dry-run" in sys.argv
    webhook = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
    if not webhook and not dry_run:
        print("No DISCORD_PIPELINE_WEBHOOK — use --dry-run or set env var")
        sys.exit(1)

    today = datetime.now(timezone.utc)
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    week_start = (today - timedelta(days=8)).strftime("%Y-%m-%d")
    week_end = (today - timedelta(days=2)).strftime("%Y-%m-%d")

    print(f"Fetching GA4 data for {yesterday} (7-day baseline: {week_start}–{week_end})...")

    try:
        token = get_ga4_token()
    except (FileNotFoundError, ValueError) as e:
        print(f"Token error: {e}")
        sys.exit(1)

    metrics = ["screenPageViews", "sessions", "newUsers", "averageSessionDuration", "bounceRate"]

    try:
        yesterday_report = ga4_report(token, yesterday, yesterday, metrics)
        baseline_report = ga4_report(token, week_start, week_end, metrics)
    except RuntimeError as e:
        print(f"GA4 error: {e}")
        sys.exit(1)

    # Yesterday stats
    pageviews = extract_metric(yesterday_report, "screenPageViews")
    sessions = extract_metric(yesterday_report, "sessions")
    new_users = extract_metric(yesterday_report, "newUsers")
    avg_duration = extract_metric(yesterday_report, "averageSessionDuration")
    bounce_rate = extract_metric(yesterday_report, "bounceRate")

    # 7-day average (total / 7)
    b_pageviews = extract_metric(baseline_report, "screenPageViews") / 7
    b_sessions = extract_metric(baseline_report, "sessions") / 7
    b_new_users = extract_metric(baseline_report, "newUsers") / 7
    b_duration = extract_metric(baseline_report, "averageSessionDuration")
    b_bounce = extract_metric(baseline_report, "bounceRate")

    # Alert check
    alert = ""
    if b_sessions > 0 and sessions < b_sessions * 0.6:
        alert = f"\n⚠️ **Varoitus:** Sessiot {sessions:.0f} on yli 40% alle 7pv keskiarvon ({b_sessions:.0f})!"

    date_fi = datetime.strptime(yesterday, "%Y-%m-%d").strftime("%-d.%-m.%Y")

    msg = f"""📊 **Päivittäinen liikennekooste — {date_fi}**

📄 Sivulataukset: **{pageviews:.0f}** ({pct_change(pageviews, b_pageviews)} vs 7pv ka)
👥 Sessiot: **{sessions:.0f}** ({pct_change(sessions, b_sessions)} vs 7pv ka)
🆕 Uudet käyttäjät: **{new_users:.0f}** ({pct_change(new_users, b_new_users)} vs 7pv ka)
⏱️ Keskim. istunto: **{fmt_duration(avg_duration)}** (7pv ka: {fmt_duration(b_duration)})
↩️ Poistumisprosentti: **{bounce_rate:.1f}%** (7pv ka: {b_bounce:.1f}%){alert}"""

    print(msg)

    if dry_run:
        print("\n[DRY RUN — not posted]")
    else:
        status = post_to_discord(msg, webhook)
        print(f"Discord status: {status}")


if __name__ == "__main__":
    main()
