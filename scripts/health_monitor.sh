#!/usr/bin/env bash
# =============================================================================
# health_monitor.sh — monitors site health and Actions publishing status
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
PIPELINE_STATUS_URL="${PIPELINE_STATUS_URL:-https://uutistenlukija.fi/api/pipeline-status.json}"
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
PIPELINE_STATUS_STALE_HOURS="${PIPELINE_STATUS_STALE_HOURS:-${PIPELINE_RUN_STALE_HOURS:-1}}"
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

get_json_field() {
    # get_json_field <json_string> <key> [nested_key ...]
    printf '%s\n' "$1" | python3 -c '
import json
import sys

value = json.load(sys.stdin)
for key in sys.argv[1:]:
    if not isinstance(value, dict):
        value = None
        break
    value = value.get(key)

if value is None:
    print("")
elif value is True:
    print("true")
elif value is False:
    print("false")
elif isinstance(value, (str, int, float)):
    print(value)
else:
    print("")
' "${@:2}" 2>/dev/null || echo ""
}

age_hours() {
    python3 -c '
from datetime import datetime, timezone
import sys

try:
    ref = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
    print(f"{(datetime.now(timezone.utc) - ref).total_seconds() / 3600:.1f}")
except Exception:
    print("")
' "$1" 2>/dev/null || echo ""
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
last_status=$(get_json_field "$state" "lastStatus")
last_alert_time=$(get_json_field "$state" "lastAlertTime")
consecutive=$(get_json_field "$state" "consecutiveFailures")
last_condition=$(get_json_field "$state" "lastAlertCondition")

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

# The staged Actions publisher writes and deploys this artifact on every
# admitted cycle. It is the publishing freshness/queue authority; health.json
# can retain null runtime markers after the retired VPS writer is gone.
pipeline_http_status=""
pipeline_status_json=""
pipeline_curl_ok=true

pipeline_status_json=$(curl -sf --max-time 15 \
    -w "\n__HTTP_STATUS__%{http_code}" \
    "$PIPELINE_STATUS_URL" 2>/dev/null) || pipeline_curl_ok=false

if [[ "$pipeline_curl_ok" == "true" ]]; then
    pipeline_http_status=$(echo "$pipeline_status_json" | grep '__HTTP_STATUS__' | sed 's/__HTTP_STATUS__//')
    pipeline_status_json=$(echo "$pipeline_status_json" | grep -v '__HTTP_STATUS__')
fi

log "pipeline_curl_ok=$pipeline_curl_ok pipeline_http_status=$pipeline_http_status"

# ── Evaluate health ───────────────────────────────────────────────────────────
condition="ok"
alert_msg=""
detail=""

if [[ "$curl_ok" == "false" || "$http_status" != "200" ]]; then
    condition="site_down"
    detail="HTTP $http_status"
    alert_msg="🔴 **Site unreachable** — \`curl $HEALTH_URL\` failed ($detail). Manual check required."

else
    site_status=$(get_json_field "$health_json" "status")
    last_published=$(get_json_field "$health_json" "lastPublished")
    article_count=$(get_json_field "$health_json" "articleCount")

    log "status=$site_status lastPublished=$last_published articles=$article_count"

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
    if [[ -n "$last_published" ]]; then
        article_age_hours=$(age_hours "$last_published")
    fi

    article_is_stale="no"
    if [[ -n "$article_age_hours" ]]; then
        article_is_stale=$(python3 -c "print('yes' if float('${article_age_hours}') > float('${CONTENT_STALE_HOURS}') else 'no')" 2>/dev/null || echo "no")
    fi

    # A non-content health degradation (for example zero articles) remains an
    # alert. Content age itself is evaluated against the Actions artifact below.
    if [[ "$condition" == "ok" && "$site_status" == "degraded" && "$article_is_stale" != "yes" ]]; then
        condition="degraded"
        alert_msg="⚠️ **Site health degraded** — \`status=degraded\` | articles=${article_count:-?}"
    fi

    if [[ "$condition" == "ok" ]]; then
        if [[ "$pipeline_curl_ok" == "false" || "$pipeline_http_status" != "200" ]]; then
            condition="actions_status_unavailable"
            alert_msg="⚠️ **Actions pipeline status unavailable** — \`GET $PIPELINE_STATUS_URL\` failed (HTTP ${pipeline_http_status:-?}). Scheduler/deploy freshness cannot be verified."
        else
            pipeline_schema_valid=$(printf '%s\n' "$pipeline_status_json" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    runway = data.get("stagedQueueRunway")
    enabled = runway.get("publisherEnabled") if isinstance(runway, dict) else None
    severity = runway.get("severity") if isinstance(runway, dict) else None
    outbox = runway.get("outboxCount") if isinstance(runway, dict) else None
    valid = (
        isinstance(data.get("generated_at"), str)
        and data.get("status") in {"ok", "degraded"}
        and isinstance(data.get("is_stale"), bool)
        and isinstance(enabled, bool)
        and isinstance(outbox, int)
        and not isinstance(outbox, bool)
        and outbox >= 0
        and (
            (enabled and severity in {"ok", "warning", "critical"})
            or (not enabled and severity == "inactive")
        )
        and ((data.get("status") == "degraded") == data.get("is_stale"))
    )
    print("yes" if valid else "no")
except Exception:
    print("no")
' 2>/dev/null || echo "no")

            if [[ "$pipeline_schema_valid" != "yes" ]]; then
                condition="invalid_actions_status"
                alert_msg="⚠️ **Invalid Actions pipeline status** — required freshness, publish-state, or runway fields are missing/inconsistent."
            else
                pipeline_generated_at=$(get_json_field "$pipeline_status_json" "generated_at")
                pipeline_status=$(get_json_field "$pipeline_status_json" "status")
                pipeline_is_stale=$(get_json_field "$pipeline_status_json" "is_stale")
                publisher_enabled=$(get_json_field "$pipeline_status_json" "stagedQueueRunway" "publisherEnabled")
                runway_severity=$(get_json_field "$pipeline_status_json" "stagedQueueRunway" "severity")
                outbox_count=$(get_json_field "$pipeline_status_json" "stagedQueueRunway" "outboxCount")
                remaining_cycles=$(get_json_field "$pipeline_status_json" "stagedQueueRunway" "worstCaseRemainingCycles")
                pipeline_age_hours=$(age_hours "$pipeline_generated_at")

                log "actions_status=$pipeline_status generated=${pipeline_generated_at:-?} age_hours=${pipeline_age_hours:-?} is_stale=$pipeline_is_stale publisher_enabled=$publisher_enabled outbox=$outbox_count runway=$runway_severity"

                if [[ -z "$pipeline_age_hours" ]]; then
                    condition="invalid_actions_status"
                    alert_msg="⚠️ **Invalid Actions pipeline status** — \`generated_at\` is not a parseable timestamp."
                elif [[ $(python3 -c "print('yes' if float('${pipeline_age_hours}') > float('${PIPELINE_STATUS_STALE_HOURS}') else 'no')" 2>/dev/null || echo "yes") == "yes" ]]; then
                    condition="actions_status_stale"
                    alert_msg="⚠️ **Actions pipeline status stale** — last deployed **${pipeline_age_hours}h ago** (threshold ${PIPELINE_STATUS_STALE_HOURS}h). Check scheduled publisher admission and deploy."
                elif [[ "$publisher_enabled" != "true" ]]; then
                    condition="publisher_disabled"
                    alert_msg="⚠️ **Actions publisher disabled** — deployed pipeline status reports the publisher marker off."
                elif [[ "$runway_severity" == "critical" || "$runway_severity" == "warning" ]]; then
                    condition="queue_${runway_severity}"
                    alert_msg="⚠️ **Staged queue ${runway_severity}** — outbox=${outbox_count}, worst-case cycles=${remaining_cycles:-?}. Publishing is enabled but supply is depleting."
                elif [[ "$pipeline_is_stale" == "true" ]]; then
                    condition="publish_stalled"
                    alert_msg="⚠️ **Publishing stalled** — Actions status is fresh, but no article arrived within the active-hours threshold. Last article: **${article_age_hours:-unknown}h ago** | outbox=${outbox_count}"
                fi
            fi
        fi
    fi

    # Secondary degraded check: high error count (catches failures before content staleness)
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

    # A fresh Actions artifact with healthy runway and is_stale=false is the
    # canonical off-hours/quiet signal, even when legacy health content is old.
    if [[ "$condition" == "ok" && "$article_is_stale" == "yes" ]]; then
        condition="content_quiet"
        alert_msg="ℹ️ **Content quiet** — last article **${article_age_hours}h ago**, while Actions status and queue runway are healthy."
    fi
fi

# ── Recovery detection ────────────────────────────────────────────────────────
previous_was_failure=false
case "$last_status" in
    degraded|stale|site_down|invalid_health|actions_status_unavailable|invalid_actions_status|actions_status_stale|publisher_disabled|queue_warning|queue_critical|publish_stalled)
        previous_was_failure=true
        ;;
esac

if [[ ( "$condition" == "ok" || "$condition" == "content_quiet" ) && "$previous_was_failure" == "true" ]]; then
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
    # Failure conditions — apply cooldown
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
