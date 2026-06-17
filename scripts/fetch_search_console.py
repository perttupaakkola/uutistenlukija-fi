#!/usr/bin/env python3
"""fetch_search_console.py — Pull GSC data → static/api/search-console-data.json
Cron: daily 06:30 UTC. Usage: python3 scripts/fetch_search_console.py [--days 28] [--dry-run]
"""
import argparse, json, os, subprocess, sys, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google_access_token import service_account_access_token

SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
_SC_SECRETS = [
    "/home/pertt/.openclaw/workspace/.secrets/search-console-tokens.json",
    "/workspace/.secrets/search-console-tokens.json",
    "/home/pertt/.openclaw/workspace/projects/uutistenlukija/.secrets/search-console-tokens.json",
    "/workspace/projects/uutistenlukija/.secrets/search-console-tokens.json",
]
OUTPUT_FILE = PROJECT_DIR / "static" / "api" / "search-console-data.json"
SITE_URL = "sc-domain:uutistenlukija.fi"
SENTINEL_SCRIPT = PROJECT_DIR / "scripts" / "analytics_oauth_sentinel.py"


def find_secrets():
    for p in _SC_SECRETS:
        if os.path.exists(p): return p
    return None


def refresh_token(f):
    try:
        service_account_token = service_account_access_token(["https://www.googleapis.com/auth/webmasters.readonly"])
    except Exception as e:
        print(f"[fetch_sc] service account token failed: {e}", file=sys.stderr)
        service_account_token = None
    if service_account_token:
        token, _path, email = service_account_token
        print(f"[fetch_sc] using service account: {email}")
        return token

    creds = json.load(open(f))
    data = urllib.parse.urlencode({
        "client_id": creds["client_id"], "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.load(r).get("access_token")
        if tok:
            creds["access_token"] = tok
            json.dump(creds, open(f, "w"), indent=2)
        return tok
    except Exception as e:
        print(f"[fetch_sc] refresh failed: {e}", file=sys.stderr); return None


def record_oauth_sentinel():
    if not SENTINEL_SCRIPT.exists():
        return
    subprocess.run(
        [
            "python3",
            str(SENTINEL_SCRIPT),
            "--service",
            "search_console",
            "--source-command",
            "scripts/run_with_project_env.sh python3 scripts/fetch_search_console.py",
            "--source-log",
            "pipeline/logs/fetch-search-console.log",
        ],
        check=False,
    )


def fetch_rows(token, days=28):
    end = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    payload = json.dumps({
        "startDate": start, "endDate": end,
        "dimensions": ["page"], "rowLimit": 500
    }).encode()
    url = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
           + urllib.parse.quote(SITE_URL, safe="") + "/searchAnalytics/query")
    req = urllib.request.Request(url, data=payload,
          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
          method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.load(r).get("rows", [])
        return [{"url": r["keys"][0],
                 "impressions": r.get("impressions", 0),
                 "clicks": r.get("clicks", 0),
                 "ctr": round(r.get("ctr", 0.0) * 100, 2),
                 "position": round(r.get("position", 0.0), 1)} for r in rows]
    except urllib.error.HTTPError as e:
        print(f"[fetch_sc] HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr); return []
    except Exception as e:
        print(f"[fetch_sc] error: {e}", file=sys.stderr); return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    secrets = find_secrets()
    if not secrets:
        print("[fetch_sc] no token file found", file=sys.stderr); return 1
    print(f"[fetch_sc] using: {secrets}")
    token = refresh_token(secrets)
    if not token:
        record_oauth_sentinel()
        return 1

    rows = fetch_rows(token, args.days)
    if not rows:
        print("[fetch_sc] no rows returned"); return 1
    print(f"[fetch_sc] got {len(rows)} pages ({args.days}d)")
    rows.sort(key=lambda r: -r["impressions"])
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "days": args.days, "site": SITE_URL, "row_count": len(rows), "rows": rows}
    if args.dry_run:
        print(json.dumps(out, indent=2)[:600]); return 0
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[fetch_sc] written {len(rows)} rows to {OUTPUT_FILE.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
