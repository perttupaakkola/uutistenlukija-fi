#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR="$SCRIPT_DIR/health_monitor.sh"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT

mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/project/pipeline/logs"
cat > "$TEST_ROOT/bin/curl" <<'CURL'
#!/usr/bin/env bash
url="${*: -1}"
if [[ "$url" == *"pipeline-status.json" ]]; then
    [[ "${PIPELINE_CURL_FAIL:-false}" != "true" ]] || exit 22
    cat "$PIPELINE_FIXTURE"
else
    cat "$HEALTH_FIXTURE"
fi
printf '\n__HTTP_STATUS__200'
CURL
chmod +x "$TEST_ROOT/bin/curl"

fresh=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
stale_status=$(date -u -d '2 hours ago' '+%Y-%m-%dT%H:%M:%SZ')
quiet_article=$(date -u -d '8 hours ago' '+%Y-%m-%dT%H:%M:%SZ')

run_case() {
    local name="$1" health_payload="$2" pipeline_payload="$3" expected_status="$4" expected_output="$5"
    local fixture="$TEST_ROOT/$name-health.json"
    local pipeline_fixture="$TEST_ROOT/$name-pipeline.json"
    local state="$TEST_ROOT/project/pipeline/logs/health-monitor-state.json"
    printf '%s\n' "$health_payload" > "$fixture"
    printf '%s\n' "$pipeline_payload" > "$pipeline_fixture"
    rm -f "$state"

    output=$(PATH="$TEST_ROOT/bin:$PATH" \
        HEALTH_FIXTURE="$fixture" \
        PIPELINE_FIXTURE="$pipeline_fixture" \
        PROJECT_DIR="$TEST_ROOT/project" \
        bash "$MONITOR" --dry-run)

    actual_status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["lastStatus"])' "$state")
    [[ "$actual_status" == "$expected_status" ]] || {
        echo "$name: expected state $expected_status, got $actual_status" >&2
        echo "$output" >&2
        return 1
    }
    [[ "$output" == *"$expected_output"* ]] || {
        echo "$name: missing output marker: $expected_output" >&2
        echo "$output" >&2
        return 1
    }
    if [[ "$expected_status" == "ok" || "$expected_status" == "content_quiet" ]]; then
        [[ "$output" != *"[dry-run] Would post to Discord:"* ]] || {
            echo "$name: healthy/quiet case attempted an alert" >&2
            echo "$output" >&2
            return 1
        }
    else
        [[ "$output" == *"[dry-run] Would post to Discord:"* ]] || {
            echo "$name: failure case did not exercise the dry-run alert path" >&2
            echo "$output" >&2
            return 1
        }
    fi
}

base='"generatedAt":"'"$fresh"'","lastPublished":"'"$fresh"'","pipeline":{"lastRun":"'"$fresh"'"},"articleCount":10'
healthy_pipeline='{"generated_at":"'"$fresh"'","status":"ok","is_stale":false,"stagedQueueRunway":{"publisherEnabled":true,"outboxCount":24,"worstCaseRemainingCycles":8,"severity":"ok"}}'
stalled_pipeline='{"generated_at":"'"$fresh"'","status":"degraded","is_stale":true,"stagedQueueRunway":{"publisherEnabled":true,"outboxCount":24,"worstCaseRemainingCycles":8,"severity":"ok"}}'
stale_pipeline='{"generated_at":"'"$stale_status"'","status":"ok","is_stale":false,"stagedQueueRunway":{"publisherEnabled":true,"outboxCount":24,"worstCaseRemainingCycles":8,"severity":"ok"}}'
disabled_pipeline='{"generated_at":"'"$fresh"'","status":"ok","is_stale":false,"stagedQueueRunway":{"publisherEnabled":false,"outboxCount":24,"worstCaseRemainingCycles":8,"severity":"inactive"}}'
warning_pipeline='{"generated_at":"'"$fresh"'","status":"ok","is_stale":false,"stagedQueueRunway":{"publisherEnabled":true,"outboxCount":12,"worstCaseRemainingCycles":4,"severity":"warning"}}'
critical_pipeline='{"generated_at":"'"$fresh"'","status":"ok","is_stale":false,"stagedQueueRunway":{"publisherEnabled":true,"outboxCount":6,"worstCaseRemainingCycles":2,"severity":"critical"}}'

