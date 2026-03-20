#!/bin/bash
# metrics_cron.sh — Daily metrics report to Discord #metrics
# Run once per day, e.g. 08:00 Helsinki time (06:00 UTC)
#
# To install as host cron (run on host):
#   (crontab -l 2>/dev/null; echo "0 6 * * * /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/metrics_cron.sh >> /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/logs/metrics_cron.log 2>&1") | crontab -
#
# Or add to OpenClaw cron config as a shell job targeting this script.

PROJECT_DIR="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
PIPELINE_DIR="$PROJECT_DIR/pipeline"

cd "$PROJECT_DIR"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

echo "=== Metrics report at $(date -u) ==="
python3 "$PIPELINE_DIR/metrics_report.py" --days 1
echo "=== Done ==="
