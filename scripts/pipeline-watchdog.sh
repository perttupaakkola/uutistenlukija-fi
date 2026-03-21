#!/usr/bin/env bash
# =============================================================================
# pipeline-watchdog.sh — auto-recovery wrapper for the article pipeline
#
# Usage:
#   ./scripts/pipeline-watchdog.sh [pipeline_command...]
#
# If no command is given, defaults to running auto_publish.sh in the project root.
#
# Behaviour:
#   - Runs the pipeline command once
#   - On non-zero exit: logs failure, waits with exponential backoff, retries
#   - Backoff sequence: 30s → 60s → 120s → 300s (5 min cap)
#   - After 10 minutes of continuous success, resets the restart counter
#   - After 5 consecutive failures: stops and posts alert to #operations webhook
#
# Environment:
#   DISCORD_PIPELINE_WEBHOOK  — webhook URL for failure alerts (from .env)
#   PROJECT_DIR               — project root (defaults to dir above scripts/)
#
# Log:
#   pipeline/logs/pipeline-failures.log
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
LOG_FILE="$PROJECT_DIR/pipeline/logs/pipeline-failures.log"
ENV_FILE="$PROJECT_DIR/.env"

MAX_RETRIES=5
SUCCESS_RESET_SECS=600   # 10 minutes
BACKOFF_INITIAL=30
BACKOFF_MAX=300

# Default pipeline command if none given
if [[ $# -eq 0 ]]; then
    PIPELINE_CMD=("$PROJECT_DIR/pipeline/auto_publish.sh")
else
    PIPELINE_CMD=("$@")
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }

log_failure() {
    local attempt="$1" exit_code="$2" stderr_tail="$3"
    mkdir -p "$(dirname "$LOG_FILE")"
    {
        echo "──────────────────────────────────────────────────────────"
        echo "FAILURE  $(ts)"
        echo "Attempt: $attempt / $MAX_RETRIES"
        echo "Exit code: $exit_code"
        echo "Command: ${PIPELINE_CMD[*]}"
        echo "--- last 20 lines of stderr ---"
        echo "$stderr_tail"
        echo "──────────────────────────────────────────────────────────"
    } >> "$LOG_FILE"
}

log_info() {
    echo "[watchdog $(ts)] $*"
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "[$(ts)] INFO  $*" >> "$LOG_FILE"
}

post_discord_alert() {
    local msg="$1"
    local webhook="${DISCORD_PIPELINE_WEBHOOK:-}"

    # Source .env if webhook not already set
    if [[ -z "$webhook" && -f "$ENV_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$ENV_FILE" || true
        webhook="${DISCORD_PIPELINE_WEBHOOK:-}"
    fi

    if [[ -z "$webhook" ]]; then
        log_info "No Discord webhook configured — alert skipped."
        return
    fi

    # Truncate message to 2000 chars (Discord limit)
    local payload
    payload=$(printf '%s' "$msg" | head -c 1980)
    local json
    json=$(printf '{"content": "%s"}' "$(echo "$payload" | sed 's/"/\\"/g; s/$/\\n/g' | tr -d '\n')")

    curl -sf -X POST "$webhook" \
        -H 'Content-Type: application/json' \
        -d "$json" \
        >/dev/null 2>&1 || true
}

# ── Main loop ─────────────────────────────────────────────────────────────────

# Source .env if present (for webhook etc.)
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE" || true
    set +a
fi

log_info "Watchdog started. Command: ${PIPELINE_CMD[*]}"

attempt=0
backoff=$BACKOFF_INITIAL
last_success_ts=0

while true; do
    attempt=$(( attempt + 1 ))
    run_start=$(date +%s)

    log_info "Starting run #$attempt..."

    # Run pipeline, capture stderr
    stderr_file=$(mktemp)
    exit_code=0
    if "${PIPELINE_CMD[@]}" 2>"$stderr_file"; then
        exit_code=0
    else
        exit_code=$?
    fi
    run_end=$(date +%s)
    run_duration=$(( run_end - run_start ))

    stderr_tail=$(tail -20 "$stderr_file")
    rm -f "$stderr_file"

    if [[ $exit_code -eq 0 ]]; then
        log_info "Run #$attempt succeeded in ${run_duration}s."

        # Track continuous success for reset
        last_success_ts=$(date +%s)

        # Reset backoff / attempt counter after 10 min of success
        if [[ $(( last_success_ts - run_start )) -ge $SUCCESS_RESET_SECS || \
              $run_duration -ge $SUCCESS_RESET_SECS ]]; then
            log_info "10+ min successful run — resetting restart counter."
            attempt=0
            backoff=$BACKOFF_INITIAL
        fi

        # Single-run mode: if pipeline exits 0, we're done (not a daemon)
        break

    else
        log_failure "$attempt" "$exit_code" "$stderr_tail"
        log_info "Run #$attempt FAILED (exit $exit_code, ${run_duration}s)."

        if [[ $attempt -ge $MAX_RETRIES ]]; then
            log_info "Hit $MAX_RETRIES consecutive failures. Stopping watchdog."

            # Grab last 30 lines of failure log for alert
            alert_log=$(tail -40 "$LOG_FILE" 2>/dev/null || echo "(log unavailable)")

            post_discord_alert "⚠️ **Pipeline watchdog STOPPED** — $MAX_RETRIES consecutive failures.

**Command:** \`${PIPELINE_CMD[*]}\`
**Last failure:** exit code $exit_code
\`\`\`
$alert_log
\`\`\`
Manual intervention required. Check \`pipeline/logs/pipeline-failures.log\`."

            exit 1
        fi

        # Exponential backoff
        log_info "Waiting ${backoff}s before retry (attempt $attempt / $MAX_RETRIES)..."
        sleep "$backoff"

        # Double backoff, cap at max
        backoff=$(( backoff * 2 ))
        if [[ $backoff -gt $BACKOFF_MAX ]]; then
            backoff=$BACKOFF_MAX
        fi
    fi
done

log_info "Watchdog exiting cleanly."
