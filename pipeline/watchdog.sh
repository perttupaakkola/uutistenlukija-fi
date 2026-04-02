#!/usr/bin/env bash
# watchdog.sh — Resilient wrapper for auto_publish.sh
#
# Cron calls this instead of auto_publish.sh directly.
# Features:
#   - Lock timeout guard (removes stale lock >20min before running)
#   - Quiet-hours throttle: from 00:00-05:59 UTC only run on the hour
#   - Single retry on non-zero exit (60s wait between attempts)
#   - Discord alert to #operations if both attempts fail
#   - Separate log file: pipeline/logs/watchdog_YYYYMMDD.log
#
# Usage (crontab):
#   */10 * * * * cd /path/to/project && bash pipeline/watchdog.sh
#
# Env (loaded from pipeline/.env):
#   DISCORD_PIPELINE_WEBHOOK — webhook URL for failure alerts

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PIPELINE_DIR="$SCRIPT_DIR"
LOGS_DIR="$PIPELINE_DIR/logs"
AUTO_PUBLISH="$PIPELINE_DIR/auto_publish.sh"
LOCK_FILE="$PIPELINE_DIR/.pipeline_lock"
LOG_FILE="$LOGS_DIR/watchdog_$(date -u '+%Y%m%d').log"
LOCK_MAX_AGE_SECS=1200  # 20 minutes

# ── Load .env ─────────────────────────────────────────────────────────────────
ENV_FILE="$PIPELINE_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

DISCORD_WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"
QUIET_HOURS_START_UTC=0
QUIET_HOURS_END_UTC=6  # exclusive; 00:00-05:59 UTC

# ── Helpers ───────────────────────────────────────────────────────────────────
mkdir -p "$LOGS_DIR"

log() {
    local ts
    ts=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
    echo "[$ts] $*" | tee -a "$LOG_FILE"
}

discord_alert() {
    local message="$1"
    if [[ -z "$DISCORD_WEBHOOK" ]]; then
        log "DISCORD_PIPELINE_WEBHOOK not set — skipping alert"
        return
    fi
    python3 - "$DISCORD_WEBHOOK" "$message" << 'PYEOF' 2>>"$LOG_FILE" || true
import json, sys, urllib.request
webhook, msg = sys.argv[1], sys.argv[2]
payload = json.dumps({"content": msg}).encode("utf-8")
req = urllib.request.Request(
    webhook, data=payload,
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    with urllib.request.urlopen(req, timeout=10):
        pass
except Exception as e:
    print(f"[watchdog] Discord alert failed: {e}", file=sys.stderr)
PYEOF
}

# ── Quiet-hours throttle ─────────────────────────────────────────────────────
CURRENT_HOUR_UTC=$(date -u '+%-H')
CURRENT_MINUTE_UTC=$(date -u '+%-M')
if (( CURRENT_HOUR_UTC >= QUIET_HOURS_START_UTC && CURRENT_HOUR_UTC < QUIET_HOURS_END_UTC )); then
    if (( CURRENT_MINUTE_UTC != 0 )); then
        log "Quiet-hours throttle active (${CURRENT_HOUR_UTC}:$(printf '%02d' "$CURRENT_MINUTE_UTC") UTC) — skipping non-hourly cycle."
        exit 0
    fi
fi

# ── Lock guard ────────────────────────────────────────────────────────────────
if [[ -f "$LOCK_FILE" ]]; then
    LOCK_EPOCH=$(date -r "$LOCK_FILE" +%s 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    LOCK_AGE=$(( NOW_EPOCH - LOCK_EPOCH ))

    if [[ "$LOCK_AGE" -gt "$LOCK_MAX_AGE_SECS" ]]; then
        LOCK_MIN=$(( LOCK_AGE / 60 ))
        LOCK_PID=$(awk 'NR==1' "$LOCK_FILE" 2>/dev/null || echo "unknown")

        log "WARNING: Stale lock detected (PID $LOCK_PID, ${LOCK_MIN}min old). Removing."
        rm -f "$LOCK_FILE"
        # Kill the stale process if still alive
        if [[ "$LOCK_PID" =~ ^[0-9]+$ ]] && kill -0 "$LOCK_PID" 2>/dev/null; then
            log "Killing stale pipeline process PID $LOCK_PID"
            kill "$LOCK_PID" 2>/dev/null || true
            sleep 2
            kill -9 "$LOCK_PID" 2>/dev/null || true
        fi
    else
        LOCK_MIN=$(( LOCK_AGE / 60 ))
        log "Pipeline already running (lock age ${LOCK_MIN}min). Skipping this cycle."
        exit 0
    fi
fi

# ── Run with retry ────────────────────────────────────────────────────────────
log "=== watchdog: starting auto_publish.sh ==="

run_pipeline() {
    bash "$AUTO_PUBLISH" >> "$LOG_FILE" 2>&1
}

EXIT_CODE=0

# Attempt 1
log "Attempt 1/2"
if run_pipeline; then
    log "Attempt 1 succeeded."
    exit 0
else
    EXIT_CODE=$?
    log "Attempt 1 FAILED (exit $EXIT_CODE). Waiting 60s before retry..."
fi

sleep 60

# Attempt 2
log "Attempt 2/2"
if run_pipeline; then
    log "Attempt 2 succeeded (recovered from first failure)."
    exit 0
else
    EXIT_CODE=$?
    log "Attempt 2 FAILED (exit $EXIT_CODE). Both attempts failed."
fi

# ── Double failure: Discord alert ─────────────────────────────────────────────
TS=$(date -u '+%Y-%m-%d %H:%M UTC')
MSG="🚨 **Pipeline double failure** — both attempts failed at $TS\n"
MSG+="Exit code: $EXIT_CODE\n"
MSG+="Log: \`pipeline/logs/watchdog_$(date -u '+%Y%m%d').log\`\n"
MSG+="Action needed: check \`crontab -l\` and recent logs on host."

log "Posting double-failure alert to Discord..."
discord_alert "$MSG"

log "=== watchdog: exiting with failure ==="
exit "$EXIT_CODE"
