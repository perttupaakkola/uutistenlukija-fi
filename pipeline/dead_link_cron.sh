#!/usr/bin/env bash
# dead_link_cron.sh — Weekly dead link crawl, posts results to #metrics
# Cron example (every Sunday 07:00 UTC):
#   0 7 * * 0 /path/to/pipeline/dead_link_cron.sh >> /path/to/logs/dead-link-cron.log 2>&1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

cd "$SCRIPT_DIR"
# Limit to 300 pages to stay under ~5min runtime
python3 dead_link_check.py --max 300
