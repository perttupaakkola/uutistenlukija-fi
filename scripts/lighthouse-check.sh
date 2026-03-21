#!/usr/bin/env bash
# lighthouse-check.sh — Lighthouse CI scoring via PageSpeed Insights API
#
# Usage:
#   ./scripts/lighthouse-check.sh [URL] [mobile|desktop]
#
# Env:
#   PAGESPEED_API_KEY  — optional Google API key (raises quota from 25 to 10k/day)
#   LIGHTHOUSE_THRESHOLD — score threshold for warnings (default: 80)
#
# Output:
#   - One-line summary printed to stdout
#   - Results appended to pipeline/lighthouse.jsonl
#   - Exit 0 if all scores pass, exit 1 if any score below threshold

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
JSONL_FILE="$PIPELINE_DIR/lighthouse.jsonl"

URL="${1:-https://uutistenlukija.fi}"
STRATEGY="${2:-mobile}"
THRESHOLD="${LIGHTHOUSE_THRESHOLD:-80}"
API_KEY="${PAGESPEED_API_KEY:-}"

PSI_URL="https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_PARAMS="url=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$URL")&strategy=$STRATEGY"
if [ -n "$API_KEY" ]; then
  PSI_PARAMS="${PSI_PARAMS}&key=${API_KEY}"
fi

echo "[lighthouse] Auditing $URL (strategy=$STRATEGY) ..."

# Fetch PSI response
TMPFILE=$(mktemp /tmp/lighthouse_XXXXXX.json)
trap 'rm -f "$TMPFILE"' EXIT

HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TMPFILE" "${PSI_URL}?${PSI_PARAMS}" 2>&1)

# Parse scores with Python
PARSE_RESULT=$(JSONL_FILE="$JSONL_FILE" python3 - "$TMPFILE" "$THRESHOLD" "$URL" "$STRATEGY" <<'PYEOF'
import sys, json, os
from datetime import datetime, timezone

tmpfile, threshold_s, url, strategy = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
threshold = int(threshold_s)

with open(tmpfile, encoding="utf-8") as f:
    data = json.load(f)

# Handle API errors
if "error" in data:
    err = data["error"]
    code = err.get("code", "?")
    msg = err.get("message", "unknown error")
    if code == 429:
        print(f"[lighthouse] QUOTA_EXCEEDED: PSI daily quota hit. Set PAGESPEED_API_KEY to raise limit.", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"[lighthouse] API_ERROR {code}: {msg}", file=sys.stderr)
        sys.exit(3)

cats = data.get("lighthouseResult", {}).get("categories", {})

score_map = {
    "performance":     cats.get("performance",     {}).get("score"),
    "accessibility":   cats.get("accessibility",   {}).get("score"),
    "best-practices":  cats.get("best-practices",  {}).get("score"),
    "seo":             cats.get("seo",             {}).get("score"),
}

# Convert to 0-100 ints
scores = {k: round(v * 100) if v is not None else None for k, v in score_map.items()}

perf  = scores.get("performance")
a11y  = scores.get("accessibility")
bp    = scores.get("best-practices")
seo   = scores.get("seo")

# Warn on low scores
warn = False
for label, val in [("Performance", perf), ("Accessibility", a11y),
                   ("Best-Practices", bp), ("SEO", seo)]:
    if val is not None and val < threshold:
        print(f"[lighthouse] WARN: {label}={val} (threshold: {threshold})")
        warn = True

# One-line summary
parts = []
if perf  is not None: parts.append(f"Perf={perf}")
if a11y  is not None: parts.append(f"A11y={a11y}")
if bp    is not None: parts.append(f"BP={bp}")
if seo   is not None: parts.append(f"SEO={seo}")
print("Lighthouse: " + "  ".join(parts))

# Append to JSONL
record = {
    "ts":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "url":           url,
    "strategy":      strategy,
    "performance":   perf,
    "accessibility": a11y,
    "best_practices": bp,
    "seo":           seo,
    "pass":          not warn,
    "threshold":     threshold,
}

jsonl_path = os.environ.get("JSONL_FILE", "")
if jsonl_path:
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as jf:
        jf.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[lighthouse] Appended to {jsonl_path}")

sys.exit(1 if warn else 0)
PYEOF
)

EXIT_CODE=$?
echo "$PARSE_RESULT"

if [ $EXIT_CODE -eq 2 ]; then
  # Quota exceeded — exit 0 so deploy doesn't fail on quota
  exit 0
fi

exit $EXIT_CODE
