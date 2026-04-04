#!/usr/bin/env bash
# Disk space monitor — posts Discord alert when usage exceeds thresholds
# Runs via cron every 6 hours
set -euo pipefail

THRESHOLD_WARN=80
THRESHOLD_CRIT=90
STATUS_FILE="/home/pertt/.openclaw/workspace/projects/uutistenlukija/data/disk_space_status.json"
WEBHOOK_URL="${DISCORD_PIPELINE_WEBHOOK:-}"

mkdir -p "$(dirname "$STATUS_FILE")"

check_partition() {
    local mount="$1"
    local usage
    usage=$(df "$mount" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
    echo "$usage"
}

root_usage=$(check_partition "/")
home_usage=$(check_partition "/home")
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Write status file
cat > "$STATUS_FILE" <<EOF
{
  "timestamp": "$now",
  "root_pct": $root_usage,
  "home_pct": $home_usage,
  "status": "$([ "$root_usage" -ge "$THRESHOLD_CRIT" ] || [ "$home_usage" -ge "$THRESHOLD_CRIT" ] && echo "critical" || ([ "$root_usage" -ge "$THRESHOLD_WARN" ] || [ "$home_usage" -ge "$THRESHOLD_WARN" ] && echo "warning" || echo "ok"))"
}
EOF

# Only post to Discord if threshold exceeded
if [ "$root_usage" -ge "$THRESHOLD_CRIT" ] || [ "$home_usage" -ge "$THRESHOLD_CRIT" ]; then
    msg="🚨 **CRITICAL: Disk space >90%** — root: ${root_usage}%, /home: ${home_usage}%"
elif [ "$root_usage" -ge "$THRESHOLD_WARN" ] || [ "$home_usage" -ge "$THRESHOLD_WARN" ]; then
    msg="⚠️ **Disk space >80%** — root: ${root_usage}%, /home: ${home_usage}%"
else
    exit 0  # All good, stay silent
fi

# Post alert if webhook is set
if [ -n "$WEBHOOK_URL" ]; then
    curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$msg\"}" >/dev/null 2>&1
fi

echo "$msg"
