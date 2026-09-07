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


def query(token, payload):
    url = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
           + urllib.parse.quote(SITE_URL, safe="") + "/searchAnalytics/query")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
          method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def fetch_report(token, days=28, *, page_size=25000, max_rows=100000, now=None, query_fn=None):
    """Bounded pagination of provider-visible rows, plus independent property totals.

    Exhausting pagination does not prove all search queries/pages were disclosed.
    Existing percent `ctr` remains compatible; canonical `ctr_fraction` is exact.
    """
    from analytics_contract import ctr_fraction
    if not 1 <= days <= 480 or not 1 <= page_size <= 25000 or max_rows < 1:
        raise ValueError("invalid collection limits")
    now = now or datetime.now(timezone.utc)
    query_fn = query_fn or query
    end = (now - timedelta(days=3)).date()
    start = end - timedelta(days=days - 1)
    window = {"startDate": start.isoformat(), "endDate": end.isoformat()}
    base = dict(window, type="web", dataState="final")
    rows, seen, calls, exhausted = [], set(), 0, False
    while len(rows) < max_rows:
        limit = min(page_size, max_rows - len(rows))
        response = query_fn(token, dict(base, dimensions=["page"], aggregationType="byPage",
                                        rowLimit=limit, startRow=len(rows)))
        page = response.get("rows", [])
        calls += 1
        if len(page) > limit:
            raise ValueError("provider exceeded requested row limit")
        for row in page:
            url = row["keys"][0]
            if url in seen:
                raise ValueError("duplicate page across pagination")
            seen.add(url)
            fraction = ctr_fraction(row)
            rows.append({"url": url, "impressions": row["impressions"], "clicks": row["clicks"],
                         "ctr": round(fraction * 100, 2), "ctr_fraction": fraction,
                         "position": round(row["position"], 1)})
        if len(page) < limit:
            exhausted = True
            break
    aggregate = query_fn(token, dict(base, aggregationType="byProperty", rowLimit=1))
    totals = aggregate.get("rows", [])
    if len(totals) != 1 or aggregate.get("responseAggregationType") != "byProperty":
        raise ValueError("missing property aggregate")
    total = totals[0]
    return {"schema_version": 2, "generated_at": now.isoformat(), "site": SITE_URL,
            "days": days, "query_window": window, "search_type": "web", "data_state": "final",
            "ctr_unit": "percent", "canonical_ctr_field": "ctr_fraction",
            "row_count": len(rows), "rows": rows,
            "property_totals": {"clicks": total["clicks"], "impressions": total["impressions"],
                                "ctr_fraction": ctr_fraction(total), "position": total["position"],
                                "aggregation_type": "byProperty"},
            "completeness": {"pagination_exhausted": exhausted, "row_limit_reached": not exhausted,
                             "page_size": page_size, "max_rows": max_rows, "page_requests": calls,
                             "scope": "provider_visible_page_rows",
                             "provider_limits": "Top rows only; privacy omissions and provider limits may apply. Dimension sums are not property totals."}}


def fetch_rows(token, days=28):
    """Compatibility API for callers expecting a list of percentage-valued rows."""
    return fetch_report(token, days)["rows"]


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

    try:
        out = fetch_report(token, args.days)
    except (ValueError, KeyError, urllib.error.URLError):
        print("[fetch_sc] collection failed; existing artifact preserved", file=sys.stderr)
        return 1
    rows = out["rows"]
    if not rows:
        print("[fetch_sc] no rows returned"); return 1
    print(f"[fetch_sc] got {len(rows)} pages ({args.days}d)")
    rows.sort(key=lambda r: -r["impressions"])
    if args.dry_run:
        print(json.dumps(out, indent=2)[:600]); return 0
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[fetch_sc] written {len(rows)} rows to {OUTPUT_FILE.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
