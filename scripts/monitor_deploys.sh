#!/usr/bin/env bash
# monitor_deploys.sh — GitHub Actions failure detector + auto-fix
# Runs every 5 minutes via cron. Detects deploy failures, diagnoses, and posts to Discord.
#
# Cron entry (add via install-crons.sh or manually):
#   */5 * * * * /home/pertt/.openclaw/workspace/projects/uutistenlukija/scripts/monitor_deploys.sh >> /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/logs/deploy-monitor.log 2>&1

set -euo pipefail

REPO="perttupaakkola/uutistenlukija-fi"
PROJECT_DIR="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
STATE_FILE="$PROJECT_DIR/pipeline/logs/deploy-monitor-state.json"
LOG_FILE="$PROJECT_DIR/pipeline/logs/deploy-monitor.log"
HUGO_BIN="/tmp/hugo"
DISCORD_WEBHOOK="${DISCORD_PIPELINE_WEBHOOK:-}"

mkdir -p "$PROJECT_DIR/pipeline/logs"

ts() { date -u '+%Y-%m-%d %H:%M UTC'; }
log() { echo "[$(ts)] $*"; }

# ── Load state ────────────────────────────────────────────────────────────────
last_known_sha=""
last_status=""
if [[ -f "$STATE_FILE" ]]; then
    last_known_sha=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('last_sha',''))" 2>/dev/null || echo "")
    last_status=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('last_status',''))" 2>/dev/null || echo "")
fi

# ── Fetch latest run ──────────────────────────────────────────────────────────
RUNS=$(curl -sf "https://api.github.com/repos/$REPO/actions/workflows/deploy.yml/runs?per_page=1" 2>/dev/null) || {
    log "ERROR: GitHub API unreachable"
    exit 0
}

SHA=$(echo "$RUNS" | python3 -c "import json,sys; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['head_sha'])" 2>/dev/null || echo "")
STATUS=$(echo "$RUNS" | python3 -c "import json,sys; r=json.load(sys.stdin)['workflow_runs'][0]; print(r.get('conclusion') or r['status'])" 2>/dev/null || echo "")
TITLE=$(echo "$RUNS" | python3 -c "import json,sys; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['display_title'][:60])" 2>/dev/null || echo "")
RUN_URL=$(echo "$RUNS" | python3 -c "import json,sys; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['html_url'])" 2>/dev/null || echo "")

log "Latest: $SHA ($STATUS) — $TITLE"

# Save state
python3 -c "
import json
d = {'last_sha': '$SHA', 'last_status': '$STATUS', 'updated': '$(ts)'}
json.dump(d, open('$STATE_FILE', 'w'))
" 2>/dev/null

# ── Already saw this SHA or it's passing ─────────────────────────────────────
if [[ "$SHA" == "$last_known_sha" && "$STATUS" == "$last_status" ]]; then
    log "No change since last check — exiting"
    exit 0
fi

if [[ "$STATUS" == "success" ]]; then
    log "Deploy green ✅"
    # If previous was failure, post recovery notice
    if [[ "$last_status" == "failure" ]]; then
        if [[ -n "$DISCORD_WEBHOOK" ]]; then
            python3 -c "
import urllib.request, json
msg = '✅ Deploy recovered — $SHA — $TITLE'
payload = json.dumps({'content': msg}).encode()
req = urllib.request.Request('$DISCORD_WEBHOOK', data=payload, headers={'Content-Type':'application/json'}, method='POST')
urllib.request.urlopen(req, timeout=10)
" 2>/dev/null || true
        fi
    fi
    exit 0
fi

if [[ "$STATUS" != "failure" ]]; then
    log "Status is '$STATUS' — not a failure, skipping"
    exit 0
fi

# ── FAILURE — diagnose ────────────────────────────────────────────────────────
log "🚨 Deploy failed! Diagnosing..."

# Pull latest
cd "$PROJECT_DIR"
git pull --rebase --quiet 2>/dev/null || true

# Run template validation
TEMPLATE_ERRORS=""
if bash scripts/validate_templates.sh --no-discord 2>&1 | grep -q "VALIDATION FAILED"; then
    TEMPLATE_ERRORS=$(bash scripts/validate_templates.sh --no-discord 2>&1 | grep "❌" | head -5)
    log "Template validation failed: $TEMPLATE_ERRORS"
fi

