#!/usr/bin/env bash
# check_pipeline_silence.sh — Alert to #operations if pipeline has been silent
#
# Checks when the last article was published. If older than THRESHOLD_HOURS
# and within active hours (06:00-22:00 UTC), posts a Discord alert.
#
# Usage:
#   bash scripts/check_pipeline_silence.sh [--hours N]
#
# Cron (every 6h):
#   0 */6 * * * cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && bash scripts/check_pipeline_silence.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HEALTH_JSON="$PROJECT_DIR/static/api/health.json"
ENV_FILE="$PROJECT_DIR/pipeline/.env"
THRESHOLD_HOURS="${1:-6}"

# Parse --hours flag
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hours) THRESHOLD_HOURS="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# Load .env for webhook URL
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi

DISCORD_WEBHOOK="${DISCORD_OPERATIONS_WEBHOOK:-${DISCORD_PIPELINE_WEBHOOK:-}}"

# Get current UTC hour for active-hours check
CURRENT_HOUR=$(date -u +%H)
CURRENT_HOUR=$((10#$CURRENT_HOUR))

# Read last published timestamp from health.json
if [[ ! -f "$HEALTH_JSON" ]]; then
    echo "[silence_check] health.json not found at $HEALTH_JSON — skipping" >&2
    exit 0
fi

LAST_PUBLISHED=$(python3 -c "
import json, sys
try:
    d = json.load(open('$HEALTH_JSON'))
    print(d.get('lastPublished', ''))
except Exception as e:
    print('', file=sys.stderr)
    sys.exit(0)
" 2>/dev/null || echo "")

if [[ -z "$LAST_PUBLISHED" ]]; then
    echo "[silence_check] Could not read lastPublished — skipping"
    exit 0
fi

# Calculate age in hours
AGE_HOURS=$(python3 -c "
from datetime import datetime, timezone
import sys
ts = '$LAST_PUBLISHED'
try:
    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'
    last = datetime.fromisoformat(ts)
    now = datetime.now(timezone.utc)
    hours = (now - last).total_seconds() / 3600
    print(f'{hours:.1f}')
except Exception as e:
    print('0', file=sys.stderr)
    sys.exit(0)
" 2>/dev/null || echo "0")

echo "[silence_check] status=OK age=${AGE_HOURS}h last=$LAST_PUBLISHED"

# Check threshold
AGE_INT=$(python3 -c "print(int(float('$AGE_HOURS')))" 2>/dev/null || echo "0")

if (( AGE_INT >= THRESHOLD_HOURS )); then
    # Only alert during active hours (06:00-22:00 UTC)
    if (( CURRENT_HOUR >= 6 && CURRENT_HOUR < 22 )); then
        MSG="⚠️ **Pipeline hiljaa ${AGE_HOURS}h** — viimeisin artikkeli julkaistu \`$LAST_PUBLISHED\`.\nTarkista cron / firehose / pipeline status.\n\`\`\`bash\nbash scripts/pipeline-status.sh\n\`\`\`"
        echo "[silence_check] ALERT: Pipeline silent ${AGE_HOURS}h — posting to Discord"

        if [[ -n "$DISCORD_WEBHOOK" ]]; then
            python3 -c "
import json, urllib.request
webhook = '$DISCORD_WEBHOOK'
msg = '''$MSG'''
payload = json.dumps({'content': msg}).encode()
req = urllib.request.Request(webhook, data=payload, headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print(f'[silence_check] Alert sent (HTTP {r.status})')
except Exception as e:
    print(f'[silence_check] Alert failed: {e}')
" 2>&1
        else
            echo "[silence_check] DISCORD_OPERATIONS_WEBHOOK not set — alert not sent"
        fi
    else
        echo "[silence_check] Age ${AGE_HOURS}h exceeds threshold but outside active hours (${CURRENT_HOUR}h UTC) — no alert"
    fi
else
    echo "[silence_check] Pipeline active — last article ${AGE_HOURS}h ago. No alert."
fi
