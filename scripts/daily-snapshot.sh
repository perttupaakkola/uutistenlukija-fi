#!/usr/bin/env bash
# =============================================================================
# daily-snapshot.sh — writes static/metrics/snapshot.json
#
# Produces a lightweight JSON health snapshot accessible at:
#   https://uutistenlukija.fi/metrics/snapshot.json
#
# Fields:
#   articlesTotal          — total .md files in content/posts/
#   articlesPublishedToday — articles whose front-matter date is within last 24h
#   lastSuccessfulRun      — ISO timestamp of last successful pipeline run
#   pipelineErrorsToday    — count of pipeline errors in last 24h
#   uptimeSinceRestart     — seconds since host last booted (/proc/uptime)
#   generatedAt            — ISO timestamp of snapshot generation
#
# Usage: bash scripts/daily-snapshot.sh [--dry-run]
# Called by: pipeline/auto_publish.sh after each successful publish
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

OUT_FILE="$PROJECT_DIR/static/metrics/snapshot.json"

# Delegate all data gathering and JSON assembly to Python (avoids shell quoting issues)
snapshot=$(python3 - "$PROJECT_DIR" << 'PYEOF'
import json, sys, os, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

project_dir = Path(sys.argv[1])
content_dir = project_dir / "content" / "posts"
metrics_file = project_dir / "pipeline" / "logs" / "metrics.json"
now = datetime.now(timezone.utc)
cutoff_24h = now - timedelta(hours=24)

# 1. articlesTotal
articles = list(content_dir.glob("**/*.md")) if content_dir.exists() else []
articles_total = len(articles)

# 2. articlesPublishedToday — parse front-matter date fields
date_re = re.compile(r'^date\s*[:=]\s*["\']?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)', re.MULTILINE)
articles_today = 0
for art in articles:
    try:
        text = art.read_text(encoding="utf-8", errors="ignore")
        m = date_re.search(text)
        if not m:
            continue
        raw = m.group(1)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        elif "+" not in raw[10:] and raw.count("-") < 3:
            raw += "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt >= cutoff_24h:
            articles_today += 1
    except Exception:
        pass

# 3. lastSuccessfulRun  4. pipelineErrorsToday
last_ok = None
errors_today = 0
if metrics_file.exists():
    try:
        runs = json.loads(metrics_file.read_text(encoding="utf-8"))
        if isinstance(runs, list):
            for run in runs:
                ts_raw = run.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                except Exception:
                    continue
                if run.get("success"):
                    if last_ok is None or ts > last_ok:
                        last_ok = ts
                elif ts >= cutoff_24h:
                    errors_today += 1
    except Exception:
        pass

# 5. uptimeSinceRestart
uptime_secs = 0
try:
    uptime_secs = int(float(Path("/proc/uptime").read_text().split()[0]))
except Exception:
    pass

snapshot = {
    "articlesTotal": articles_total,
    "articlesPublishedToday": articles_today,
    "lastSuccessfulRun": last_ok.strftime("%Y-%m-%dT%H:%M:%SZ") if last_ok else None,
    "pipelineErrorsToday": errors_today,
    "uptimeSinceRestart": uptime_secs,
    "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
}
print(json.dumps(snapshot, indent=2))
PYEOF
)

# Validate
echo "$snapshot" | python3 -c "import json,sys; json.load(sys.stdin)" \
    || { echo "[daily-snapshot] ERROR: invalid JSON generated" >&2; exit 1; }

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[daily-snapshot] Dry run — would write to $OUT_FILE:"
    echo "$snapshot"
    exit 0
fi

mkdir -p "$(dirname "$OUT_FILE")"
echo "$snapshot" > "$OUT_FILE"

# Summary line for pipeline log
articles_total=$(echo "$snapshot" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['articlesTotal'])")
articles_today=$(echo "$snapshot" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['articlesPublishedToday'])")
errors_today=$(echo "$snapshot"   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['pipelineErrorsToday'])")
echo "[daily-snapshot] Written: $OUT_FILE (total=$articles_total today=$articles_today errors=$errors_today)"
