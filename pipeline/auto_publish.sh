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

# Regenerate health endpoint
python3 "$PIPELINE_DIR/generate_health.py" 2>&1 | tee -a "$LOG_FILE" || echo "[health] generation failed (non-fatal)" | tee -a "$LOG_FILE"

echo "=== Auto-publish completed at $(date -u) ==="  | tee -a "$LOG_FILE"

# Update publish metrics (append this run's stats to publish-metrics.json)
python3 "$PIPELINE_DIR/update_publish_metrics.py" 2>&1 | tee -a "$LOG_FILE" || true

# Print metrics summary (last 7 days) to log
echo "[metrics] 7-day summary:" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/metrics.py" --metrics-report --days 7 2>&1 | tee -a "$LOG_FILE" || true

# Cleanup old logs (keep last 50)
ls -t "$PIPELINE_DIR/logs/auto_publish_"*.log 2>/dev/null | tail -n +51 | xargs rm -f 2>/dev/null || true
