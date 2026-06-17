#!/usr/bin/env python3
"""
weekly-metrics-digest.py — Weekly GA4 metrics summary for uutistenlukija.fi

Queries GA4 Data API for the past 7 days and posts a formatted digest to
Discord #metrics channel.

Usage:
    python3 scripts/weekly-metrics-digest.py [--dry-run]

Cron (Mondays 07:00 UTC = 09:00 Helsinki):
    0 7 * * 1 python3 /workspace/scripts/weekly-metrics-digest.py >> /workspace/logs/weekly-metrics-digest.log 2>&1

GA4 property: 529369568
Token file: prefer ~/.openclaw/workspace/.secrets/analytics-tokens.json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from google_access_token import service_account_access_token

# ── Config ────────────────────────────────────────────────────────────────────
GA4_PROPERTY   = "529369568"
GA4_SECRETS_PATHS = [
    "/home/pertt/.openclaw/workspace/.secrets/analytics-tokens.json",
    "/workspace/.secrets/analytics-tokens.json",
    "/home/pertt/.openclaw/workspace/projects/uutistenlukija/.secrets/analytics-tokens.json",
    "/workspace/projects/uutistenlukija/.secrets/analytics-tokens.json",
    "/home/pertt/.openclaw/workspace-max/projects/uutistenlukija/.secrets/analytics-tokens.json",
]
GA4_SECRETS = next((p for p in GA4_SECRETS_PATHS if os.path.exists(p)),
                   GA4_SECRETS_PATHS[0])
METRICS_CHANNEL = "1482720741790060554"  # #metrics

# Fallback: use DISCORD_METRICS_WEBHOOK env or bot token
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_METRICS_WEBHOOK = os.environ.get("DISCORD_METRICS_WEBHOOK", "")


# ── Token refresh ─────────────────────────────────────────────────────────────

def refresh_google_token(secrets_file: str) -> str | None:
    """Refresh GA4 OAuth2 token, or use service account when configured."""
    try:
        service_account_token = service_account_access_token(["https://www.googleapis.com/auth/analytics.readonly"])
    except Exception as e:
        print(f"[weekly-metrics] Service account token failed: {e}", file=sys.stderr)
        service_account_token = None
    if service_account_token:
        token, _path, email = service_account_token
        print(f"[weekly-metrics] Using service account: {email}")
        return token

    if not os.path.exists(secrets_file):
        print(f"[weekly-metrics] Token file not found: {secrets_file}", file=sys.stderr)
        return None
    try:
        with open(secrets_file) as f:
            creds = json.load(f)
        data = urllib.parse.urlencode({
            "client_id":     creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type":    "refresh_token",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data)
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        creds["access_token"] = resp["access_token"]
        with open(secrets_file, "w") as f:
            json.dump(creds, f, indent=2)
        return creds["access_token"]
    except Exception as e:
        print(f"[weekly-metrics] Token refresh failed: {e}", file=sys.stderr)
        return None


# ── GA4 requests ──────────────────────────────────────────────────────────────

def ga4_request(token: str, endpoint: str, payload: dict) -> dict:
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:{endpoint}"
    req = urllib.request.Request(
        url,
        json.dumps(payload).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[weekly-metrics] GA4 HTTP {e.code}: {body}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[weekly-metrics] GA4 request failed: {e}", file=sys.stderr)
        return {}


def fetch_weekly_ga4(token: str) -> dict:
    """Fetch last 7 days of GA4 data. Returns parsed metrics dict."""
    today = datetime.now(timezone.utc)
    end_date   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    # ── Totals: last 7 days ───────────────────────────────────────────────────
    totals = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "averageSessionDuration"},
            {"name": "bounceRate"},
            {"name": "newUsers"},
        ],
    })

    # ── Previous 7 days for WoW comparison ────────────────────────────────────
    prev_end   = (today - timedelta(days=8)).strftime("%Y-%m-%d")
    prev_start = (today - timedelta(days=14)).strftime("%Y-%m-%d")

    prev_totals = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": prev_start, "endDate": prev_end}],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "sessions"},
            {"name": "totalUsers"},
        ],
    })

    # ── Top 5 articles by pageviews ───────────────────────────────────────────
    top_pages = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
        "metrics": [{"name": "screenPageViews"}, {"name": "totalUsers"}],
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 7,
        "dimensionFilter": {
            "filter": {
                "fieldName": "pagePath",
                "stringFilter": {"matchType": "BEGINS_WITH", "value": "/posts/"}
            }
        }
    })

    # ── Traffic sources ───────────────────────────────────────────────────────
    traffic_sources = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "sessionDefaultChannelGroup"}],
        "metrics": [{"name": "sessions"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 5,
    })

    def _row(resp, idx=0) -> list[str] | None:
        rows = resp.get("rows", [])
        if idx < len(rows):
            return [v["value"] for v in rows[idx]["metricValues"]]
        return None

    def _int(v: str | None) -> int:
        try: return int(v or "0")
        except: return 0

    def _float(v: str | None) -> float:
        try: return float(v or "0")
        except: return 0.0

    curr = _row(totals) or ["0"] * 6
    prev = _row(prev_totals) or ["0"] * 3

    def wow(curr_val: int, prev_val: int) -> str:
        if prev_val == 0:
            return "—"
        delta = curr_val - prev_val
        pct = delta / prev_val * 100
        sign = "+" if delta >= 0 else ""
        icon = "📈" if pct > 5 else ("📉" if pct < -5 else "➡️")
        return f"{icon} {sign}{pct:.0f}%"

    pageviews   = _int(curr[0])
    sessions    = _int(curr[1])
    users       = _int(curr[2])
    avg_dur_sec = _float(curr[3])
    bounce_rate = _float(curr[4])
    new_users   = _int(curr[5])

    prev_pv   = _int(prev[0])
    prev_sess = _int(prev[1])
    prev_usr  = _int(prev[2])

    avg_dur_str = f"{int(avg_dur_sec // 60)}m {int(avg_dur_sec % 60)}s"

    # Top pages
    articles = []
    for row in top_pages.get("rows", [])[:5]:
        dims = [d["value"] for d in row["dimensionValues"]]
        mets = [m["value"] for m in row["metricValues"]]
        path  = dims[0] if dims else "?"
        title = dims[1] if len(dims) > 1 else path
        views = _int(mets[0])
        uusers = _int(mets[1])
        # Shorten title
        title = title.replace(" | Uutistenlukija", "").replace(" | uutistenlukija.fi", "").strip()
        if len(title) > 55:
            title = title[:52] + "…"
        articles.append({"path": path, "title": title, "views": views, "users": uusers})

    # Traffic sources
    sources = []
    for row in traffic_sources.get("rows", [])[:4]:
        channel = row["dimensionValues"][0]["value"]
        sess = _int(row["metricValues"][0]["value"])
        sources.append({"channel": channel, "sessions": sess})

    return {
        "week_start": start_date,
        "week_end":   end_date,
        "pageviews":  pageviews,
        "sessions":   sessions,
        "users":      users,
        "new_users":  new_users,
        "avg_duration": avg_dur_str,
        "bounce_rate":  round(bounce_rate * 100, 1),
        "wow_pv":     wow(pageviews, prev_pv),
        "wow_sess":   wow(sessions, prev_sess),
        "wow_users":  wow(users, prev_usr),
        "top_articles": articles,
        "traffic_sources": sources,
    }


# ── Format digest ─────────────────────────────────────────────────────────────

def format_digest(d: dict) -> str:
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    lines = [
        f"📊 **Viikkoraportti — {d['week_start']} → {d['week_end']}** *(generoitu {now_str})*",
        "",
        "**Yleiskatsaus (7 pv):**",
        f"  👁️  Sivulataukset:  **{d['pageviews']:,}**  {d['wow_pv']}",
        f"  🧑  Käyttäjät:      **{d['users']:,}**  {d['wow_users']}",
        f"  🔗  Istunnot:       **{d['sessions']:,}**  {d['wow_sess']}",
        f"  🆕  Uudet käyttäjät: {d['new_users']:,}",
        f"  ⏱️  Keskim. kesto:   {d['avg_duration']}",
        f"  🏃  Välitön poistuma: {d['bounce_rate']}%",
    ]

    if d["top_articles"]:
        lines += ["", "**🏆 Top 5 artikkelia:**"]
        for i, art in enumerate(d["top_articles"], 1):
            lines.append(f"  {i}. {art['title']}  —  **{art['views']:,}** latausta")

    if d["traffic_sources"]:
        lines += ["", "**📡 Liikenteen lähteet:**"]
        for src in d["traffic_sources"]:
            lines.append(f"  • {src['channel']}: {src['sessions']:,} istuntoa")

    return "\n".join(lines)


# ── Discord post ──────────────────────────────────────────────────────────────

def post_to_discord(message: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(message)
        return True

    # Try webhook first
    if DISCORD_METRICS_WEBHOOK:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            DISCORD_METRICS_WEBHOOK, payload,
            {"Content-Type": "application/json", "User-Agent": "Hermes-Uutistenlukija/1.0"}, method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            print("[weekly-metrics] Posted via webhook")
            return True
        except Exception as e:
            print(f"[weekly-metrics] Webhook failed: {e}", file=sys.stderr)

    # Fall back to Bot token
    if DISCORD_BOT_TOKEN:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{METRICS_CHANNEL}/messages",
            payload,
            {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            print("[weekly-metrics] Posted via bot token")
            return True
        except Exception as e:
            print(f"[weekly-metrics] Bot post failed: {e}", file=sys.stderr)

    print("[weekly-metrics] No Discord credentials configured", file=sys.stderr)
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print digest to stdout without posting")
    parser.add_argument("--secrets", default=GA4_SECRETS,
                        help="Path to GA4 secrets JSON")
    args = parser.parse_args()

    print(f"[weekly-metrics] Starting at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")

    # Refresh token
    token = refresh_google_token(args.secrets)
    if not token:
        if args.dry_run:
            print("[weekly-metrics] No GA4 token — printing mock data for dry-run")
            mock = {
                "week_start": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"),
                "week_end":   (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
                "pageviews": 0, "sessions": 0, "users": 0, "new_users": 0,
                "avg_duration": "0m 0s", "bounce_rate": 0.0,
                "wow_pv": "—", "wow_sess": "—", "wow_users": "—",
                "top_articles": [], "traffic_sources": [],
            }
            print(format_digest(mock))
            return 0
        print("[weekly-metrics] Cannot run without GA4 token", file=sys.stderr)
        return 1

    # Fetch data
    print("[weekly-metrics] Fetching GA4 data...")
    try:
        data = fetch_weekly_ga4(token)
    except Exception as e:
        print(f"[weekly-metrics] Data fetch failed: {e}", file=sys.stderr)
        return 1

    print(f"[weekly-metrics] Got data: {data['pageviews']} pageviews, "
          f"{data['sessions']} sessions, {data['users']} users")

    # Format and post
    digest = format_digest(data)
    ok = post_to_discord(digest, dry_run=args.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
