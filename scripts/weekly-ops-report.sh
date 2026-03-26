#!/usr/bin/env bash
# weekly-ops-report.sh — Weekly operational summary for uutistenlukija pipeline
# Covers: article throughput, pipeline failures, top sources, description coverage
# Meant to be run manually or via cron on Mondays, posts to Discord via webhook
#
# Usage:
#   bash scripts/weekly-ops-report.sh              # print to stdout
#   bash scripts/weekly-ops-report.sh --post        # also post to Discord #operations
#   bash scripts/weekly-ops-report.sh --post --quiet  # post only, no stdout

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIPELINE="$PROJECT_DIR/pipeline"
LOGS="$PIPELINE/logs"
CONTENT="$PROJECT_DIR/content/posts"

POST_TO_DISCORD=false
QUIET=false
for arg in "$@"; do
  [[ "$arg" == "--post" ]] && POST_TO_DISCORD=true
  [[ "$arg" == "--quiet" ]] && QUIET=true
done

# ── Date range: last 7 days ───────────────────────────────────────────────────
REPORT_DATE=$(date -u '+%Y-%m-%d')
WEEK_START=$(date -u -d '7 days ago' '+%Y-%m-%d' 2>/dev/null || date -u -v-7d '+%Y-%m-%d')

# ── Article stats ─────────────────────────────────────────────────────────────
TOTAL=$(ls "$CONTENT"/*.md 2>/dev/null | wc -l || echo 0)

# Count articles published in last 7 days by checking filename prefix
WEEK_COUNT=0
for f in "$CONTENT"/*.md; do
  [[ -f "$f" ]] || continue
  fname=$(basename "$f")
  fdate="${fname:0:10}"
  if [[ "$fdate" > "$WEEK_START" ]] || [[ "$fdate" == "$WEEK_START" ]]; then
    (( WEEK_COUNT++ )) || true
  fi
done

# Articles per day this week
DAILY_BREAKDOWN=""
for i in 6 5 4 3 2 1 0; do
  D=$(date -u -d "${i} days ago" '+%Y-%m-%d' 2>/dev/null || date -u -v"-${i}d" '+%Y-%m-%d')
  COUNT=$(find "$CONTENT" -maxdepth 1 -name "${D}*.md" 2>/dev/null | wc -l)
  DOW=$(date -u -d "$D" '+%a' 2>/dev/null || date -u -j -f '%Y-%m-%d' "$D" '+%a' 2>/dev/null || echo "")
  DAILY_BREAKDOWN="${DAILY_BREAKDOWN}  ${D} (${DOW}): ${COUNT}\n"
done

# ── Pipeline failure count ────────────────────────────────────────────────────
FAILURE_COUNT=0
if [[ -f "$LOGS/pipeline-failures.log" ]]; then
  FAILURE_COUNT=$(wc -l < "$LOGS/pipeline-failures.log" 2>/dev/null || echo 0)
fi

# ── Top sources (from filenames — source often in slug) ──────────────────────
TOP_SOURCES=$(python3 - <<PYEOF 2>/dev/null || echo "  (unavailable)"
import os, re
from pathlib import Path
from collections import Counter

CONTENT = Path("$CONTENT")
# Extract source hint from slug patterns: date-source-slug.md
# Common patterns: yle, hs, is, kauppalehti, ts, iltasanomat, etc.
SOURCES = ["yle", "hs", "helsinginSanomat", "kauppalehti", "is", "iltasanomat",
           "ts", "bbc", "reuters", "ap", "spiegel", "guardian", "aftonbladet"]

import json
files = list(CONTENT.glob("*.md"))
week_start = "$WEEK_START"
week_files = [f for f in files if f.name[:10] >= week_start]

source_counts = Counter()
for f in week_files:
    try:
        text = f.read_text(encoding="utf-8")
        # Check front matter for source field
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end > 0:
                fm = text[3:end]
                for line in fm.splitlines():
                    if line.startswith("source:") or line.startswith("feed_source:"):
                        _, _, v = line.partition(":")
                        src = v.strip().strip('"').split("/")[2] if "/" in v else v.strip().strip('"')
                        # Clean to domain
                        src = re.sub(r'^www\.', '', src)
                        source_counts[src] += 1
                        break
    except Exception:
        pass

if source_counts:
    for src, cnt in source_counts.most_common(5):
        print(f"  {src}: {cnt}")
else:
    print("  (no source metadata found)")
PYEOF
)

# ── Description coverage ─────────────────────────────────────────────────────
DESC_COUNT=$(grep -l "^description:" "$CONTENT"/*.md 2>/dev/null | wc -l || echo 0)
NO_DESC=$(( TOTAL - DESC_COUNT ))

# ── Disk usage ────────────────────────────────────────────────────────────────
DISK_FREE=$(df -BM "$PROJECT_DIR" | awk 'NR==2{gsub("M","",$4); print $4}')
DISK_PCT=$(df "$PROJECT_DIR" | awk 'NR==2{print $5}')

# ── Format report ─────────────────────────────────────────────────────────────
REPORT="⚙️ **Weekly Ops Report** — week ending ${REPORT_DATE}

**📰 Article throughput**
• This week: ${WEEK_COUNT} articles published
• Total corpus: ${TOTAL}
• Daily breakdown:
$(printf "$DAILY_BREAKDOWN")
**🔧 Pipeline health**
• Failure log entries: ${FAILURE_COUNT}
• Description coverage: ${DESC_COUNT}/${TOTAL} (${NO_DESC} missing)

**📡 Top sources this week**
${TOP_SOURCES}

**💾 Disk**
• Free: ${DISK_FREE}MB (${DISK_PCT} used)"

if ! $QUIET; then
  echo "$REPORT"
fi

if $POST_TO_DISCORD; then
  # Load webhook from env or pipeline/.env
  if [[ -z "${DISCORD_PIPELINE_WEBHOOK:-}" ]] && [[ -f "$PIPELINE/.env" ]]; then
    source "$PIPELINE/.env" 2>/dev/null || true
  fi

  WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-${DISCORD_WEBHOOK_OPS:-}}"
  if [[ -z "$WEBHOOK" ]]; then
    echo "ERROR: DISCORD_PIPELINE_WEBHOOK or DISCORD_WEBHOOK_OPS not set" >&2
    exit 1
  fi

  # Escape for JSON
  PAYLOAD=$(python3 -c "
import json, sys
msg = sys.stdin.read()
print(json.dumps({'content': msg}))
" <<< "$REPORT")

  curl -sf -X POST -H 'Content-Type: application/json' -d "$PAYLOAD" "$WEBHOOK" && \
    echo "Posted to Discord ✅" || echo "Discord post failed ❌"
fi
