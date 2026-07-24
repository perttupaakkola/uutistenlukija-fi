#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/bin"
cat > "$TMP_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="${*: -1}"
if [[ "$url" == *"pipeline-status.json" ]]; then
    cat "$PIPELINE_FIXTURE"
else
    cat "$HEALTH_FIXTURE"
fi
printf '\n__HTTP_STATUS__200'
EOF
chmod +x "$TMP_DIR/bin/curl"

cat > "$TMP_DIR/health.json" <<'EOF'
{"status":"ok","lastPublished":null,"articleCount":1,"generatedAt":null,"pipeline":{"lastRun":null}}
EOF

fresh=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
cat > "$TMP_DIR/pipeline-status.json" <<EOF
{"generated_at":"$fresh","status":"ok","is_stale":false,"stagedQueueRunway":{"publisherEnabled":true,"outboxCount":24,"worstCaseRemainingCycles":8,"severity":"ok"}}
EOF

run_case() {
    local errors="$1" expected="$2"
    local state_file="$TMP_DIR/state-$errors.json"
    local snapshot_file="$TMP_DIR/snapshot-$errors.json" output

    printf '{"pipelineErrorsToday":%s}\n' "$errors" > "$snapshot_file"
    output=$(PATH="$TMP_DIR/bin:$PATH" \
        HEALTH_FIXTURE="$TMP_DIR/health.json" \
        PIPELINE_FIXTURE="$TMP_DIR/pipeline-status.json" \
        ENV_FILE="$TMP_DIR/missing.env" \
        STATE_FILE="$state_file" \
        SNAPSHOT_FILE="$snapshot_file" \
        HEALTH_URL="https://fixture.invalid/health.json" \
        PIPELINE_STATUS_URL="https://fixture.invalid/pipeline-status.json" \
        bash "$SCRIPT_DIR/health_monitor.sh" --dry-run)

    [[ $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["lastStatus"])' "$state_file") == "$expected" ]]

    if [[ "$expected" == "degraded" ]]; then
        grep -F "condition=degraded" <<< "$output" >/dev/null
        grep -F "23 errors today (threshold >20)" <<< "$output" >/dev/null
        grep -F "[dry-run] Would post to Discord:" <<< "$output" >/dev/null
    else
        grep -F "Status ok — no alert." <<< "$output" >/dev/null
        ! grep -F "Would post to Discord" <<< "$output" >/dev/null
    fi
}

run_case 23 degraded
run_case 20 ok

echo "health_monitor regression: PASS (>20 degraded, <=20 healthy, isolated dry-run)"
