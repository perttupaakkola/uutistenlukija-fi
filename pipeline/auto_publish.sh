#!/bin/bash
# Auto-publish pipeline: scan → rewrite → publish → build → commit → push
set -euo pipefail

PROJECT_DIR="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
LOG_FILE="$PIPELINE_DIR/logs/auto_publish_$(date -u +%Y%m%d_%H%M%S).log"

cd "$PROJECT_DIR"

# ── Deduplication lockfile guard ─────────────────────────────────────────────
LOCK_FILE="$PIPELINE_DIR/.pipeline_lock"

STALE_LOCK_MINS=30

if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(awk 'NR==1' "$LOCK_FILE")
    LOCK_TS=$(awk 'NR==2' "$LOCK_FILE")
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        # Check lock age — kill if stuck longer than STALE_LOCK_MINS
        LOCK_AGE_SECS=$(python3 -c "
from datetime import datetime, timezone
import sys
try:
    ts = datetime.fromisoformat('" + $LOCK_TS + "'.replace('Z','+00:00'))
    print(int((datetime.now(timezone.utc) - ts).total_seconds()))
except: print(0)
" 2>/dev/null || echo 0)
        STALE_LOCK_SECS=$(( STALE_LOCK_MINS * 60 ))
        if (( LOCK_AGE_SECS > STALE_LOCK_SECS )); then
            LOCK_AGE_MIN=$(( LOCK_AGE_SECS / 60 ))
            echo "[auto_publish] STUCK PIPELINE: PID $LOCK_PID running ${LOCK_AGE_MIN}min (limit: ${STALE_LOCK_MINS}min). Killing."
            kill -TERM "$LOCK_PID" 2>/dev/null || true
            sleep 2
            kill -KILL "$LOCK_PID" 2>/dev/null || true
            rm -f "$LOCK_FILE"
            # Alert Discord
            WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"
            if [ -n "$WEBHOOK" ]; then
                MSG="⚠️ **Stuck pipeline killed** — PID $LOCK_PID was running for ${LOCK_AGE_MIN} minutes (limit: ${STALE_LOCK_MINS}min). Lock removed, new run starting."
                python3 -c "import json,urllib.request; urllib.request.urlopen(urllib.request.Request('$WEBHOOK', data=json.dumps({'content':'$MSG'}).encode(), headers={'Content-Type':'application/json'}, method='POST'), timeout=5)" 2>/dev/null || true
            fi
        else
            echo "[auto_publish] Pipeline already running (PID $LOCK_PID, started $LOCK_TS, age ${LOCK_AGE_SECS}s) — exiting."
            exit 0
        fi
    else
        echo "[auto_publish] WARNING: Stale lock (PID $LOCK_PID no longer running, started $LOCK_TS). Removing."
        rm -f "$LOCK_FILE"
    fi
fi

# Write lock and register cleanup on exit
printf '%s
%s
' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

echo "=== Auto-publish started at $(date -u) ===" | tee -a "$LOG_FILE"

# Run pipeline (scan + rewrite + publish + build)
echo "[1/3] Running pipeline..." | tee -a "$LOG_FILE"
cd "$PIPELINE_DIR"
python3 run_pipeline.py --quick --max-articles 1 --dedup-window 48 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}

if [ "$PIPELINE_EXIT" -ne 0 ]; then
  echo "Pipeline failed with exit code $PIPELINE_EXIT" | tee -a "$LOG_FILE"
  exit 1
fi

# Commit and push if there are changes
cd "$PROJECT_DIR"
echo "[2/3] Checking for changes..." | tee -a "$LOG_FILE"

git add content/ public/ 2>/dev/null || true
if git diff --cached --quiet; then
  echo "No new content to push." | tee -a "$LOG_FILE"
else
  ARTICLE_COUNT=$(git diff --cached --name-only | grep -c "^content/posts/" || echo "0")
  git commit -m "Auto-publish: ${ARTICLE_COUNT} new articles ($(date -u +%Y-%m-%d %H:%M UTC))" 2>&1 | tee -a "$LOG_FILE"
  
  echo "[3/3] Pushing to GitHub..." | tee -a "$LOG_FILE"
  git push origin main 2>&1 | tee -a "$LOG_FILE"
  echo "Deployed ${ARTICLE_COUNT} new articles." | tee -a "$LOG_FILE"
fi

# Regenerate health endpoint + metrics snapshot
python3 "$PIPELINE_DIR/generate_health.py" 2>&1 | tee -a "$LOG_FILE" || echo "[health] generation failed (non-fatal)" | tee -a "$LOG_FILE"
bash "$PROJECT_DIR/scripts/daily-snapshot.sh" 2>&1 | tee -a "$LOG_FILE" || echo "[snapshot] generation failed (non-fatal)" | tee -a "$LOG_FILE" 2>&1 | tee -a "$LOG_FILE" || echo "[health] generation failed (non-fatal)" | tee -a "$LOG_FILE"

echo "=== Auto-publish completed at $(date -u) ==="  | tee -a "$LOG_FILE"

# Update publish metrics (append this run's stats to publish-metrics.json)
python3 "$PIPELINE_DIR/update_publish_metrics.py" 2>&1 | tee -a "$LOG_FILE" || true

# Print metrics summary (last 7 days) to log
echo "[metrics] 7-day summary:" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/metrics.py" --metrics-report --days 7 2>&1 | tee -a "$LOG_FILE" || true

# Cleanup old logs (keep last 50)
ls -t "$PIPELINE_DIR/logs/auto_publish_"*.log 2>/dev/null | tail -n +51 | xargs rm -f 2>/dev/null || true
