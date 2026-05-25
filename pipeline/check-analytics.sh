#!/usr/bin/env bash
# check-analytics.sh — Pull GA4 realtime + daily stats and Search Console data.
# Outputs: /workspace/projects/uutistenlukija/analytics/daily-report.json
#
# Dependencies: curl, python3 (stdlib only), jq
# Secrets: /workspace/.secrets/analytics-tokens.json
#          /workspace/.secrets/search-console-tokens.json
#
# Token format (standard Google OAuth2):
#   { "access_token": "...", "refresh_token": "...",
#     "client_id": "...", "client_secret": "...",
#     "token_uri": "https://oauth2.googleapis.com/token" }
#
# Usage:
#   bash check-analytics.sh              # write report
#   bash check-analytics.sh --print      # also print summary to stdout

set -euo pipefail

PRINT_SUMMARY=false
[[ "${1:-}" == "--print" ]] && PRINT_SUMMARY=true

# Require jq — exit gracefully if not installed (avoids silent cron failures)
if ! command -v jq &>/dev/null; then
    echo "[check-analytics] SKIP: jq not installed. Install with: sudo apt-get install -y jq" >&2
    exit 0
fi

DEFAULT_SECRETS_DIR="/workspace/.secrets"
if [[ -d "/home/pertt/.openclaw/workspace/.secrets" ]]; then
    DEFAULT_SECRETS_DIR="/home/pertt/.openclaw/workspace/.secrets"
fi
SECRETS_DIR="${SECRETS_DIR:-$DEFAULT_SECRETS_DIR}"
ANALYTICS_TOKENS="$SECRETS_DIR/analytics-tokens.json"
SEARCH_CONSOLE_TOKENS="$SECRETS_DIR/search-console-tokens.json"
OUTPUT_DIR="/workspace/projects/uutistenlukija/analytics"
OUTPUT_FILE="$OUTPUT_DIR/daily-report.json"
PROJECT_DIR="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
SENTINEL_SCRIPT="$PROJECT_DIR/scripts/analytics_oauth_sentinel.py"
PROPERTY_ID="529369568"
SC_SITE="sc-domain:uutistenlukija.fi"
TODAY=$(date -u +%Y-%m-%d)
YESTERDAY=$(date -u -d "yesterday" +%Y-%m-%d)
SEVEN_DAYS_AGO=$(date -u -d "7 days ago" +%Y-%m-%d)
OAUTH_FAILED_SERVICES=()

mkdir -p "$OUTPUT_DIR"

