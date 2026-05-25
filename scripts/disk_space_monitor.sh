#!/usr/bin/env bash
# Disk space monitor - records root/home usage and optionally posts alerts.
# Runs via cron every 6 hours.
set -euo pipefail

PROJECT_ROOT="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
THRESHOLD_WARN="${DISK_MONITOR_WARN_PCT:-80}"
THRESHOLD_CRIT="${DISK_MONITOR_CRIT_PCT:-90}"
STATUS_FILE="${DISK_MONITOR_STATUS_FILE:-$PROJECT_ROOT/data/disk_space_status.json}"
WEBHOOK_URL="${DISCORD_PIPELINE_WEBHOOK:-}"
DRY_RUN=0
NO_ALERT=0

usage() {
    cat <<'EOF'
Usage: scripts/disk_space_monitor.sh [--dry-run] [--no-alert]

Options:
  --dry-run   Print the status JSON without writing data/disk_space_status.json.
  --no-alert  Do not post to Discord even if a webhook is configured.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            ;;
        --no-alert)
            NO_ALERT=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

mkdir -p "$(dirname "$STATUS_FILE")"

partition_pct() {
    local mount="$1"
    df -P "$mount" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}'
}

partition_available_kb() {
    local mount="$1"
    df -P "$mount" 2>/dev/null | awk 'NR==2 {print $4}'
}

status_for_usage() {
    local root_pct="$1"
    local home_pct="$2"
    if [ "$root_pct" -ge "$THRESHOLD_CRIT" ] || [ "$home_pct" -ge "$THRESHOLD_CRIT" ]; then
        echo "critical"
    elif [ "$root_pct" -ge "$THRESHOLD_WARN" ] || [ "$home_pct" -ge "$THRESHOLD_WARN" ]; then
        echo "warning"
    else
        echo "ok"
    fi
}

root_usage=$(partition_pct "/")
home_usage=$(partition_pct "/home")
root_available_kb=$(partition_available_kb "/")
home_available_kb=$(partition_available_kb "/home")
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
status=$(status_for_usage "$root_usage" "$home_usage")

status_json=$(cat <<EOF
{
  "timestamp": "$now",
  "status": "$status",
  "threshold_warn_pct": $THRESHOLD_WARN,
  "threshold_crit_pct": $THRESHOLD_CRIT,
  "root_pct": $root_usage,
  "root_available_kb": $root_available_kb,
  "home_pct": $home_usage,
  "home_available_kb": $home_available_kb,
  "source": "scripts/disk_space_monitor.sh"
}
EOF
)

if [ "$DRY_RUN" -eq 1 ]; then
    printf '%s\n' "$status_json"
else
    printf '%s\n' "$status_json" > "$STATUS_FILE"
fi

if [ "$status" = "critical" ]; then
    msg="CRITICAL: Disk space >=${THRESHOLD_CRIT}% - root: ${root_usage}%, /home: ${home_usage}%"
elif [ "$status" = "warning" ]; then
    msg="WARNING: Disk space >=${THRESHOLD_WARN}% - root: ${root_usage}%, /home: ${home_usage}%"
else
    msg="OK: Disk space below thresholds - root: ${root_usage}%, /home: ${home_usage}%"
fi

if [ "$status" != "ok" ] && [ "$DRY_RUN" -eq 1 ]; then
    echo "$msg" >&2
elif [ "$status" != "ok" ]; then
    echo "$msg"
fi

if [ "$status" != "ok" ] && [ "$NO_ALERT" -eq 0 ] && [ -n "$WEBHOOK_URL" ]; then
    curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$msg\"}" >/dev/null 2>&1
fi
