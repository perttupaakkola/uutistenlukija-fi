#!/usr/bin/env bash
# check_pipeline_silence.sh — alerts Discord if pipeline hasn't published in >2h
set -euo pipefail

REPO="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
STATE_FILE="$REPO/pipeline/.silence_alert_state"
LOG_FILE="$REPO/pipeline/logs/cron.log"
METRICS_FILE="$REPO/pipeline/metrics.jsonl"
THRESHOLD=7200  # 2 hours in seconds
WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"

if [ -z "$WEBHOOK" ]; then
  . "$REPO/pipeline/.env" 2>/dev/null || true
  WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"
fi

if [ -z "$WEBHOOK" ]; then
  echo "$(date -u): DISCORD_METRICS_WEBHOOK not set, skipping"
  exit 0
fi

# Find last successful publish timestamp
LAST_PUBLISH=0

# Try metrics.jsonl first (most reliable)
if [ -f "$METRICS_FILE" ]; then
  LAST_LINE=$(grep '"published":[1-9]' "$METRICS_FILE" 2>/dev/null | tail -1)
  if [ -n "$LAST_LINE" ]; then
    TS=$(echo "$LAST_LINE" | python3 -c "import json,sys,datetime; d=json.load(sys.stdin); print(int(datetime.datetime.fromisoformat(d['timestamp'].replace('Z','+00:00')).timestamp()))" 2>/dev/null || echo 0)
    [ "$TS" -gt "$LAST_PUBLISH" ] && LAST_PUBLISH=$TS
  fi
fi

# Fall back to .last_run
if [ -f "$REPO/pipeline/.last_run" ]; then
  TS=$(cat "$REPO/pipeline/.last_run" 2>/dev/null | tr -d '[:space:]')
  [ "$TS" -gt "$LAST_PUBLISH" ] 2>/dev/null && LAST_PUBLISH=$TS || true
fi

# Fall back to cron.log last success
if [ "$LAST_PUBLISH" -eq 0 ] && [ -f "$LOG_FILE" ]; then
  TS=$(grep -o 'Auto-publish completed at .*' "$LOG_FILE" 2>/dev/null | tail -1 | sed 's/Auto-publish completed at //' | xargs -I{} date -d '{}' +%s 2>/dev/null || echo 0)
  [ "$TS" -gt 0 ] && LAST_PUBLISH=$TS
fi

if [ "$LAST_PUBLISH" -eq 0 ]; then
  echo "$(date -u): Could not determine last publish time, skipping alert"
  exit 0
fi

NOW=$(date +%s)
AGE=$((NOW - LAST_PUBLISH))

if [ "$AGE" -lt "$THRESHOLD" ]; then
  echo "$(date -u): Pipeline healthy, last publish ${AGE}s ago"
  # Clear alert state if recovering
  rm -f "$STATE_FILE"
  exit 0
fi

# Check cooldown — don't spam (6h cooldown)
if [ -f "$STATE_FILE" ]; then
  LAST_ALERT=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
  COOLDOWN=21600
  if [ $((NOW - LAST_ALERT)) -lt $COOLDOWN ]; then
    echo "$(date -u): Alert already sent, cooldown active"
    exit 0
  fi
fi

HOURS=$((AGE / 3600))
MINS=$(( (AGE % 3600) / 60 ))

curl -s -X POST "$WEBHOOK"   -H 'Content-Type: application/json'   -d "{\"content\":\"⚠️ **Pipeline hiljaisuusvaroitus** — viimeisin julkaisu ${HOURS}h ${MINS}min sitten. Tarkista pipeline.\"}" > /dev/null

echo "$NOW" > "$STATE_FILE"
echo "$(date -u): Alert sent — pipeline silent for ${HOURS}h ${MINS}min"
