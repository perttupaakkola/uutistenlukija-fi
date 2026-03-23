#!/bin/bash
# Firehose cron runner — called every 10 minutes
# Polls Firehose, rewrites new articles, publishes (no Hugo build — build runs separately).
#
# Crontab entry (run as user, from host):
#   */10 * * * * /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/firehose_cron.sh >> /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/logs/firehose_cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/firehose_$(date -u +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "" | tee -a "$LOG_FILE"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === firehose_cron starting ===" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"

# Load .env if present
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Activate venv if present
if [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# Run pipeline in Firehose-only mode (poll → rewrite → publish, skip RSS + Hugo build)
python3 "$SCRIPT_DIR/run_pipeline.py" --firehose-only --quick 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}

if [ "$PIPELINE_EXIT" -ne 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pipeline exited with code $PIPELINE_EXIT" | tee -a "$LOG_FILE"
    exit 1
fi

# Commit and push if new content was added
cd "$PROJECT_DIR"
# CRITICAL: Reset index first to prevent bridge-staged files (layouts/, docs/, etc.)
# from being accidentally swept into firehose commits. See 0dfb184 revert.
git reset HEAD -- . 2>/dev/null || true
git add content/ pipeline/.pipeline_lock pipeline/metrics.jsonl 2>/dev/null || true
if git diff --cached --quiet; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] No new content to commit" | tee -a "$LOG_FILE"
else
    ARTICLE_COUNT=$(git diff --cached --name-only 2>/dev/null | grep -c "^content/posts/" || echo "0")
    git commit -m "auto(firehose): ${ARTICLE_COUNT} articles $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>&1 | tee -a "$LOG_FILE"
    git push origin main 2>&1 | tee -a "$LOG_FILE"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Committed and pushed ${ARTICLE_COUNT} firehose articles" | tee -a "$LOG_FILE"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === firehose_cron done ===" | tee -a "$LOG_FILE"

# Cleanup old logs (keep last 30 daily log files)
ls -t "$LOG_DIR/firehose_"*.log 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null || true
