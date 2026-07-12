#!/usr/bin/env bash
# =============================================================================
# health_monitor.sh — monitors /api/health.json and alerts #operations
#
# Runs every 15 min (matching pipeline cadence).
# State file: pipeline/logs/health-monitor-state.json
# Alert target: $DISCORD_PIPELINE_WEBHOOK (#operations)
# Escalation (3 consecutive degraded): also pings #general
#
# Usage: ./scripts/health_monitor.sh [--dry-run]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
STATE_FILE="${STATE_FILE:-$PROJECT_DIR/pipeline/logs/health-monitor-state.json}"
HEALTH_URL="${HEALTH_URL:-https://uutistenlukija.fi/api/health.json}"
SNAPSHOT_FILE="${SNAPSHOT_FILE:-$PROJECT_DIR/static/metrics/snapshot.json}"
ALERT_COOLDOWN_SECS=3600   # max 1 alert/hour for same condition
ESCALATION_THRESHOLD=3     # consecutive degraded before pinging #general

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# ── Load env ──────────────────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE" || true
    set +a
fi

WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"
GENERAL_WEBHOOK="${DISCORD_GENERAL_WEBHOOK:-$WEBHOOK}"  # fallback to same webhook
PIPELINE_RUN_STALE_HOURS="${PIPELINE_RUN_STALE_HOURS:-1}"
CONTENT_STALE_HOURS="${CONTENT_STALE_HOURS:-6}"

# ── State helpers ─────────────────────────────────────────────────────────────
now=$(date +%s)

read_state() {
    if [[ -f "$STATE_FILE" ]]; then
        cat "$STATE_FILE"
    else
        echo '{"lastStatus":"unknown","lastAlertTime":0,"consecutiveFailures":0,"lastAlertCondition":""}'
    fi
}

write_state() {
    local status="$1" alert_time="$2" consecutive="$3" condition="$4"
    mkdir -p "$(dirname "$STATE_FILE")"
    cat > "$STATE_FILE" << STATEOF
{"lastStatus":"$status","lastAlertTime":$alert_time,"consecutiveFailures":$consecutive,"lastAlertCondition":"$condition"}
STATEOF
}

get_field() {
    # get_field <json_string> <key>
    echo "$1" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$2',''))" 2>/dev/null || echo ""
}

post_discord() {
    local webhook="$1" message="$2"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] Would post to Discord: $message"
        return 0
    fi
    if [[ -z "$webhook" ]]; then
        echo "[health_monitor] No webhook configured — skipping alert." >&2
        return 0
    fi
    local payload
    payload=$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1]}))" "$message")
    curl -sf -X POST "$webhook" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        >/dev/null 2>&1 || echo "[health_monitor] Discord post failed." >&2
}

log() { echo "[health_monitor $(date -u '+%H:%M:%S UTC')] $*"; }

# ── Read current state ────────────────────────────────────────────────────────
state=$(read_state)
last_status=$(get_field "$state" "lastStatus")
last_alert_time=$(get_field "$state" "lastAlertTime")
consecutive=$(get_field "$state" "consecutiveFailures")
last_condition=$(get_field "$state" "lastAlertCondition")

[[ -z "$last_alert_time" ]] && last_alert_time=0
[[ -z "$consecutive"     ]] && consecutive=0

# ── Fetch health endpoint ─────────────────────────────────────────────────────
http_status=""
health_json=""
curl_ok=true

health_json=$(curl -sf --max-time 15 \
    -w "\n__HTTP_STATUS__%{http_code}" \
    "$HEALTH_URL" 2>/dev/null) || curl_ok=false

if [[ "$curl_ok" == "true" ]]; then
    http_status=$(echo "$health_json" | grep '__HTTP_STATUS__' | sed 's/__HTTP_STATUS__//')
    health_json=$(echo "$health_json" | grep -v '__HTTP_STATUS__')
fi

log "curl_ok=$curl_ok http_status=$http_status"

# ── Evaluate health ───────────────────────────────────────────────────────────
condition="ok"
alert_msg=""
detail=""

if [[ "$curl_ok" == "false" || "$http_status" != "200" ]]; then
    condition="site_down"
    detail="HTTP $http_status"
    alert_msg="🔴 **Site unreachable** — \`curl $HEALTH_URL\` failed ($detail). Manual check required."

