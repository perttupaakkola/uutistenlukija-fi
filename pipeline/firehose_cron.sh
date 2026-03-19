#!/bin/bash
# Firehose cron runner — called every 10 minutes
# Add to crontab: */10 * * * * /path/to/firehose_cron.sh >> /path/to/logs/firehose_cron.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/firehose_$(date -u +%Y%m%d).log"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] firehose_cron starting" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"

# Activate venv if present
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

python3 pipeline/firehose.py >> "$LOG_FILE" 2>&1

# Commit and push if new content was added
if git -C "$PROJECT_DIR" diff --quiet HEAD -- content/; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] No new content to commit" | tee -a "$LOG_FILE"
else
    git -C "$PROJECT_DIR" add content/
    git -C "$PROJECT_DIR" commit -m "auto: firehose articles $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git -C "$PROJECT_DIR" push origin main
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Committed and pushed new firehose articles" | tee -a "$LOG_FILE"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] firehose_cron done" | tee -a "$LOG_FILE"
