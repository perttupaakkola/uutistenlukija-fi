#!/usr/bin/env python3
"""retention_trend.py — Post weekly new vs. returning users report to Discord #metrics.

Fetches from GA4:
- New users vs. returning users for the past full week (Mon–Sun)
- Returning active share (not cohort retention) and week-over-week trend

Posts to #metrics every Monday at 08:30 UTC.

Usage:
    python3 scripts/retention_trend.py [--dry-run]

Cron (every Monday 08:30 UTC):
    30 8 * * 1 cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && python3 scripts/retention_trend.py >> pipeline/logs/retention-trend.log 2>&1
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
_SECRETS_CANDIDATES = [
    Path.home() / ".openclaw" / "workspace" / ".secrets" / "analytics-tokens.json",
    Path("/workspace/.secrets/analytics-tokens.json"),
    PROJECT_DIR / ".secrets" / "analytics-tokens.json",
    PROJECT_DIR.parent / ".secrets" / "analytics-tokens.json",
    Path.home() / ".openclaw" / "workspace" / "projects" / "uutistenlukija" / ".secrets" / "analytics-tokens.json",
]
ANALYTICS_TOKENS = next((p for p in _SECRETS_CANDIDATES if p.exists()), _SECRETS_CANDIDATES[0])
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


def refresh_ga4_token() -> str | None:
    """Attempt to refresh the OAuth token using refresh_token + client credentials."""
    if not ANALYTICS_TOKENS.exists():
        return None
    try:
        import urllib.parse
        creds = json.loads(ANALYTICS_TOKENS.read_text())
        if not creds.get("refresh_token"):
            return None
        data = urllib.parse.urlencode({
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=data, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            new_token = json.loads(r.read()).get("access_token")
        if new_token:
            creds["access_token"] = new_token
            ANALYTICS_TOKENS.write_text(json.dumps(creds, indent=2, ensure_ascii=False))
            return new_token
    except Exception as e:
        print(f"Token refresh failed: {e}", file=sys.stderr)
    return None


def get_ga4_token() -> str:
    if not ANALYTICS_TOKENS.exists():
        raise FileNotFoundError(
            f"Analytics tokens not found. Tried: {[str(p) for p in _SECRETS_CANDIDATES]}"
        )
    data = json.loads(ANALYTICS_TOKENS.read_text())
    token = data.get("access_token", "")
    if not token:
        raise ValueError("No access_token in analytics-tokens.json — refresh token first")
    return token


def get_valid_token() -> str:
    """Get a valid GA4 token, auto-refreshing if the current one is expired."""
    token = get_ga4_token()
    # Quick check: try a lightweight token info call
    try:
        req = urllib.request.Request(
            f"https://oauth2.googleapis.com/tokeninfo?access_token={token}", method="GET"
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
        return token
    except urllib.error.HTTPError:
        # Token is invalid/expired — try refresh
        print("Access token expired, refreshing...", file=sys.stderr)
        new_token = refresh_ga4_token()
        if new_token:
            return new_token
        # Return original and let GA4 call fail with a clear error
        return token


def ga4_report(token: str, start: str, end: str, metrics: list, dimensions: list = None) -> dict:
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:runReport"
    payload = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "metrics": [{"name": m} for m in metrics],
    }
    if dimensions:
        payload["dimensions"] = [{"name": d} for d in dimensions]
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GA4 API error {e.code}: {body[:300]}")


def extract_metric(report: dict, name: str) -> float:
    """Read a required finite nonnegative metric; malformed data is not zero."""
    import math
    try:
        headers = [h["name"] for h in report["metricHeaders"]]
        value = report["rows"][0]["metricValues"][headers.index(name)]["value"]
        if isinstance(value, bool):
            raise ValueError("boolean metric")
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError("invalid metric")
        return result
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("missing or invalid " + name) from exc


def extract_new_returning(report: dict, totals: dict | None = None,
                          expected_metrics: list | None = None) -> tuple[float, float, float, float | None]:
    """Validated new/returning active users, sessions and independent denominator.

    The weekly caller supplies the exact requested metrics. Both queries use
    that week's same dates; dimension user counts must never be summed into
    the denominator. This is returning active share, not cohort retention.
    """
    def validate(response, dimensions, required_metrics, requested_metrics=None):
        try:
            headers = [h["name"] for h in response["metricHeaders"]]
            if (not headers or len(set(headers)) != len(headers)
                    or not set(required_metrics).issubset(headers)
                    or (requested_metrics is not None and headers != requested_metrics)
                    or [h["name"] for h in response.get("dimensionHeaders", [])] != dimensions):
                raise ValueError("response schema mismatch")
            rows = response["rows"]
            if (not isinstance(rows, list) or not rows
                    or type(response["rowCount"]) is not int
                    or response["rowCount"] != len(rows)
                    or (not dimensions and len(rows) != 1)):
                raise ValueError("empty or incomplete rows")
            metadata = response.get("metadata", {})
            if not isinstance(metadata, dict) or any(metadata.get(key) for key in (
                    "subjectToThresholding", "samplingMetadatas", "dataLossFromOtherRow")):
                raise ValueError("limited provider data")
            seen = set()
            for row in rows:
                if (len(row["metricValues"]) != len(headers)
                        or len(row.get("dimensionValues", [])) != len(dimensions)):
                    raise ValueError("row schema mismatch")
                if dimensions:
                    cohort = row["dimensionValues"][0]["value"]
                    if cohort not in ("new", "returning", "(not set)") or cohort in seen:
                        raise ValueError("invalid or duplicate newVsReturning row")
                    seen.add(cohort)
                for name in headers:
                    extract_metric({"metricHeaders": response["metricHeaders"], "rows": [row]}, name)
            return rows
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError("invalid weekly GA4 response: " + str(exc)) from exc

    rows = validate(report, ["newVsReturning"], ["activeUsers", "sessions"], expected_metrics)
    new_users = returning = sessions = 0.0
    for row in rows:
        values = {"metricHeaders": report["metricHeaders"], "rows": [row]}
        cohort = row["dimensionValues"][0]["value"]
        users = extract_metric(values, "activeUsers")
        sessions += extract_metric(values, "sessions")
        if cohort == "new":
            new_users = users
        elif cohort == "returning":
            returning = users
    total = None
    if totals is not None:
        validate(totals, [], ["activeUsers"], ["activeUsers"] if expected_metrics is not None else None)
        total = extract_metric(totals, "activeUsers")
        if total <= 0 or returning > total or new_users > total:
            raise ValueError("zero or inconsistent direct activeUsers denominator")
    return new_users, returning, sessions, total


def post_to_discord(message: str, webhook: str) -> int | None:
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": DISCORD_HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.URLError as e:
        print(f"Discord post failed: {e}")
        return None


def pct_change(current: float, baseline: float) -> str:
    if baseline == 0:
        return "N/A"
    change = (current - baseline) / baseline * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def week_number(date_str: str) -> int:
    return datetime.strptime(date_str, "%Y-%m-%d").isocalendar()[1]


def main():
    dry_run = "--dry-run" in sys.argv
    webhook = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")
    if not webhook and not dry_run:
        print("No DISCORD_PIPELINE_WEBHOOK — use --dry-run or set env var")
        sys.exit(1)

    today = datetime.now(timezone.utc)

    # Last full week: Mon–Sun
    # Today is Monday (cron day). Last full week = last Mon–Sun.
    days_since_monday = today.weekday()  # 0=Mon
    if days_since_monday == 0:
        # Running on Monday morning — report on last week (Mon-7 to Sun-1)
        week_end = today - timedelta(days=1)
        week_start = today - timedelta(days=7)
    else:
        # If run off-schedule, use the most recent full week
        week_end = today - timedelta(days=days_since_monday + 1)
        week_start = week_end - timedelta(days=6)

    # Previous week for comparison
    prev_week_end = week_start - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)

    ws = week_start.strftime("%Y-%m-%d")
    we = week_end.strftime("%Y-%m-%d")
    pws = prev_week_start.strftime("%Y-%m-%d")
    pwe = prev_week_end.strftime("%Y-%m-%d")
    wk_num = week_number(ws)

    print(f"Week: {ws} → {we} (vko {wk_num})")
    print(f"Prev: {pws} → {pwe}")

    try:
        token = get_valid_token()
    except (FileNotFoundError, ValueError) as e:
        print(f"Token error: {e}")
        sys.exit(1)

    metrics = ["activeUsers", "sessions", "totalUsers", "newUsers"]

    try:
        this_week = ga4_report(token, ws, we, metrics, dimensions=["newVsReturning"])
        prev_week = ga4_report(token, pws, pwe, metrics, dimensions=["newVsReturning"])
        this_totals = ga4_report(token, ws, we, ["activeUsers"])
        prev_totals = ga4_report(token, pws, pwe, ["activeUsers"])
    except RuntimeError as e:
        print(f"GA4 error: {e}")
        sys.exit(1)

    try:
        new_users, returning, sessions, total = extract_new_returning(this_week, this_totals, metrics)
        prev_new, prev_returning, _prev_sessions, prev_total = extract_new_returning(prev_week, prev_totals, metrics)
        if total is None or prev_total is None:
            raise ValueError("missing direct activeUsers response")
    except ValueError as exc:
        print(f"Returning active share unavailable: {exc}")
        return 1

    return_rate = returning / total * 100
    prev_return_rate = prev_returning / prev_total * 100
    rate_delta = return_rate - prev_return_rate
    rate_delta_str = f"+{rate_delta:.0f} pp" if rate_delta >= 0 else f"{rate_delta:.0f} pp"
    trend_emoji = "📈" if rate_delta >= 0 else "📉"

    msg = f"""📊 **Palaavien aktiivisten käyttäjien osuus vko {wk_num}** ({ws} – {we})

👤 Uudet: **{new_users:.0f}** ({pct_change(new_users, prev_new)} vko:sta)
🔄 Palaavat: **{returning:.0f}** ({pct_change(returning, prev_returning)} vko:sta)
📋 Sessiot: **{sessions:.0f}**
{trend_emoji} Palaavien osuus aktiivisista: **{return_rate:.0f} %** ({rate_delta_str} edellisestä viikosta, oli {prev_return_rate:.0f} %)
Tämä osuus ei ole hankintakohortin säilyvyysaste."""

    print(msg)

    if dry_run:
        print("\n[DRY RUN — not posted]")
    else:
        status = post_to_discord(msg, webhook)
        print(f"Discord status: {status}")


if __name__ == "__main__":
    sys.exit(main())
