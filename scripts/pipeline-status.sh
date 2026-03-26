#!/usr/bin/env bash
# pipeline-status.sh — Quick pipeline health snapshot for ops use
# Shows: last run time, article counts, recent errors, cron status, disk
#
# Usage:
#   bash scripts/pipeline-status.sh          # human-readable
#   bash scripts/pipeline-status.sh --json   # machine-readable

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIPELINE="$PROJECT_DIR/pipeline"
LOGS="$PIPELINE/logs"
CONTENT="$PROJECT_DIR/content/posts"
JSON_MODE=false
[[ "${1:-}" == "--json" ]] && JSON_MODE=true

# ── Gather data ───────────────────────────────────────────────────────────────

# Last pipeline run time (from most recent auto_publish log)
LAST_LOG=$(ls -t "$LOGS"/auto_publish_*.log 2>/dev/null | head -1 || true)
if [[ -n "$LAST_LOG" ]]; then
  LAST_RUN_FILE=$(basename "$LAST_LOG")
  # Extract timestamp from filename: auto_publish_YYYYMMDD_HHMMSS.log
  TS_RAW=$(echo "$LAST_RUN_FILE" | grep -oP '\d{8}_\d{6}' || echo "unknown")
  if [[ "$TS_RAW" != "unknown" ]]; then
    LAST_RUN=$(date -u -d "${TS_RAW:0:8} ${TS_RAW:9:2}:${TS_RAW:11:2}:${TS_RAW:13:2}" '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo "$TS_RAW")
  else
    LAST_RUN="unknown"
  fi
  LAST_LOG_LINES=$(wc -l < "$LAST_LOG")
  LAST_LOG_ERRORS=$(grep -c -iE "error|exception|traceback|failed|quota" "$LAST_LOG" 2>/dev/null || echo 0)
else
  LAST_RUN="no logs found"
  LAST_LOG_LINES=0
  LAST_LOG_ERRORS=0
fi

# Article counts
TOTAL_ARTICLES=$(ls "$CONTENT"/*.md 2>/dev/null | wc -l || echo 0)
TODAY=$(date -u '+%Y-%m-%d')
TODAY_ARTICLES=$(find "$CONTENT" -maxdepth 1 -name "*${TODAY}*.md" 2>/dev/null | wc -l)
YESTERDAY=$(date -u -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || date -u -v-1d '+%Y-%m-%d' 2>/dev/null || echo "")
YESTERDAY_ARTICLES=0
[[ -n "$YESTERDAY" ]] && YESTERDAY_ARTICLES=$(find "$CONTENT" -maxdepth 1 -name "*${YESTERDAY}*.md" 2>/dev/null | wc -l)

# Health JSON
HEALTH_FILE="$PROJECT_DIR/static/api/health.json"
HEALTH_STATUS="unknown"
HEALTH_TS="unknown"
if [[ -f "$HEALTH_FILE" ]]; then
  HEALTH_STATUS=$(python3 -c "import json,sys; d=json.load(open('$HEALTH_FILE')); print(d.get('status','unknown'))" 2>/dev/null || echo "parse_error")
  HEALTH_TS=$(python3 -c "import json,sys; d=json.load(open('$HEALTH_FILE')); print(d.get('updated','unknown'))" 2>/dev/null || echo "unknown")
fi

# Pipeline lock
LOCK_FILE="$PIPELINE/.pipeline_lock"
LOCK_STATUS="none"
LOCK_AGE=0
if [[ -f "$LOCK_FILE" ]]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE") ))
  if (( LOCK_AGE > 1800 )); then
    LOCK_STATUS="STALE (${LOCK_AGE}s old)"
  else
    LOCK_STATUS="active (${LOCK_AGE}s old)"
  fi
fi

# Disk space
DISK_AVAIL=$(df -BM "$PROJECT_DIR" | awk 'NR==2{gsub("M","",$4); print $4}' 2>/dev/null || echo 0)
DISK_PCT=$(df "$PROJECT_DIR" | awk 'NR==2{print $5}' 2>/dev/null || echo "?")

# Cron running?
PIPELINE_CRON=$(crontab -l 2>/dev/null | grep -E "(auto_publish|pipeline-watchdog)" | grep -v "^#" | wc -l || echo 0)

# Recent errors in cron.log (last 100 lines)
RECENT_ERRORS=0
if [[ -f "$LOGS/cron.log" ]]; then
  RECENT_ERRORS=$(tail -100 "$LOGS/cron.log" | grep -c -iE "error|exception|traceback|quota|failed" 2>/dev/null || echo 0)
fi

# ── Output ─────────────────────────────────────────────────────────────────────

if $JSON_MODE; then
  python3 - <<PYEOF
import json
print(json.dumps({
  "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "health_status": "$HEALTH_STATUS",
  "health_updated": "$HEALTH_TS",
  "last_pipeline_run": "$LAST_RUN",
  "last_log_errors": $LAST_LOG_ERRORS,
  "articles": {
    "total": $TOTAL_ARTICLES,
    "today": $TODAY_ARTICLES,
    "yesterday": $YESTERDAY_ARTICLES
  },
  "lock": "$LOCK_STATUS",
  "disk_mb_free": $DISK_AVAIL,
  "disk_pct_used": "$DISK_PCT",
  "pipeline_crons": $PIPELINE_CRON,
  "recent_cron_errors": $RECENT_ERRORS
}, indent=2))
PYEOF
else
  echo "══════════════════════════════════════════════════"
  echo "  Pipeline Status — $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "══════════════════════════════════════════════════"
  echo ""
  echo "  Health API    : $HEALTH_STATUS (updated: $HEALTH_TS)"
  echo "  Last run      : $LAST_RUN"
  echo "  Errors in run : $LAST_LOG_ERRORS"
  echo ""
  echo "  Articles today     : $TODAY_ARTICLES"
  echo "  Articles yesterday : $YESTERDAY_ARTICLES"
  echo "  Total articles     : $TOTAL_ARTICLES"
  echo ""
  echo "  Pipeline lock : $LOCK_STATUS"
  echo "  Pipeline crons: $PIPELINE_CRON active"
  echo "  Disk free     : ${DISK_AVAIL}MB ($DISK_PCT used)"
  echo "  Recent errors : $RECENT_ERRORS (last 100 cron log lines)"
  echo ""
  if (( LAST_LOG_ERRORS > 0 || RECENT_ERRORS > 5 )); then
    echo "  ⚠️  Issues detected — check logs"
  else
    echo "  ✅ Pipeline looks healthy"
  fi
fi
