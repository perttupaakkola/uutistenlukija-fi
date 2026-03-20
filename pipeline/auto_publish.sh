#!/bin/bash
# Auto-publish pipeline: scan → rewrite → publish → build → commit → push
set -euo pipefail

PROJECT_DIR="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
LOG_FILE="$PIPELINE_DIR/logs/auto_publish_$(date -u +%Y%m%d_%H%M%S).log"

cd "$PROJECT_DIR"

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
python3 run_pipeline.py 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}

if [ "$PIPELINE_EXIT" -ne 0 ]; then
  echo "Pipeline failed with exit code $PIPELINE_EXIT" | tee -a "$LOG_FILE"
  # Send Discord alert with last 20 lines of log
  TAIL=$(tail -20 "$LOG_FILE" 2>/dev/null || echo "(log unavailable)")
  python3 - <<PYEOF
import sys
sys.path.insert(0, "$PIPELINE_DIR")
from health_check import notify_discord_failure
notify_discord_failure("run_pipeline", """$TAIL""", "auto_publish.sh exit code $PIPELINE_EXIT")
PYEOF
  exit 1
fi

# Stage new content, then run pre-publish quality gate
cd "$PROJECT_DIR"
echo "[2/4] Checking for changes..." | tee -a "$LOG_FILE"

git add content/ public/ 2>/dev/null || true
if git diff --cached --quiet; then
  echo "No new content to push." | tee -a "$LOG_FILE"
else
  # Pre-publish gate: auto-fix descriptions, reject articles missing image or too thin
  # Exit code 1 = some articles rejected (un-staged); remaining good articles still proceed
  echo "[3/4] Running pre-publish quality gate..." | tee -a "$LOG_FILE"
  cd "$PIPELINE_DIR"
  python3 pre_publish_check.py 2>&1 | tee -a "$LOG_FILE"
  PRE_CHECK_EXIT=${PIPESTATUS[0]}
  cd "$PROJECT_DIR"

  if [ "$PRE_CHECK_EXIT" -ne 0 ]; then
    echo "[pre-publish] Some articles were rejected — proceeding with remaining staged articles." | tee -a "$LOG_FILE"
  fi

  # Re-check if anything is still staged after the gate
  if git diff --cached --quiet; then
    echo "No articles passed quality gate. Nothing to deploy." | tee -a "$LOG_FILE"
  else
    ARTICLE_COUNT=$(git diff --cached --name-only | grep -c "^content/posts/" || echo "0")
    REJECTED_COUNT=$(git diff --cached --name-only -- 'content/posts/' | wc -l)
    git commit -m "Auto-publish: ${ARTICLE_COUNT} new articles ($(date -u '+%Y-%m-%d %H:%M UTC'))" 2>&1 | tee -a "$LOG_FILE"

    echo "[4/4] Pushing to GitHub..." | tee -a "$LOG_FILE"
    git push origin main 2>&1 | tee -a "$LOG_FILE"
    echo "Deployed ${ARTICLE_COUNT} new articles." | tee -a "$LOG_FILE"
  fi
fi

echo "=== Auto-publish completed at $(date -u) ===" | tee -a "$LOG_FILE"

# Cleanup old logs (keep last 50)
ls -t "$PIPELINE_DIR/logs/auto_publish_"*.log 2>/dev/null | tail -n +51 | xargs rm -f 2>/dev/null || true
