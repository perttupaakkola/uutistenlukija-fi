#!/usr/bin/env bash
# lighthouse_cron.sh — Daily Lighthouse run, posts scores to #metrics
# Cron example (daily 08:00 UTC):
#   0 8 * * * /path/to/pipeline/lighthouse_cron.sh >> /path/to/logs/lighthouse-cron.log 2>&1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env from pipeline dir
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

cd "$SCRIPT_DIR"
python3 lighthouse_check.py
