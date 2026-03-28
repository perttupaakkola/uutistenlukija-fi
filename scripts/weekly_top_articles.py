#!/usr/bin/env python3
"""
weekly_top_articles.py — Top 5 articles of the week for uutistenlukija.fi

Fetches GA4 Data API (last 7 days) and posts the top 5 articles by pageviews
with avg session duration to Discord #metrics channel.

Usage:
    python3 scripts/weekly_top_articles.py [--dry-run]

Cron (Mondays 08:00 UTC = 10:00 Helsinki):
    0 8 * * 1 cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && \
        python3 scripts/weekly_top_articles.py \
        >> /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/logs/weekly-top-articles.log 2>&1

GA4 property: 529369568
Token file: /workspace/.secrets/analytics-tokens.json (or absolute path on host)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
GA4_PROPERTY = "529369568"
METRICS_CHANNEL = "1482720741790060554"  # #metrics

# Token file: workspace path works in sandbox, absolute path on host
GA4_SECRETS_PATHS = [
    "/workspace/.secrets/analytics-tokens.json",
    "/home/pertt/.openclaw/workspace/.secrets/analytics-tokens.json",
    "/home/pertt/.openclaw/workspace-max/projects/uutistenlukija/.secrets/analytics-tokens.json",
    "/home/pertt/.openclaw/workspace-alex/projects/uutistenlukija/.secrets/analytics-tokens.json",
]

DISCORD_METRICS_WEBHOOK = os.environ.get(
    "DISCORD_METRICS_WEBHOOK",
    "https://discord.com/api/webhooks/1487074961175875714/INXZeLxZpI4X7_0sOddAdHl_dkMVAjH6OewKfV2TvIOW44GoFMCgWslRoALcRNheXvdw"
)


# ── Token refresh ─────────────────────────────────────────────────────────────

def find_secrets_file() -> str | None:
    for path in GA4_SECRETS_PATHS:
        if os.path.exists(path):
            return path
    return None


def refresh_google_token(secrets_file: str) -> str | None:
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
        print(f"[top-articles] Token refresh failed: {e}", file=sys.stderr)
        return None


# ── GA4 ───────────────────────────────────────────────────────────────────────

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
        print(f"[top-articles] GA4 HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"[top-articles] GA4 request failed: {e}", file=sys.stderr)
        return {}


def fetch_top_articles(token: str) -> list[dict]:
    """Fetch top 5 articles by pageviews with avg session duration."""
    today = datetime.now(timezone.utc)
    end_date   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    # Top pages by pageviews, filtered to /posts/ paths
    resp = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "averageSessionDuration"},
        ],
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 10,
        "dimensionFilter": {
            "filter": {
                "fieldName": "pagePath",
                "stringFilter": {"matchType": "BEGINS_WITH", "value": "/posts/"}
            }
        }
    })

    articles = []
    for row in resp.get("rows", [])[:5]:
        dims = [d["value"] for d in row["dimensionValues"]]
        mets = [m["value"] for m in row["metricValues"]]
        path  = dims[0] if dims else "?"
        title = dims[1] if len(dims) > 1 else path
        views = int(mets[0]) if mets else 0
        avg_dur_sec = float(mets[1]) if len(mets) > 1 else 0.0

        # Clean title
        for suffix in [" | Uutistenlukija", " | uutistenlukija.fi", " – Uutistenlukija"]:
            title = title.replace(suffix, "")
        title = title.strip()
        if len(title) > 60:
            title = title[:57] + "…"

        avg_dur_str = f"{int(avg_dur_sec // 60)}m {int(avg_dur_sec % 60)}s"

        articles.append({
            "title": title,
            "path": path,
            "views": views,
            "avg_duration": avg_dur_str,
        })

    return articles


# ── Format & post ─────────────────────────────────────────────────────────────

def format_message(articles: list[dict], start_date: str, end_date: str) -> str:
    # Convert to Finnish day range (ma = Monday, su = Sunday)
    lines = [f"📊 **Viikon top 5 artikkelia** ({start_date} – {end_date})", ""]

    if not articles:
        lines.append("*Ei dataa saatavilla.*")
        return "\n".join(lines)

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, art in enumerate(articles):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(
            f"{medal} **{art['title']}**\n"
            f"   👁️ {art['views']:,} näyttöä  ·  ⏱️ {art['avg_duration']} keskim."
        )

    return "\n".join(lines)


def post_to_discord(message: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(message)
        return True

    if not DISCORD_METRICS_WEBHOOK:
        print("[top-articles] No Discord webhook configured", file=sys.stderr)
        return False

    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        DISCORD_METRICS_WEBHOOK, payload,
        {"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("[top-articles] Posted to #metrics via webhook")
        return True
    except Exception as e:
        print(f"[top-articles] Webhook post failed: {e}", file=sys.stderr)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Post weekly top articles to Discord #metrics")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout, don't post")
    parser.add_argument("--secrets", default=None, help="Path to GA4 secrets JSON")
    args = parser.parse_args()

    print(f"[top-articles] Starting at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")

    secrets_file = args.secrets or find_secrets_file()
    if not secrets_file:
        print("[top-articles] GA4 secrets file not found", file=sys.stderr)
        return 1

    token = refresh_google_token(secrets_file)
    if not token:
        print("[top-articles] Cannot run without GA4 token", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc)
    end_date   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    print("[top-articles] Fetching GA4 top articles...")
    articles = fetch_top_articles(token)
    print(f"[top-articles] Got {len(articles)} articles")

    message = format_message(articles, start_date, end_date)
    ok = post_to_discord(message, dry_run=args.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
