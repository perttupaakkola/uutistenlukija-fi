#!/usr/bin/env bash
# uptime_monitor.sh — Monitor uutistenlukija.fi uptime and response time
#
# Checks HTTP status and response time every run.
# Alerts to #operations via Discord webhook on failure or slow response.
#
# Cron (every 15min):
#   */15 * * * * cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && bash scripts/uptime_monitor.sh >> pipeline/logs/uptime-monitor.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/pipeline/.env"
LOG_FILE="$PROJECT_DIR/pipeline/logs/uptime-monitor.log"
TARGET_URL="${UPTIME_TARGET_URL:-https://uutistenlukija.fi/}"
SLOW_THRESHOLD="${SLOW_THRESHOLD:-5}"  # seconds
ALERT_COOLDOWN_FILE="/tmp/uptime_alert_cooldown"
ALERT_COOLDOWN_SECS=1800  # 30 min between repeat alerts

# Load .env for webhook
if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
fi
WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"

NOW="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
mkdir -p "$(dirname "$LOG_FILE")"

# --- Check cooldown ---
should_alert() {
    if [[ -f "$ALERT_COOLDOWN_FILE" ]]; then
        local last_alert
        last_alert=$(cat "$ALERT_COOLDOWN_FILE" 2>/dev/null || echo 0)
        local now_ts
        now_ts=$(date +%s)
        if (( now_ts - last_alert < ALERT_COOLDOWN_SECS )); then
            return 1  # Still in cooldown
        fi
    fi
    return 0
}

mark_alerted() {
    date +%s > "$ALERT_COOLDOWN_FILE"
}

# --- Send Discord alert ---
send_alert() {
    local message="$1"
    if [[ -z "$WEBHOOK" ]]; then
        echo "[$NOW] ALERT (no webhook configured): $message" >> "$LOG_FILE"
        return
    fi
    curl -s -X POST "$WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$message\"}" \
        -o /dev/null \
        --max-time 10 || true
    echo "[$NOW] Alert sent: $message" >> "$LOG_FILE"
}

# --- Perform check ---
result=$(curl -o /dev/null -s -w "%{http_code}|%{time_total}" \
    --max-time 15 \
    --connect-timeout 10 \
    -L "$TARGET_URL" 2>/dev/null) || result="000|15.000"

http_code="${result%%|*}"
time_total="${result##*|}"
time_int=$(echo "$time_total" | cut -d. -f1)

echo "[$NOW] status=$http_code time=${time_total}s url=$TARGET_URL" >> "$LOG_FILE"

# --- Evaluate ---
if [[ "$http_code" != "200" ]]; then
    if should_alert; then
        mark_alerted
        send_alert "⚠️ **Uptime alert:** uutistenlukija.fi returned HTTP $http_code at $NOW. Check Cloudflare Pages status."
    fi
elif (( time_int >= SLOW_THRESHOLD )); then
    if should_alert; then
        mark_alerted
        send_alert "🐢 **Slow response:** uutistenlukija.fi responded in ${time_total}s (threshold: ${SLOW_THRESHOLD}s) at $NOW."
    fi
else
    # Clear cooldown on recovery
    rm -f "$ALERT_COOLDOWN_FILE"
fi
