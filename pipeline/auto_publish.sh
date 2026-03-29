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

# Pre-flight: validate imports before running the real pipeline
echo "[0/3] Pre-flight import check..." | tee -a "$LOG_FILE"
cd "$PIPELINE_DIR"
if ! python3 run_pipeline.py --dry-run 2>&1 | tee -a "$LOG_FILE"; then
  echo "❌ Pre-flight failed — broken imports. Pipeline NOT started." | tee -a "$LOG_FILE"
  # Alert Discord if webhook is set
  WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"
  if [ -n "$WEBHOOK" ]; then
    MSG="❌ **Pipeline pre-flight failed** — broken imports detected. Pipeline did NOT run. Check logs: $LOG_FILE"
    python3 -c "import json,urllib.request; urllib.request.urlopen(urllib.request.Request('$WEBHOOK', data=json.dumps({'content':'$MSG'}).encode(), headers={'Content-Type':'application/json'}, method='POST'), timeout=5)" 2>/dev/null || true
  fi
  exit 1
fi

# Run pipeline (scan + rewrite + publish + build)
echo "[1/3] Running pipeline..." | tee -a "$LOG_FILE"
python3 run_pipeline.py --quick --max-articles 3 --dedup-window 48 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}

if [ "$PIPELINE_EXIT" -ne 0 ]; then
  echo "Pipeline failed with exit code $PIPELINE_EXIT" | tee -a "$LOG_FILE"
  exit 1
fi

# Commit and push if there are changes
cd "$PROJECT_DIR"
echo "[2/3] Checking for changes..." | tee -a "$LOG_FILE"

# Pull latest pipeline code from origin so scanner.py and scripts stay current.
# Without this, the host checkout drifts from GitHub main and new feeds/fixes
# never reach the running pipeline. --rebase keeps history linear.
# Non-fatal: if pull fails (offline, conflict), we proceed with current code.
git pull --rebase origin main 2>&1 | tee -a "$LOG_FILE" || echo "[git-pull] pull failed (non-fatal, continuing with current code)" | tee -a "$LOG_FILE"

# CRITICAL: Reset index + restore layout/script files to HEAD before staging.
# Bridge syncs from Alex's sessions can leave modified layout files or scripts
# with wrong permissions in the working tree. This ensures:
#   1. No layout/theme/script changes leak into auto-publish commits
#   2. .sh files retain their execute bits (git checkout restores committed mode)
git reset HEAD -- . 2>/dev/null || true
git checkout HEAD -- layouts/ themes/ scripts/ pipeline/auto_publish.sh pipeline/firehose_cron.sh pipeline/scanner.py 2>/dev/null || true

# Generate health + pipeline status BEFORE git add so they get committed and deployed to Cloudflare
python3 "$PIPELINE_DIR/generate_health.py" 2>&1 | tee -a "$LOG_FILE" || echo "[health] generation failed (non-fatal)" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/generate_pipeline_status.py" 2>&1 | tee -a "$LOG_FILE" || echo "[pipeline_status] generation failed (non-fatal)" | tee -a "$LOG_FILE"
python3 "$PROJECT_DIR/scripts/category_distribution.py" 2>&1 | tee -a "$LOG_FILE" || echo "[category_distribution] generation failed (non-fatal)" | tee -a "$LOG_FILE"

git add content/ public/ static/api/ static/metrics/ pipeline/metrics.jsonl pipeline/.pipeline_lock 2>/dev/null || true
if git diff --cached --quiet; then
  echo "No new content to push." | tee -a "$LOG_FILE"
else
  ARTICLE_COUNT=$(git diff --cached --name-only | grep -c "^content/posts/" 2>/dev/null; true)
  git commit -m "Auto-publish: ${ARTICLE_COUNT} new articles ($(date -u +%Y-%m-%d %H:%M UTC))" 2>&1 | tee -a "$LOG_FILE"
  
  echo "[3/3] Pushing to GitHub..." | tee -a "$LOG_FILE"
  git push origin main 2>&1 | tee -a "$LOG_FILE"
  echo "Deployed ${ARTICLE_COUNT} new articles." | tee -a "$LOG_FILE"
fi
bash "$PROJECT_DIR/scripts/daily-snapshot.sh" 2>&1 | tee -a "$LOG_FILE" || echo "[snapshot] generation failed (non-fatal)" | tee -a "$LOG_FILE"

echo "=== Auto-publish completed at $(date -u) ==="  | tee -a "$LOG_FILE"

# Update publish metrics (append this run's stats to publish-metrics.json)
python3 "$PIPELINE_DIR/update_publish_metrics.py" 2>&1 | tee -a "$LOG_FILE" || true

# Print metrics summary (last 7 days) to log
echo "[metrics] 7-day summary:" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/metrics.py" --metrics-report --days 7 2>&1 | tee -a "$LOG_FILE" || true

# Cleanup old logs (keep last 50)
ls -t "$PIPELINE_DIR/logs/auto_publish_"*.log 2>/dev/null | tail -n +51 | xargs rm -f 2>/dev/null || true