run_case missing "{$base}" "$healthy_pipeline" invalid_health "Invalid health payload"
run_case empty "{\"status\":\"\",$base}" "$healthy_pipeline" invalid_health "Invalid health payload"
run_case null "{\"status\":null,$base}" "$healthy_pipeline" invalid_health "Invalid health payload"
run_case unknown "{\"status\":\"mystery\",$base}" "$healthy_pipeline" invalid_health "Invalid health payload"
run_case non_string "{\"status\":42,$base}" "$healthy_pipeline" invalid_health "Invalid health payload"
run_case ok "{\"status\":\"ok\",$base}" "$healthy_pipeline" ok "Status ok — no alert"
run_case degraded "{\"status\":\"degraded\",$base}" "$healthy_pipeline" degraded "Site health degraded"
quiet_base='"generatedAt":"'"$fresh"'","lastPublished":"'"$quiet_article"'","pipeline":{"lastRun":"'"$fresh"'"},"articleCount":10'
run_case content_quiet "{\"status\":\"degraded\",$quiet_base}" "$healthy_pipeline" content_quiet "Status content_quiet — no alert"

# The retired VPS runtime marker is deliberately null. A fresh Actions status
# with healthy runway is authoritative and must suppress the old false alert.
retired_base='"generatedAt":"'"$quiet_article"'","lastPublished":"'"$quiet_article"'","pipeline":{"lastRun":null},"articleCount":10'
run_case retired_marker_null "{\"status\":\"ok\",$retired_base}" "$healthy_pipeline" content_quiet "Status content_quiet — no alert"

run_case actions_status_stale "{\"status\":\"ok\",$base}" "$stale_pipeline" actions_status_stale "Actions pipeline status stale"
run_case publisher_disabled "{\"status\":\"ok\",$base}" "$disabled_pipeline" publisher_disabled "Actions publisher disabled"
run_case queue_warning "{\"status\":\"ok\",$base}" "$warning_pipeline" queue_warning "Staged queue warning"
run_case queue_critical "{\"status\":\"ok\",$base}" "$critical_pipeline" queue_critical "Staged queue critical"
run_case publish_stalled "{\"status\":\"ok\",$quiet_base}" "$stalled_pipeline" publish_stalled "Publishing stalled"
run_case invalid_actions_status "{\"status\":\"ok\",$base}" '{"generated_at":"'"$fresh"'","status":"ok","is_stale":false}' invalid_actions_status "Invalid Actions pipeline status"

# Missing/unreachable Actions status fails closed even when site health is OK.
fixture="$TEST_ROOT/unavailable-health.json"
pipeline_fixture="$TEST_ROOT/unavailable-pipeline.json"
state="$TEST_ROOT/project/pipeline/logs/health-monitor-state.json"
printf '%s\n' "{\"status\":\"ok\",$base}" > "$fixture"
printf '%s\n' "$healthy_pipeline" > "$pipeline_fixture"
rm -f "$state"
output=$(PATH="$TEST_ROOT/bin:$PATH" \
    HEALTH_FIXTURE="$fixture" \
    PIPELINE_FIXTURE="$pipeline_fixture" \
    PIPELINE_CURL_FAIL=true \
    PROJECT_DIR="$TEST_ROOT/project" \
    bash "$MONITOR" --dry-run)
[[ $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["lastStatus"])' "$state") == "actions_status_unavailable" ]]
[[ "$output" == *"Actions pipeline status unavailable"* ]]

# A valid payload recovers from the new non-healthy condition using the existing
# recovery path, regardless of the normal alert cooldown.
state="$TEST_ROOT/project/pipeline/logs/health-monitor-state.json"
printf '%s\n' '{"lastStatus":"queue_warning","lastAlertTime":0,"consecutiveFailures":1,"lastAlertCondition":"queue_warning"}' > "$state"
fixture="$TEST_ROOT/recovery.json"
pipeline_fixture="$TEST_ROOT/recovery-pipeline.json"
printf '%s\n' "{\"status\":\"ok\",$retired_base}" > "$fixture"
printf '%s\n' "$healthy_pipeline" > "$pipeline_fixture"
output=$(PATH="$TEST_ROOT/bin:$PATH" HEALTH_FIXTURE="$fixture" PIPELINE_FIXTURE="$pipeline_fixture" PROJECT_DIR="$TEST_ROOT/project" bash "$MONITOR" --dry-run)
[[ "$output" == *"Pipeline recovered"* ]] || {
    echo "recovery: expected recovery alert" >&2
    echo "$output" >&2
    exit 1
}

echo "health_monitor status regression: PASS (Actions authority, retired marker, queue/publisher/stall failures, recovery)"