else
    site_status=$(get_field "$health_json" "status")
    last_published=$(get_field "$health_json" "lastPublished")
    article_count=$(get_field "$health_json" "articleCount")
    generated_at=$(get_field "$health_json" "generatedAt")
    pipeline_last_run=$(echo "$health_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('pipeline') or {}).get('lastRun',''))" 2>/dev/null || echo "")

    log "status=$site_status lastPublished=$last_published pipelineLastRun=$pipeline_last_run articles=$article_count"

    case "$site_status" in
        ok|degraded)
            ;;
        *)
            condition="invalid_health"
            alert_msg="🔴 **Invalid health payload** — HTTP 200 response has missing or unrecognised \`status\`. Manual check required."
            log "Invalid health status received"
            ;;
    esac

    article_age_hours=""
    if [[ -n "$last_published" && "$last_published" != "None" && "$last_published" != "null" ]]; then
        article_age_hours=$(python3 -c "
from datetime import datetime, timezone
try:
    lp = datetime.fromisoformat('$last_published'.replace('Z','+00:00'))
    age = (datetime.now(timezone.utc) - lp).total_seconds() / 3600
    print(f'{age:.1f}')
except Exception:
    print('')
" 2>/dev/null || echo "")
    fi

    pipeline_age_hours=""
    freshness_ref="${pipeline_last_run:-$generated_at}"
    if [[ -n "$freshness_ref" && "$freshness_ref" != "None" && "$freshness_ref" != "null" ]]; then
        pipeline_age_hours=$(python3 -c "
from datetime import datetime, timezone
try:
    ref = datetime.fromisoformat('$freshness_ref'.replace('Z','+00:00'))
    age = (datetime.now(timezone.utc) - ref).total_seconds() / 3600
    print(f'{age:.1f}')
except Exception:
    print('')
" 2>/dev/null || echo "")
    fi

    article_is_stale="no"
    if [[ -n "$article_age_hours" ]]; then
        article_is_stale=$(python3 -c "print('yes' if float('${article_age_hours}') > float('${CONTENT_STALE_HOURS}') else 'no')" 2>/dev/null || echo "no")
    fi

    pipeline_run_is_stale="unknown"
    if [[ -n "$pipeline_age_hours" ]]; then
        pipeline_run_is_stale=$(python3 -c "print('yes' if float('${pipeline_age_hours}') > float('${PIPELINE_RUN_STALE_HOURS}') else 'no')" 2>/dev/null || echo "unknown")
    fi

    if [[ "$site_status" == "degraded" ]]; then
        if [[ "$article_is_stale" == "yes" && "$pipeline_run_is_stale" == "no" ]]; then
            condition="content_quiet"
            alert_msg="ℹ️ **Content quiet** — last article **${article_age_hours}h ago**, but pipeline last ran **${pipeline_age_hours}h ago**. articles=${article_count:-?}"
        else
            stale_msg=""
            if [[ -n "$article_age_hours" ]]; then
                stale_msg=" | Last article: **${article_age_hours}h ago**"
            fi
            run_msg=""
            if [[ -n "$pipeline_age_hours" ]]; then
                run_msg=" | Pipeline last run: **${pipeline_age_hours}h ago**"
            fi
            condition="degraded"
            alert_msg="⚠️ **Pipeline degraded** — \`status=degraded\`${stale_msg}${run_msg} | articles=${article_count:-?}"
        fi
    fi

    # Secondary degraded check: high error count (catches failures before 6h stale threshold)
    if [[ "$condition" == "ok" ]]; then
        if [[ -f "$SNAPSHOT_FILE" ]]; then
            _errors=$(python3 -c "
import json,sys
try: print(json.load(open(sys.argv[1])).get('pipelineErrorsToday',0))
except: print(0)
" "$SNAPSHOT_FILE" 2>/dev/null || echo 0)
            if (( _errors > 20 )); then
                condition="degraded"
                alert_msg="⚠️ **Pipeline degraded** — ${_errors} errors today (threshold >20). Check pipeline logs."
                log "High error count: errors_today=${_errors}"
            fi
        fi
    fi

    # Explicit stale check (belt + suspenders) only if content is stale AND runtime also looks stale.
    if [[ "$condition" == "ok" && "$article_is_stale" == "yes" ]]; then
        if [[ "$pipeline_run_is_stale" == "yes" || "$pipeline_run_is_stale" == "unknown" ]]; then
            condition="stale"
            if [[ -n "$pipeline_age_hours" ]]; then
                alert_msg="⚠️ **Stale pipeline** — last article published **${article_age_hours}h ago** and pipeline last ran **${pipeline_age_hours}h ago**"
            else
                alert_msg="⚠️ **Stale pipeline** — last article published **${article_age_hours}h ago** and pipeline freshness could not be verified"
            fi
        fi
    fi
fi

# ── Recovery detection ────────────────────────────────────────────────────────
if [[ "$condition" == "ok" && ( "$last_status" == "degraded" || "$last_status" == "stale" || "$last_status" == "site_down" || "$last_status" == "invalid_health" ) ]]; then
    condition="recovered"
    alert_msg="✅ **Pipeline recovered** — health check passing. Previous status: \`$last_status\`"
fi

# ── Cooldown + consecutive tracking ──────────────────────────────────────────
secs_since_alert=$(( now - last_alert_time ))
same_condition=$( [[ "$condition" == "$last_condition" ]] && echo "true" || echo "false" )
should_alert=false

if [[ "$condition" == "ok" || "$condition" == "content_quiet" ]]; then
    # No alert needed — just update state
    write_state "$condition" "$last_alert_time" "0" "$condition"
    log "Status $condition — no alert."
    exit 0

elif [[ "$condition" == "recovered" ]]; then
    # Always alert on recovery (regardless of cooldown)
    should_alert=true
    consecutive=0

else
    # Degraded / stale / site_down — apply cooldown
    consecutive=$(( consecutive + 1 ))
    if (( secs_since_alert >= ALERT_COOLDOWN_SECS )) || [[ "$condition" != "$last_condition" ]]; then
        should_alert=true
    else
        log "Condition=$condition but in cooldown (${secs_since_alert}s / ${ALERT_COOLDOWN_SECS}s) — skipping alert."
    fi
fi

# ── Post alert ────────────────────────────────────────────────────────────────
if [[ "$should_alert" == "true" ]]; then
    log "Alerting: $alert_msg"
    post_discord "$WEBHOOK" "$alert_msg"

    # Escalation: 3+ consecutive degraded checks → also ping #general
    if (( consecutive >= ESCALATION_THRESHOLD )) && [[ "$condition" != "recovered" ]]; then
        escalation_msg="🚨 **Escalation** — pipeline has been degraded for $((consecutive * 15))+ minutes. Check #operations for details."
        log "Escalating to #general (consecutive=$consecutive)"
        post_discord "$GENERAL_WEBHOOK" "$escalation_msg"
    fi

    write_state "$condition" "$now" "$consecutive" "$condition"
else
    # Update consecutive count even without alerting
    write_state "$condition" "$last_alert_time" "$consecutive" "$last_condition"
fi

log "Done. condition=$condition consecutive=$consecutive"
