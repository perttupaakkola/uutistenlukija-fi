#!/bin/bash
# pipeline-health-check.sh — lightweight pipeline health check
# Outputs a one-liner status; exits 0=OK, 1=ALERT
#
# Usage:
#   ./scripts/pipeline-health-check.sh
#   ./scripts/pipeline-health-check.sh --alert-only   (silent on OK, outputs only on ALERT)
#
# Cron example (every 30 min, alert-only):
#   */30 * * * * /home/pertt/.openclaw/workspace/projects/uutistenlukija/scripts/pipeline-health-check.sh --alert-only

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/..&& pwd)"
HEALTH_JSON="$PROJECT_DIR/static/api/health.json"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
ALERT_THRESHOLD_HOURS=3
ALERT_ONLY=false

if [[ "${1:-}" == "--alert-only" ]]; then
    ALERT_ONLY=true
fi

# ── 1. Last publish time ───────────────────────────────────────────────────
if [ ! -f "$HEALTH_JSON" ]; then
    echo "ALERT: health.json not found at $HEALTH_JSON"
    exit 1
fi

LAST_PUBLISHED=$(python3 -c "
import json, sys
data = json.load(open('$HEALTH_JSON'))
lp = data.get('lastPublished', '')
if not lp:
    print('MISSING')
    sys.exit(1)
print(lp)
")

if [ "$LAST_PUBLISHED" = "MISSING" ]; then
    echo "ALERT: lastPublished field missing from health.json"
    exit 1
fi

MINUTES_AGO=$(python3 -c "
from datetime import datetime, timezone
ts = datetime.fromisoformat('$LAST_PUBLISHED'.replace('Z', '+00:00'))
now = datetime.now(timezone.utc)
diff = int((now - ts).total_seconds() / 60)
print(diff)
")

THRESHOLD_MINUTES=$(( ALERT_THRESHOLD_HOURS * 60 ))

# ── 2. Script execute bits ─────────────────────────────────────────────────
SCRIPTS_OK=true
SCRIPTS_MISSING=()

for script in "$PIPELINE_DIR/auto_publish.sh" "$PIPELINE_DIR/watchdog.sh"; do
    if [ ! -f "$script" ]; then
        SCRIPTS_OK=false
        SCRIPTS_MISSING+=("$(basename $script) MISSING")
    elif [ ! -x "$script" ]; then
        SCRIPTS_OK=false
        SCRIPTS_MISSING+=("$(basename $script) -x")
    fi
done

SCRIPTS_STATUS="✅"
if [ "$SCRIPTS_OK" = false ]; then
    SCRIPTS_STATUS="❌ (${SCRIPTS_MISSING[*]})"
fi

# ── 3. Format time human-readable ─────────────────────────────────────────
format_duration() {
    local mins=$1
    if (( mins < 60 )); then
        echo "${mins}min"
    else
        local h=$(( mins / 60 ))
        local m=$(( mins % 60 ))
        if (( m == 0 )); then
            echo "${h}h"
        else
            echo "${h}h ${m}min"
        fi
    fi
}

DURATION=$(format_duration "$MINUTES_AGO")

# ── 4. Output ──────────────────────────────────────────────────────────────
if (( MINUTES_AGO > THRESHOLD_MINUTES )); then
    MSG="ALERT: no publish in $DURATION | scripts: $SCRIPTS_STATUS"
    echo "$MSG"
    exit 1
else
    MSG="OK: last publish ${DURATION} ago | scripts: $SCRIPTS_STATUS"
    if [ "$ALERT_ONLY" = false ]; then
        echo "$MSG"
    fi
    exit 0
fi
