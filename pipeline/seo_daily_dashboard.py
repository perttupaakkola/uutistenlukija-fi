#!/usr/bin/env python3
"""
seo_daily_dashboard.py — Daily SEO report for uutistenlukija.fi

Pulls GA4 + Search Console data and posts a formatted digest to Discord #seo.
Run daily at 07:30 UTC via cron.

Usage:
    python3 seo_daily_dashboard.py [--dry-run] [--discord-channel <id>]
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
from google_access_token import service_account_access_token

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_DIR = os.path.join(SCRIPT_DIR, "..", "..", "secrets")
WORKSPACE_SECRETS_CANDIDATES = [
    "/home/pertt/.openclaw/workspace/.secrets",
    "/workspace/.secrets",
]
WORKSPACE_SECRETS = next(
    (path for path in WORKSPACE_SECRETS_CANDIDATES if os.path.isdir(path)),
    WORKSPACE_SECRETS_CANDIDATES[0],
)

GA4_SECRETS    = os.path.join(WORKSPACE_SECRETS, "analytics-tokens.json")
SC_SECRETS     = os.path.join(WORKSPACE_SECRETS, "search-console-tokens.json")

GA4_PROPERTY   = "529369568"
SC_PROPERTY    = "sc-domain:uutistenlukija.fi"
SEO_CHANNEL    = "1482511287912104130"   # #seo

LOG_DIR        = os.path.join(SCRIPT_DIR, "logs")
STATE_FILE     = os.path.join(LOG_DIR, "seo-dashboard-state.json")

# ── Token helpers ──────────────────────────────────────────────────────────────

def refresh_google_token(secrets_file: str, scope: str | None = None) -> str:
    """Refresh a Google OAuth2 access token or mint one from a service account."""
    scopes = [scope] if scope else ["https://www.googleapis.com/auth/analytics.readonly"]
    try:
        service_account_token = service_account_access_token(scopes)
    except Exception as e:
        print(f"[google-auth] service account token failed: {e}", file=sys.stderr)
        service_account_token = None
    if service_account_token:
        token, _path, email = service_account_token
        print(f"[google-auth] using service account: {email}")
        return token

    with open(secrets_file) as f:
        creds = json.load(f)
    data = urllib.parse.urlencode({
        "client_id":     creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data)
    resp = json.loads(urllib.request.urlopen(req).read())
    creds["access_token"] = resp["access_token"]
    with open(secrets_file, "w") as f:
        json.dump(creds, f, indent=2)
    return creds["access_token"]


def ga4_request(token: str, endpoint: str, payload: dict) -> dict:
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:{endpoint}"
    req = urllib.request.Request(
        url, json.dumps(payload).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[ga4] HTTP {e.code}: {body}", file=sys.stderr)
        return {}


def sc_request(token: str, payload: dict) -> dict:
    encoded_site = urllib.parse.quote(SC_PROPERTY, safe="")
    url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
    req = urllib.request.Request(
        url, json.dumps(payload).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[sc] HTTP {e.code}: {body}", file=sys.stderr)
        return {}


# ── Data fetchers ──────────────────────────────────────────────────────────────

def fetch_ga4_data(token: str) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Totals: yesterday
    totals_resp = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": yesterday, "endDate": yesterday}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "screenPageViews"},
            {"name": "bounceRate"},
            {"name": "averageSessionDuration"},
        ],
    })

    # Totals: last 7 days (for trend)
    week_resp = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": "7daysAgo", "endDate": yesterday}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "screenPageViews"},
        ],
    })

    # Top pages yesterday
    top_pages_resp = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": yesterday, "endDate": yesterday}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": "screenPageViews"}, {"name": "totalUsers"}],
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 10,
        "dimensionFilter": {
            "filter": {
                "fieldName": "pagePath",
                "stringFilter": {"matchType": "BEGINS_WITH", "value": "/posts/"}
            }
        }
    })

    # Traffic source
    source_resp = ga4_request(token, "runReport", {
        "dateRanges": [{"startDate": yesterday, "endDate": yesterday}],
        "dimensions": [{"name": "sessionDefaultChannelGroup"}],
        "metrics": [{"name": "sessions"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 6,
    })

    # Real-time active users
    rt_resp = ga4_request(token, "runRealtimeReport", {
        "metrics": [{"name": "activeUsers"}]
    })

    def row_metrics(resp):
        if resp.get("rows"):
            return [v["value"] for v in resp["rows"][0]["metricValues"]]
        return None

    totals = row_metrics(totals_resp)
    week_totals = row_metrics(week_resp)
    rt_users = (
        rt_resp["rows"][0]["metricValues"][0]["value"]
        if rt_resp.get("rows") else "0"
    )

    top_pages = []
    for row in top_pages_resp.get("rows", []):
        path = row["dimensionValues"][0]["value"]
        views = int(row["metricValues"][0]["value"])
        users = int(row["metricValues"][1]["value"])
        top_pages.append({"path": path, "views": views, "users": users})

    sources = {}
    total_sessions = 0
    for row in source_resp.get("rows", []):
        ch = row["dimensionValues"][0]["value"]
        n = int(row["metricValues"][0]["value"])
        sources[ch] = n
        total_sessions += n

    return {
        "yesterday": yesterday,
        "totals": totals,
        "week_totals": week_totals,
        "top_pages": top_pages,
        "sources": sources,
        "total_sessions": total_sessions,
        "rt_users": rt_users,
        "has_data": totals is not None,
    }


def fetch_sc_data(token: str) -> dict:
    # SC data lags 2-3 days — use 3-5 days ago
    end   = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

    # Top queries
    q_resp = sc_request(token, {
        "startDate": start, "endDate": end,
        "dimensions": ["query"],
        "rowLimit": 20,
        "orderBy": [{"fieldName": "clicks", "sortOrder": "DESCENDING"}]
    })

    # Top pages
    p_resp = sc_request(token, {
        "startDate": start, "endDate": end,
        "dimensions": ["page"],
        "rowLimit": 10,
        "orderBy": [{"fieldName": "clicks", "sortOrder": "DESCENDING"}]
    })

    # Low CTR pages (high impressions, low clicks)
    ctr_resp = sc_request(token, {
        "startDate": start, "endDate": end,
        "dimensions": ["page"],
        "rowLimit": 50,
        "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}]
    })

    top_queries = q_resp.get("rows", [])
    top_pages   = p_resp.get("rows", [])

    # Filter low-CTR pages
    low_ctr = [
        r for r in ctr_resp.get("rows", [])
        if r.get("impressions", 0) >= 200 and r.get("ctr", 1) < 0.02
    ]
    low_ctr.sort(key=lambda r: r.get("impressions", 0), reverse=True)

    total_clicks      = sum(r.get("clicks", 0) for r in top_queries)
    total_impressions = sum(r.get("impressions", 0) for r in q_resp.get("rows", []))

    return {
        "period": f"{start} → {end}",
        "top_queries": top_queries[:10],
        "top_pages": top_pages[:10],
        "low_ctr_pages": low_ctr[:5],
        "total_clicks": total_clicks,
        "total_impressions": total_impressions,
        "has_data": len(top_queries) > 0,
    }


# ── Formatter ──────────────────────────────────────────────────────────────────

def format_report(ga4: dict, sc: dict, date_str: str) -> str:
    lines = [f"📊 **SEO Daily — {date_str}**\n"]

    # GA4 section
    if ga4["has_data"]:
        t = ga4["totals"]
        sessions = int(t[0]) if t else 0
        users    = int(t[1]) if t else 0
        views    = int(t[2]) if t else 0
        bounce   = float(t[3]) if t else 0
        dur      = float(t[4]) if t else 0
        rt       = ga4["rt_users"]

        lines.append("**GA4 (eilen)**")
        lines.append(f"Sessiot: {sessions:,} | Käyttäjät: {users:,} | Sivulataukset: {views:,}")
        lines.append(f"Välittömät poistumiset: {bounce:.0%} | Kesto: {dur:.0f}s | Reaaliajassa: {rt}")

        if ga4["sources"]:
            src_parts = []
            for ch, n in sorted(ga4["sources"].items(), key=lambda x: -x[1])[:4]:
                pct = 100 * n / ga4["total_sessions"] if ga4["total_sessions"] else 0
                src_parts.append(f"{ch} {pct:.0f}%")
            lines.append("Lähteet: " + " | ".join(src_parts))

        if ga4["top_pages"]:
            lines.append("\nTop sivut (eilen):")
            for p in ga4["top_pages"][:5]:
                path = p["path"]
                slug = path.split("/")[-2] if path.endswith("/") else path.split("/")[-1]
                slug = slug[:55] + "…" if len(slug) > 55 else slug
                lines.append(f"  {p['views']} latausta  {slug}")
    else:
        lines.append("**GA4:** Ei dataa vielä (uusi kiinteistö, odota 24-72h)")

    lines.append("")

    # SC section
    if sc["has_data"]:
        lines.append(f"**Search Console** ({sc['period']})")
        lines.append(f"Klikkaukset: {sc['total_clicks']:,} | Näyttökerrat: {sc['total_impressions']:,}")

        if sc["top_queries"]:
            lines.append("\nTop hakusanat:")
            for r in sc["top_queries"][:5]:
                q    = r.get("keys", ["?"])[0]
                cl   = r.get("clicks", 0)
                imp  = r.get("impressions", 0)
                ctr  = r.get("ctr", 0)
                pos  = r.get("position", 0)
                lines.append(f"  `{q[:40]}` — {cl} klik, {imp:,} näyttöä, {ctr:.1%} CTR, pos {pos:.1f}")

        if sc["low_ctr_pages"]:
            lines.append("\n⚠️ Matala CTR (parannuspotentiaalia):")
            for r in sc["low_ctr_pages"][:3]:
                page = r.get("keys", ["?"])[0]
                slug = page.rstrip("/").split("/")[-1][:50]
                imp  = r.get("impressions", 0)
                ctr  = r.get("ctr", 0)
                pos  = r.get("position", 0)
                lines.append(f"  `{slug}` — {imp:,} näyttöä, {ctr:.1%} CTR, pos {pos:.1f} → korjaa otsikko/kuvaus")
    else:
        lines.append("**Search Console:** Ei dataa vielä (2-3 päivän viive uusille kiinteistöille)")
        lines.append("⚠️ Muistutus: Sitemap pitää rekisteröidä Search Consoleen:")
        lines.append("  → <https://search.google.com/search-console> → Sitemaps → `https://uutistenlukija.fi/sitemap.xml`")

    return "\n".join(lines)


# ── Discord poster ─────────────────────────────────────────────────────────────

def post_to_discord(message: str, channel_id: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[DRY RUN] Would post to Discord #{channel_id}:\n{message}")
        return True
    # Use OpenClaw message tool indirectly via env — this script is called by OpenClaw
    # Direct webhook fallback if BOT_TOKEN available
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not bot_token:
        # Try to read from .env
        env_file = os.path.join(SCRIPT_DIR, ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DISCORD_BOT_TOKEN="):
                        bot_token = line.split("=", 1)[1].strip().strip('"')
    if not bot_token:
        print("[discord] No BOT_TOKEN — writing to stdout for OpenClaw routing", file=sys.stderr)
        print(f"DISCORD_CHANNEL={channel_id}\n{message}")
        return False

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps({"content": message[:2000]}).encode()
    req = urllib.request.Request(
        url, payload,
        {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        print(f"[discord] Posted ✅ HTTP {resp.status}")
        return True
    except urllib.error.HTTPError as e:
        print(f"[discord] HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return False


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--discord-channel", default=SEO_CHANNEL)
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"[seo_dashboard] Refreshing tokens...")
    ga4_token = refresh_google_token(GA4_SECRETS, "https://www.googleapis.com/auth/analytics.readonly")
    sc_token  = refresh_google_token(SC_SECRETS, "https://www.googleapis.com/auth/webmasters.readonly")

    print("[seo_dashboard] Fetching GA4 data...")
    ga4 = fetch_ga4_data(ga4_token)

    print("[seo_dashboard] Fetching Search Console data...")
    sc = fetch_sc_data(sc_token)

    report = format_report(ga4, sc, date_str)
    print("\n" + report)

    # Write state
    state = {
        "date": date_str,
        "ga4_has_data": ga4["has_data"],
        "sc_has_data": sc["has_data"],
        "ga4_sessions": ga4["totals"][0] if ga4.get("totals") else 0,
        "sc_clicks": sc.get("total_clicks", 0),
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    post_to_discord(report, args.discord_channel, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
