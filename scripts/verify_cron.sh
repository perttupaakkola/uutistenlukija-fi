#!/usr/bin/env bash
# verify_cron.sh — Compare expected crons (from CRON.md) against actual crontab.
# Reports: MATCH ✅ | MISSING ❌ | SCHEDULE MISMATCH ⚠️ | EXTRA ⚠️
#
# Usage:
#   bash scripts/verify_cron.sh
#   bash scripts/verify_cron.sh --json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
JSON_MODE=false

if [[ "${1:-}" == "--json" ]]; then
  JSON_MODE=true
fi

# Expected pipeline crons from CRON.md — "schedule|command_pattern|description"
declare -a EXPECTED=(
  "*/15 * * * *|pipeline-watchdog.sh|Main pipeline watchdog (every 15 min)"
  "*/85 * * * *|refresh-x-token.sh|X OAuth2 token refresh (every 85 min)"
  "30 7 * * *|seo_daily_dashboard.py|SEO daily dashboard (07:30 UTC)"
  "30 7,11,17,20 * * *|x_auto_poster.py|X auto-poster (4× daily)"
  "0 6 * * *|metrics_cron.sh|Daily metrics report (06:00 UTC)"
  "0 9 * * *|lighthouse_check.py|Lighthouse scores (09:00 UTC)"
  "0 7 * * 1|validate_articles.py|Weekly content quality (Mon 07:00 UTC)"
  "0 7 * * 0|dead_link_cron.sh|Weekly dead-link crawl (Sun 07:00 UTC)"
)

ACTUAL_CRONTAB=$(crontab -l 2>/dev/null || true)
PIPELINE_ACTUAL=$(echo "$ACTUAL_CRONTAB" | grep -v "^#" | grep -v "^$" | grep -v "^MAILTO" | \
  grep -E "(uutistenlukija|workspace/projects)" || true)

MATCH=()
MISSING=()
PARTIAL=()

for entry in "${EXPECTED[@]}"; do
  IFS='|' read -r schedule pattern description <<< "$entry"
  if echo "$PIPELINE_ACTUAL" | grep -q "$pattern"; then
    matched_line=$(echo "$PIPELINE_ACTUAL" | grep "$pattern" | head -1)
    if echo "$matched_line" | grep -q "^${schedule} "; then
      MATCH+=("MATCH | ${schedule} | ${description}")
    else
      actual_sched=$(echo "$matched_line" | awk '{print $1" "$2" "$3" "$4" "$5}')
      PARTIAL+=("SCHED_MISMATCH | expected: ${schedule} | actual: ${actual_sched} | ${description}")
    fi
  else
    MISSING+=("MISSING | ${schedule} | ${description}")
  fi
done

EXTRA=()
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  found=false
  for entry in "${EXPECTED[@]}"; do
    IFS='|' read -r _ pattern _ <<< "$entry"
    if echo "$line" | grep -q "$pattern"; then
      found=true; break
    fi
  done
  $found || EXTRA+=("EXTRA | $line")
done <<< "$PIPELINE_ACTUAL"

if ! $JSON_MODE; then
  echo "════════════════════════════════════════════════════════"
  echo "  Cron Verification — uutistenlukija pipeline"
  echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "════════════════════════════════════════════════════════"
  echo ""
  echo "── Expected (from CRON.md) ──────────────────────────"
  for m in "${MATCH[@]}";    do echo "  ✅ $m"; done
  for m in "${PARTIAL[@]}";  do echo "  ⚠️  $m"; done
  for m in "${MISSING[@]}";  do echo "  ❌ $m"; done
  echo ""
  echo "── Extra pipeline crons (installed but not in CRON.md) ─"
  if [[ ${#EXTRA[@]} -eq 0 ]]; then
    echo "  (none)"
  else
    for e in "${EXTRA[@]}"; do echo "  ⚠️  $e"; done
  fi
  echo ""
  echo "Summary: ${#MATCH[@]} matched | ${#PARTIAL[@]} schedule mismatch | ${#MISSING[@]} missing | ${#EXTRA[@]} extra"
fi
