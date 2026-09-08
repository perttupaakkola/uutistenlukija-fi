#!/bin/bash
# Auto-publish pipeline: scan → rewrite → publish → build → commit → push
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
LOG_FILE="$PIPELINE_DIR/logs/auto_publish_$(date -u +%Y%m%d_%H%M%S).log"

cd "$PROJECT_DIR"

# Shared admission precedes environment loading and all producer work.
source "$PIPELINE_DIR/legacy_publish_git.sh"
legacy_admit
mkdir -p "$PIPELINE_DIR/logs"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

PIPELINE_START_TS=$(date +%s)
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

# Refuse advancement without overwriting generated or concurrent work.
legacy_postwork_check

# Generate health + pipeline status BEFORE git add so they get committed and deployed to Cloudflare
python3 "$PIPELINE_DIR/generate_health.py" 2>&1 | tee -a "$LOG_FILE" || echo "[health] generation failed (non-fatal)" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/generate_pipeline_status.py" 2>&1 | tee -a "$LOG_FILE" || echo "[pipeline_status] generation failed (non-fatal)" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/generate_search_index.py" 2>&1 | tee -a "$LOG_FILE" || echo "[search_index] generation failed (non-fatal)" | tee -a "$LOG_FILE"
python3 "$PROJECT_DIR/scripts/category_distribution.py" 2>&1 | tee -a "$LOG_FILE" || echo "[category_distribution] generation failed (non-fatal)" | tee -a "$LOG_FILE"

bash "$PROJECT_DIR/scripts/daily-snapshot.sh" 2>&1 | tee -a "$LOG_FILE" || echo "[snapshot] generation failed (non-fatal)" | tee -a "$LOG_FILE"
legacy_commit_and_push

echo "=== Auto-publish completed at $(date -u) ==="  | tee -a "$LOG_FILE"

# Update publish metrics (append this run's stats to publish-metrics.json)
python3 "$PIPELINE_DIR/update_publish_metrics.py" 2>&1 | tee -a "$LOG_FILE" || true

# Print metrics summary (last 7 days) to log
echo "[metrics] 7-day summary:" | tee -a "$LOG_FILE"
python3 "$PIPELINE_DIR/metrics.py" --metrics-report --days 7 2>&1 | tee -a "$LOG_FILE" || true

PIPELINE_ELAPSED=$(( $(date +%s) - PIPELINE_START_TS ))
python3 "$PROJECT_DIR/scripts/pipeline_run_summary.py" \
  --articles "${ARTICLE_COUNT:-0}" --elapsed "$PIPELINE_ELAPSED" \
  2>&1 | tee -a "$LOG_FILE" || true

# Cleanup old logs (keep last 50)
ls -t "$PIPELINE_DIR/logs/auto_publish_"*.log 2>/dev/null | tail -n +51 | xargs rm -f 2>/dev/null || true
