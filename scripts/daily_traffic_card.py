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
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
# Try multiple candidate paths (same pattern as weekly-metrics-digest.py)
_SECRETS_CANDIDATES = [
    Path.home() / ".openclaw" / "workspace" / ".secrets" / "analytics-tokens.json",
    Path("/workspace/.secrets/analytics-tokens.json"),
    PROJECT_DIR / ".secrets" / "analytics-tokens.json",
    PROJECT_DIR.parent / ".secrets" / "analytics-tokens.json",
    Path.home() / ".openclaw" / "workspace" / "projects" / "uutistenlukija" / ".secrets" / "analytics-tokens.json",
]
ANALYTICS_TOKENS = next((p for p in _SECRETS_CANDIDATES if p.exists()), _SECRETS_CANDIDATES[0])
SENTINEL_SCRIPT = PROJECT_DIR / "scripts" / "analytics_oauth_sentinel.py"
ENV_FILES = [
    PROJECT_DIR / ".env",
    PROJECT_DIR / "pipeline" / ".env",
    Path("/workspace/.env"),
]
GA4_PROPERTY = "529369568"
METRICS_CHANNEL = "1482720741790060554"  # #metrics
DISCORD_HTTP_USER_AGENT = "Mozilla/5.0"

def load_env():
    for env_file in ENV_FILES:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()


def get_ga4_token() -> str:
    if not ANALYTICS_TOKENS.exists():
        raise FileNotFoundError(f"Analytics tokens not found. Tried: {[str(p) for p in _SECRETS_CANDIDATES]}")
    data = json.loads(ANALYTICS_TOKENS.read_text())
    refreshed = refresh_ga4_token(data)
    if refreshed:
        return refreshed
    token = data.get("access_token", "")
    if not token:
        raise ValueError("No access_token in analytics-tokens.json — refresh token first")
    return token


def refresh_ga4_token(data: dict) -> str | None:
    refresh_token = data.get("refresh_token")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    if not (refresh_token and client_id and client_secret):
        return None

    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            response = json.loads(resp.read())
        data["access_token"] = response["access_token"]
        ANALYTICS_TOKENS.write_text(json.dumps(data, indent=2) + "\n")
        print("Refreshed GA4 access token")
        return data["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"GA4 token refresh failed {e.code}: {body[:300]}")
        record_oauth_sentinel()
        return None
    except (OSError, KeyError, json.JSONDecodeError, urllib.error.URLError) as e:
        print(f"GA4 token refresh failed: {e}")
        return None


def record_oauth_sentinel() -> None:
    if not SENTINEL_SCRIPT.exists():
        return
    subprocess.run(
        [
            "python3",
            str(SENTINEL_SCRIPT),
            "--service",
            "ga4",
            "--source-command",
            "scripts/run_with_project_env.sh python3 scripts/daily_traffic_card.py --dry-run",
            "--source-log",
            "pipeline/logs/daily-traffic-card.log",
        ],
        check=False,
    )


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
            "User-Agent": "Hermes-Uutistenlukija/1.0",
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
                                  headers={"Content-Type": "application/json", "User-Agent": DISCORD_HTTP_USER_AGENT}, method="POST")
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


def error_card(yesterday: str, detail: str) -> str:
    date_fi = datetime.strptime(yesterday, "%Y-%m-%d").strftime("%-d.%-m.%Y")
    return f"""⚠️ **Päivittäinen liikennekooste — {date_fi}**

GA4-dataa ei voitu hakea, joten liikennelukuja ei julkaistu.
Syy: {detail}

Korjaus: GA4 OAuth pitää valtuuttaa uudelleen. Cron ja Discord-postauspolku toimivat, mutta token on vanhentunut tai peruttu."""


def emit_message(msg: str, webhook: str, dry_run: bool) -> None:
    print(msg)
    if dry_run:
        print("\n[DRY RUN — not posted]")
        return
    status = post_to_discord(msg, webhook)
    print(f"Discord status: {status}")


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
        emit_message(error_card(yesterday, str(e)), webhook, dry_run)
        sys.exit(1)

    metrics = ["screenPageViews", "sessions", "newUsers", "averageSessionDuration", "bounceRate"]

    try:
        yesterday_report = ga4_report(token, yesterday, yesterday, metrics)
        baseline_report = ga4_report(token, week_start, week_end, metrics)
    except RuntimeError as e:
        print(f"GA4 error: {e}")
        emit_message(error_card(yesterday, "GA4 OAuth2 authentication failed"), webhook, dry_run)
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

    emit_message(msg, webhook, dry_run)


if __name__ == "__main__":
    main()
