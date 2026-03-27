#!/usr/bin/env bash
# uptime_monitor.sh — checks if uutistenlukija.fi is responding
set -euo pipefail

SITE="https://uutistenlukija.fi"
WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"
STATE_FILE="/home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/.uptime_alert_state"
COOLDOWN=3600

if [ -z "$WEBHOOK" ]; then
  . "/home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/.env" 2>/dev/null || true
  WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$SITE" 2>/dev/null || echo 0)
NOW=$(date +%s)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
  echo "$(date -u): Site UP (HTTP $HTTP_CODE)"
  rm -f "$STATE_FILE"
  exit 0
fi

# Down — check cooldown
if [ -f "$STATE_FILE" ]; then
  LAST_ALERT=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
  if [ $((NOW - LAST_ALERT)) -lt $COOLDOWN ]; then
    echo "$(date -u): Site down (HTTP $HTTP_CODE) — cooldown active"
    exit 0
  fi
fi

if [ -n "$WEBHOOK" ]; then
  curl -s -X POST "$WEBHOOK"     -H 'Content-Type: application/json'     -d "{\"content\":\"🔴 **uutistenlukija.fi on alhaalla** — HTTP $HTTP_CODE. Tarkista Cloudflare Pages.\"}" > /dev/null
fi

echo "$NOW" > "$STATE_FILE"
echo "$(date -u): DOWN alert sent (HTTP $HTTP_CODE)"