# Run Hugo build
BUILD_ERROR=""
if [[ -x "$HUGO_BIN" ]]; then
    BUILD_OUTPUT=$("$HUGO_BIN" --minify 2>&1 | tail -5)
    if echo "$BUILD_OUTPUT" | grep -q "Error:"; then
        BUILD_ERROR=$(echo "$BUILD_OUTPUT" | grep "Error:" | head -3)
        log "Hugo build failed: $BUILD_ERROR"
    else
        log "Hugo build OK locally"
    fi
fi

# ── Attempt auto-fix ──────────────────────────────────────────────────────────
FIXED=0
FIX_DESC=""

# Auto-fix 1: deprecated math shortcuts
if echo "$TEMPLATE_ERRORS" | grep -q "math shortcut"; then
    if [[ -f "fix_all_templates.py" ]]; then
        python3 fix_all_templates.py >> "$LOG_FILE" 2>&1
        git add layouts/ && git commit -m "auto-fix: deprecated Hugo math shortcuts (monitor_deploys)" && git push origin main
        FIXED=1
        FIX_DESC="Fixed deprecated Hugo math shortcuts"
        log "Auto-fixed: math shortcuts"
    fi
fi

# Auto-fix 2: _internal/pagination.html
if echo "$BUILD_ERROR" | grep -q "_internal/pagination.html"; then
    find layouts -name "*.html" -exec grep -l "_internal/pagination.html" {} \; | while read f; do
        sed -i 's|{{ template "_internal/pagination.html" . }}|{{/* Pagination — Hugo 0.147 removed _internal/pagination */}}|g' "$f"
        log "Fixed pagination in $f"
    done
    git add layouts/ && git commit -m "auto-fix: remove _internal/pagination.html ref (monitor_deploys)" && git push origin main
    FIXED=1
    FIX_DESC="Fixed _internal/pagination.html reference"
fi

# Auto-fix 3: execute bit on critical scripts
if echo "$BUILD_ERROR" | grep -q "critical_scripts\|permission"; then
    git update-index --chmod=+x pipeline/auto_publish.sh pipeline/firehose_cron.sh scripts/pipeline-watchdog.sh 2>/dev/null || true
    git commit -m "auto-fix: restore execute bits on critical scripts (monitor_deploys)" --allow-empty && git push origin main
    FIXED=1
    FIX_DESC="Restored execute bits on critical scripts"
fi

# Auto-fix 4: sort pipe syntax
if echo "$BUILD_ERROR" | grep -q "can't sort string\|sort.*pipe"; then
    find layouts -name "*.html" -exec grep -l "| sort \"" {} \; | while read f; do
        # Replace "X | sort "Key" "order"" with "sort X "Key" "order""
        python3 -c "
import re, sys
with open('$f') as fp:
    content = fp.read()
# Match: \$var | sort \"Key\" \"order\"
fixed = re.sub(r'(\\\$\w+)\s*\|\s*sort\s+(\"[^\"]+\")\s+(\"[^\"]+\")', r'sort \1 \2 \3', content)
if fixed != content:
    with open('$f', 'w') as fp:
        fp.write(fixed)
    print(f'Fixed sort pipe in $f')
" 2>/dev/null
    done
    git add layouts/ && git commit -m "auto-fix: sort pipe syntax for Hugo 0.147 (monitor_deploys)" && git push origin main
    FIXED=1
    FIX_DESC="Fixed sort pipe syntax"
fi

# ── Post Discord alert ────────────────────────────────────────────────────────
if [[ -n "$DISCORD_WEBHOOK" ]]; then
    if [[ $FIXED -eq 1 ]]; then
        MSG="🔧 **Auto-fixed deploy failure** — $FIX_DESC\nSHA: \`$SHA\` — $TITLE\nFix pushed — next deploy should be green."
    else
        MSG="🚨 **Deploy failed** — could not auto-fix\nSHA: \`$SHA\` — $TITLE"
        [[ -n "$TEMPLATE_ERRORS" ]] && MSG="$MSG\nTemplate errors: $TEMPLATE_ERRORS"
        [[ -n "$BUILD_ERROR" ]] && MSG="$MSG\nBuild error: $BUILD_ERROR"
        MSG="$MSG\nURL: $RUN_URL"
    fi
    python3 -c "
import urllib.request, json, sys
msg = sys.argv[1].replace('\\\\n', '\n')
payload = json.dumps({'content': msg}).encode()
req = urllib.request.Request('$DISCORD_WEBHOOK', data=payload, headers={'Content-Type':'application/json'}, method='POST')
urllib.request.urlopen(req, timeout=10)
print('Discord alert sent')
" "$MSG" 2>/dev/null || log "Discord alert failed"
fi

log "Done (fixed=$FIXED)"
