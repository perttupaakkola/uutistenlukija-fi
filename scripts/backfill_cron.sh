#!/usr/bin/env bash
# backfill_cron.sh — Automated thin-article expansion with guardrails and reporting.
#
# Usage:
#   ./backfill_cron.sh                  Run normally
#   ./backfill_cron.sh --dry-run        Dry-run pass-through
#
# Guardrails:
#   - Skips if main pipeline lockfile exists (pipeline/.pipeline_lock)
#   - Skips if last backfill was <4h ago (logs/backfill-last-run.txt)
#   - Auto-escalates threshold: 50 → 100 → 150 → 200 when tier is cleared
#
# Reports to Discord #operations via $DISCORD_PIPELINE_WEBHOOK after each batch.
# Appends stats to logs/backfill-progress.json.

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
LOGS_DIR="$PIPELINE_DIR/logs"

LOCKFILE="$PIPELINE_DIR/.pipeline_lock"
LAST_RUN_FILE="$LOGS_DIR/backfill-last-run.txt"
PROGRESS_FILE="$LOGS_DIR/backfill-progress.json"
THRESHOLD_FILE="$LOGS_DIR/backfill-threshold.txt"
LOG_FILE="$LOGS_DIR/backfill-$(date -u +%Y-%m-%d).log"

PYTHON="${PYTHON:-python3}"
BACKFILL_SCRIPT="$PIPELINE_DIR/backfill_thin_articles.py"

MIN_INTERVAL_SECS=14400   # 4 hours
BATCH_SIZE=10
THRESHOLDS=(50 100 150 200)   # word count tiers, escalate when tier cleared

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$LOGS_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ── Discord notification ──────────────────────────────────────────────────────
notify_discord() {
    local msg="$1"
    if [[ -z "${DISCORD_PIPELINE_WEBHOOK:-}" ]]; then
        log "DISCORD_PIPELINE_WEBHOOK not set — skipping notification"
        return 0
    fi
    curl -s -X POST "$DISCORD_PIPELINE_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{\"content\": $(printf '%s' "$msg" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
        > /dev/null || log "WARNING: Discord notification failed"
}

# ── Guardrail: pipeline lock ──────────────────────────────────────────────────
if [[ -f "$LOCKFILE" ]]; then
    log "Pipeline lockfile present — skipping backfill (main pipeline running)"
    exit 0
fi

# ── Guardrail: minimum interval ───────────────────────────────────────────────
if [[ -f "$LAST_RUN_FILE" ]]; then
    LAST_RUN_TS=$(cat "$LAST_RUN_FILE" | tr -d '[:space:]')
    NOW_TS=$(date -u +%s)
    if [[ -n "$LAST_RUN_TS" ]]; then
        ELAPSED=$(( NOW_TS - LAST_RUN_TS ))
        if (( ELAPSED < MIN_INTERVAL_SECS )); then
            WAIT=$(( MIN_INTERVAL_SECS - ELAPSED ))
            log "Last backfill was ${ELAPSED}s ago — skipping (next eligible in ${WAIT}s)"
            exit 0
        fi
    fi
fi

# ── Determine current threshold (auto-escalate) ───────────────────────────────
CURRENT_THRESHOLD=50
if [[ -f "$THRESHOLD_FILE" ]]; then
    CURRENT_THRESHOLD=$(cat "$THRESHOLD_FILE" | tr -d '[:space:]')
fi

# Verify threshold is valid (one of the defined tiers)
VALID_THRESHOLD=0
for t in "${THRESHOLDS[@]}"; do
    if [[ "$CURRENT_THRESHOLD" == "$t" ]]; then
        VALID_THRESHOLD=1
        break
    fi
done
if [[ "$VALID_THRESHOLD" == "0" ]]; then
    log "WARNING: Invalid threshold '$CURRENT_THRESHOLD', resetting to 50"
    CURRENT_THRESHOLD=50
fi

log "Starting backfill: threshold=<${CURRENT_THRESHOLD}w, batch=${BATCH_SIZE}${DRY_RUN:+, DRY-RUN}"

# ── Run backfill ──────────────────────────────────────────────────────────────
DRY_FLAG=""
if (( DRY_RUN )); then
    DRY_FLAG="--dry-run"
fi

RESULT_JSON=""
RESULT_JSON=$(
    cd "$PIPELINE_DIR" && \
    $PYTHON backfill_thin_articles.py \
        --max-words "$CURRENT_THRESHOLD" \
        --batch "$BATCH_SIZE" \
        --json \
        $DRY_FLAG \
    | awk '/^__RESULT_JSON__/{found=1; next} found{print}' \
    || true
)