# ── Token refresh helper ──────────────────────────────────────────────────────
refresh_token() {
    local token_file="$1"
    local refresh_token client_id client_secret token_uri response new_access

    refresh_token=$(jq -r '.refresh_token' "$token_file")
    client_id=$(jq -r '.client_id' "$token_file")
    client_secret=$(jq -r '.client_secret' "$token_file")
    token_uri=$(jq -r '.token_uri // "https://oauth2.googleapis.com/token"' "$token_file")

    response=$(curl -s -X POST "$token_uri" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=refresh_token" \
        -d "refresh_token=${refresh_token}" \
        -d "client_id=${client_id}" \
        -d "client_secret=${client_secret}")

    new_access=$(echo "$response" | jq -r '.access_token // empty')
    if [[ -z "$new_access" ]]; then
        echo "[check-analytics] ERROR: token refresh failed for $token_file" >&2
        echo "$response" >&2
        return 1
    fi

    # Write refreshed token back
    jq --arg tok "$new_access" '.access_token = $tok' "$token_file" > "${token_file}.tmp" \
        && mv "${token_file}.tmp" "$token_file"

    echo "$new_access"
}

get_token() {
    local token_file="$1"
    local tok
    tok=$(jq -r '.access_token // empty' "$token_file")
    echo "$tok"
}

record_oauth_sentinel() {
    local service="$1"
    OAUTH_FAILED_SERVICES+=("$service")
}

flush_oauth_sentinel() {
    if [[ "${#OAUTH_FAILED_SERVICES[@]}" -eq 0 ]]; then
        return
    fi
    if [[ -x "$SENTINEL_SCRIPT" || -f "$SENTINEL_SCRIPT" ]]; then
        local args=()
        local service
        for service in "${OAUTH_FAILED_SERVICES[@]}"; do
            args+=(--service "$service")
        done
        python3 "$SENTINEL_SCRIPT" \
            "${args[@]}" \
            --source-command "SECRETS_DIR=$SECRETS_DIR bash pipeline/check-analytics.sh" \
            --source-log "pipeline/logs/analytics.log" || true
    fi
}

# ── GA4: refresh access token ─────────────────────────────────────────────────
echo "[check-analytics] Refreshing GA4 token..."
GA4_TOKEN=$(refresh_token "$ANALYTICS_TOKENS") || {
    record_oauth_sentinel ga4
    echo "[check-analytics] Falling back to stored GA4 token"
    GA4_TOKEN=$(get_token "$ANALYTICS_TOKENS")
}

# ── GA4: Realtime active users ────────────────────────────────────────────────
echo "[check-analytics] Fetching GA4 realtime..."
REALTIME_RAW=$(curl -s -X POST \
    "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY_ID}:runRealtimeReport" \
    -H "Authorization: Bearer $GA4_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "dimensions": [{"name": "country"}],
        "metrics": [{"name": "activeUsers"}]
    }')

ACTIVE_USERS=$(echo "$REALTIME_RAW" | jq -r '
    [.rows[]?.metricValues[]?.value | tonumber] | add // 0')

# ── GA4: Daily pageviews (today + yesterday) ──────────────────────────────────
echo "[check-analytics] Fetching GA4 daily pageviews..."
DAILY_RAW=$(curl -s -X POST \
    "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY_ID}:runReport" \
    -H "Authorization: Bearer $GA4_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"dateRanges\": [{\"startDate\": \"$YESTERDAY\", \"endDate\": \"$TODAY\"}],
        \"dimensions\": [{\"name\": \"date\"}],
        \"metrics\": [
            {\"name\": \"screenPageViews\"},
            {\"name\": \"sessions\"},
            {\"name\": \"totalUsers\"}
        ],
        \"orderBys\": [{\"dimension\": {\"dimensionName\": \"date\"}, \"desc\": true}]
    }")

# ── GA4: Top pages (last 7 days) ──────────────────────────────────────────────
echo "[check-analytics] Fetching GA4 top pages..."
TOP_PAGES_RAW=$(curl -s -X POST \
    "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY_ID}:runReport" \
    -H "Authorization: Bearer $GA4_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"dateRanges\": [{\"startDate\": \"$SEVEN_DAYS_AGO\", \"endDate\": \"$TODAY\"}],
        \"dimensions\": [{\"name\": \"pagePath\"}, {\"name\": \"pageTitle\"}],
        \"metrics\": [{\"name\": \"screenPageViews\"}],
        \"orderBys\": [{\"metric\": {\"metricName\": \"screenPageViews\"}, \"desc\": true}],
        \"limit\": 10
    }")

# ── GA4: Traffic sources (last 7 days) ────────────────────────────────────────
echo "[check-analytics] Fetching GA4 traffic sources..."
SOURCES_RAW=$(curl -s -X POST \
    "https://analyticsdata.googleapis.com/v1beta/properties/${PROPERTY_ID}:runReport" \
    -H "Authorization: Bearer $GA4_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"dateRanges\": [{\"startDate\": \"$SEVEN_DAYS_AGO\", \"endDate\": \"$TODAY\"}],
        \"dimensions\": [{\"name\": \"sessionSource\"}, {\"name\": \"sessionMedium\"}],
        \"metrics\": [{\"name\": \"sessions\"}],
        \"orderBys\": [{\"metric\": {\"metricName\": \"sessions\"}, \"desc\": true}],
        \"limit\": 10
    }")

# ── Search Console: refresh token ─────────────────────────────────────────────
echo "[check-analytics] Refreshing Search Console token..."
SC_TOKEN=$(refresh_token "$SEARCH_CONSOLE_TOKENS") || {
    record_oauth_sentinel search_console
    echo "[check-analytics] Falling back to stored SC token"
    SC_TOKEN=$(get_token "$SEARCH_CONSOLE_TOKENS")
}
flush_oauth_sentinel

# ── Search Console: top queries (last 7 days) ────────────────────────────────
echo "[check-analytics] Fetching Search Console queries..."
SC_QUERIES_RAW=$(curl -s -X POST \
    "https://searchconsole.googleapis.com/webmasters/v3/sites/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe='')); " "$SC_SITE")/searchAnalytics/query" \
    -H "Authorization: Bearer $SC_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"startDate\": \"$SEVEN_DAYS_AGO\",
        \"endDate\": \"$YESTERDAY\",
        \"dimensions\": [\"query\"],
        \"rowLimit\": 10,
        \"startRow\": 0
    }")

# ── Search Console: performance totals ───────────────────────────────────────
echo "[check-analytics] Fetching Search Console totals..."
SC_TOTALS_RAW=$(curl -s -X POST \
    "https://searchconsole.googleapis.com/webmasters/v3/sites/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe='')); " "$SC_SITE")/searchAnalytics/query" \
    -H "Authorization: Bearer $SC_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"startDate\": \"$SEVEN_DAYS_AGO\",
        \"endDate\": \"$YESTERDAY\",
        \"dimensions\": [\"date\"],
        \"rowLimit\": 7
    }")

# ── Assemble report ───────────────────────────────────────────────────────────
echo "[check-analytics] Assembling report..."

python3 - "$ACTIVE_USERS" "$TODAY" <<'PYEOF'
import sys, json, os

active_users = int(sys.argv[1])
today = sys.argv[2]

def safe_load(name):
    """Read a JSON variable piped via env."""
    return json.loads(os.environ.get(name, "{}"))

def parse_report(raw_json):
    """Parse GA4 runReport response into list of row dicts."""
    try:
        data = json.loads(raw_json)
    except Exception:
        return []
    dim_hdrs = [h.get("name") for h in data.get("dimensionHeaders", [])]
    met_hdrs = [h.get("name") for h in data.get("metricHeaders", [])]
    rows = []
    for row in data.get("rows", []):
        r = {}
        for i, v in enumerate(row.get("dimensionValues", [])):
            r[dim_hdrs[i]] = v.get("value")
        for i, v in enumerate(row.get("metricValues", [])):
            r[met_hdrs[i]] = v.get("value")
        rows.append(r)
    return rows

def parse_sc(raw_json):
    try:
        data = json.loads(raw_json)
    except Exception:
        return []
    return data.get("rows", [])

PYEOF

# Use python3 for the full assembly (cleaner than jq for nested structures)
REPORT=$(python3 - <<PYEOF
import json, sys, os

def parse_ga4(raw):
    try:
        data = json.loads(raw)
    except Exception:
        return []
    dim_hdrs = [h.get("name") for h in data.get("dimensionHeaders", [])]
    met_hdrs = [h.get("name") for h in data.get("metricHeaders", [])]
    rows = []
    for row in data.get("rows", []):
        r = {}
        for i, v in enumerate(row.get("dimensionValues", [])):
            r[dim_hdrs[i]] = v.get("value")
        for i, v in enumerate(row.get("metricValues", [])):
            try:
                r[met_hdrs[i]] = int(v.get("value", 0))
            except ValueError:
                r[met_hdrs[i]] = float(v.get("value", 0))
        rows.append(r)
    return rows

def parse_sc(raw):
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data.get("rows", [])

daily   = parse_ga4("""$DAILY_RAW""")
pages   = parse_ga4("""$TOP_PAGES_RAW""")
sources = parse_ga4("""$SOURCES_RAW""")
queries = parse_sc("""$SC_QUERIES_RAW""")
sc_totals = parse_sc("""$SC_TOTALS_RAW""")

# Search Console totals
total_clicks      = sum(r.get("clicks",      0) for r in sc_totals)
total_impressions = sum(r.get("impressions", 0) for r in sc_totals)
avg_ctr = (total_clicks / total_impressions * 100) if total_impressions else 0
avg_pos = (sum(r.get("position", 0) * r.get("impressions", 0) for r in sc_totals) / total_impressions) if total_impressions else 0

report = {
    "generated_at": "$TODAY",
    "property_id": "$PROPERTY_ID",
    "site": "$SC_SITE",
    "realtime": {
        "active_users": $ACTIVE_USERS
    },
    "daily_pageviews": daily,
    "top_pages_7d": [
        {"path": r.get("pagePath"), "title": r.get("pageTitle"), "pageviews": r.get("screenPageViews", 0)}
        for r in pages[:10]
    ],
    "traffic_sources_7d": [
        {"source": r.get("sessionSource"), "medium": r.get("sessionMedium"), "sessions": r.get("sessions", 0)}
        for r in sources[:10]
    ],
    "search_console": {
        "period": "7d",
        "total_clicks": total_clicks,
        "total_impressions": total_impressions,
        "avg_ctr_pct": round(avg_ctr, 2),
        "avg_position": round(avg_pos, 1),
        "top_queries": [
            {
                "query": r.get("keys", [""])[0],
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr_pct": round(r.get("ctr", 0) * 100, 2),
                "position": round(r.get("position", 0), 1)
            }
            for r in queries[:10]
        ]
    }
}

print(json.dumps(report, ensure_ascii=False, indent=2))
PYEOF
)

echo "$REPORT" > "$OUTPUT_FILE"
echo "[check-analytics] Report written to $OUTPUT_FILE"

if [[ "$PRINT_SUMMARY" == "true" ]]; then
    echo ""
    echo "════════════════════════════════════════"
    echo "  Uutistenlukija Analytics — $TODAY"
    echo "════════════════════════════════════════"
    echo "  Active users right now: $(echo "$REPORT" | jq -r '.realtime.active_users')"
    echo ""
    echo "  Search Console (7d):"
    echo "    Clicks:      $(echo "$REPORT" | jq -r '.search_console.total_clicks')"
    echo "    Impressions: $(echo "$REPORT" | jq -r '.search_console.total_impressions')"
    echo "    CTR:         $(echo "$REPORT" | jq -r '.search_console.avg_ctr_pct')%"
    echo "    Avg position:$(echo "$REPORT" | jq -r '.search_console.avg_position')"
    echo ""
    echo "  Top pages (7d):"
    echo "$REPORT" | jq -r '.top_pages_7d[:5][] | "    \(.pageviews) views — \(.path)"'
    echo ""
    echo "  Top queries (7d):"
    echo "$REPORT" | jq -r '.search_console.top_queries[:5][] | "    pos \(.position) — \(.query) (\(.clicks) clicks)"'
    echo "════════════════════════════════════════"
fi
