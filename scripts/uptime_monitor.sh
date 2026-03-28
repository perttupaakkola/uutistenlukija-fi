#!/usr/bin/env bash
# uptime_monitor.sh — checks if uutistenlukija.fi is responding
# Alerts via DISCORD_METRICS_WEBHOOK only after 2+ consecutive failures (avoids flaps)
set -euo pipefail

SITE="https://uutistenlukija.fi"
WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"
PROJECT="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
STATE_FILE="$PROJECT/pipeline/.uptime_fail_count"
LOG_FILE="$PROJECT/pipeline/logs/uptime.log"
ALERT_THRESHOLD=2
COOLDOWN=1800

if [ -z "$WEBHOOK" ]; then
  . "$PROJECT/pipeline/.env" 2>/dev/null || true
  WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"
fi

log() { echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ'): $*" | tee -a "$LOG_FILE"; }

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$SITE" 2>/dev/null || echo 0)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
  log "UP (HTTP $HTTP_CODE)"
  rm -f "$STATE_FILE"
  exit 0
fi

FAIL_COUNT=0
LAST_ALERT=0
if [ -f "$STATE_FILE" ]; then
  FAIL_COUNT=$(awk 'NR==1{print $1}' "$STATE_FILE" 2>/dev/null || echo 0)
  LAST_ALERT=$(awk 'NR==2{print $1}' "$STATE_FILE" 2>/dev/null || echo 0)
fi

FAIL_COUNT=$((FAIL_COUNT + 1))
NOW=$(date +%s)

log "DOWN (HTTP $HTTP_CODE) — consecutive failures: $FAIL_COUNT"

if [ "$FAIL_COUNT" -ge "$ALERT_THRESHOLD" ] && [ $((NOW - LAST_ALERT)) -ge "$COOLDOWN" ]; then
  if [ -n "$WEBHOOK" ]; then
    curl -s -X POST "$WEBHOOK" \
      -H 'Content-Type: application/json' \
      -d "{\"content\":\"🔴 **uutistenlukija.fi on alhaalla** — HTTP $HTTP_CODE ($FAIL_COUNT peräkkäistä virhettä). Tarkista Cloudflare Pages.\"}" > /dev/null
    log "Alert sent (threshold=$ALERT_THRESHOLD, cooldown=${COOLDOWN}s)"
  fi
  LAST_ALERT=$NOW
fi

printf '%s\n%s\n' "$FAIL_COUNT" "$LAST_ALERT" > "$STATE_FILE"