if [[ -z "$RESULT_JSON" ]]; then
    log "ERROR: No result JSON from backfill script"
    notify_discord "⚠️ Backfill cron: script returned no output — check $LOG_FILE"
    exit 1
fi

log "Result JSON: $RESULT_JSON"

# ── Parse result ──────────────────────────────────────────────────────────────
EXPANDED=$(echo "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['expanded'])")
SKIPPED=$(echo  "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['skipped'])")
FAILED=$(echo   "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['failed'])")
AVG_BEFORE=$(echo "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['avg_before'])")
AVG_AFTER=$(echo  "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['avg_after'])")
REMAINING=$(echo  "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['remaining'])")
TOTAL_THIN=$(echo "$RESULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_thin'])")

log "Expanded: $EXPANDED, Skipped: $SKIPPED, Failed: $FAILED, Remaining: $REMAINING"

# ── Update last-run timestamp (skip if dry-run) ───────────────────────────────
if (( ! DRY_RUN )); then
    date -u +%s > "$LAST_RUN_FILE"
fi

# ── Append to progress log ────────────────────────────────────────────────────
NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROGRESS_ENTRY=$(python3 -c "
import json, sys
entry = {
    'date': '$NOW_ISO',
    'threshold': $CURRENT_THRESHOLD,
    'batch_size': $BATCH_SIZE,
    'expanded': $EXPANDED,
    'skipped': $SKIPPED,
    'failed': $FAILED,
    'avg_before': $AVG_BEFORE,
    'avg_after': $AVG_AFTER,
    'remaining': $REMAINING,
    'dry_run': bool($DRY_RUN),
}
print(json.dumps(entry))
")

if [[ -f "$PROGRESS_FILE" ]]; then
    # Append entry to existing JSON array
    python3 -c "
import json
with open('$PROGRESS_FILE') as f:
    data = json.load(f)
data.append($PROGRESS_ENTRY)
with open('$PROGRESS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
"
else
    echo "[$PROGRESS_ENTRY]" > "$PROGRESS_FILE"
fi

# ── Auto-escalate threshold when tier is cleared ──────────────────────────────
if (( ! DRY_RUN && REMAINING == 0 )); then
    NEXT_THRESHOLD=""
    FOUND_CURRENT=0
    for t in "${THRESHOLDS[@]}"; do
        if (( FOUND_CURRENT )); then
            NEXT_THRESHOLD="$t"
            break
        fi
        if [[ "$t" == "$CURRENT_THRESHOLD" ]]; then
            FOUND_CURRENT=1
        fi
    done

    if [[ -n "$NEXT_THRESHOLD" ]]; then
        log "Tier <${CURRENT_THRESHOLD}w complete — escalating to <${NEXT_THRESHOLD}w"
        echo "$NEXT_THRESHOLD" > "$THRESHOLD_FILE"
        notify_discord "📈 Backfill tier complete: all articles <${CURRENT_THRESHOLD}w expanded. Escalating to <${NEXT_THRESHOLD}w threshold."
    else
        log "All backfill tiers complete (max threshold ${CURRENT_THRESHOLD}w reached)"
        notify_discord "✅ Backfill complete: all thin article tiers processed (up to ${CURRENT_THRESHOLD}w)."
    fi
else
    # Persist current threshold
    echo "$CURRENT_THRESHOLD" > "$THRESHOLD_FILE"
fi

# ── Discord summary ───────────────────────────────────────────────────────────
if (( DRY_RUN )); then
    DISCORD_MSG="🔍 Backfill dry-run (<${CURRENT_THRESHOLD}w): would process ${BATCH_SIZE} articles. ${TOTAL_THIN} thin articles found."
elif (( EXPANDED > 0 )); then
    DISCORD_MSG="📝 Backfill: ${EXPANDED}/${BATCH_SIZE} expanded, avg ${AVG_BEFORE}w → ${AVG_AFTER}w (threshold <${CURRENT_THRESHOLD}w, ${REMAINING} remaining)"
    if (( FAILED > 0 )); then
        DISCORD_MSG="${DISCORD_MSG}, ${FAILED} failed"
    fi
else
    DISCORD_MSG="📝 Backfill: nothing expanded (${SKIPPED} skipped, ${FAILED} failed, ${REMAINING} remaining <${CURRENT_THRESHOLD}w)"
fi

log "Discord: $DISCORD_MSG"
notify_discord "$DISCORD_MSG"

log "Backfill cron complete."
exit 0
