#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR="$SCRIPT_DIR/health_monitor.sh"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT

mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/project/pipeline/logs"
cat > "$TEST_ROOT/bin/curl" <<'CURL'
#!/usr/bin/env bash
cat "$HEALTH_FIXTURE"
printf '\n__HTTP_STATUS__200'
CURL
chmod +x "$TEST_ROOT/bin/curl"

fresh=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
quiet_article=$(date -u -d '8 hours ago' '+%Y-%m-%dT%H:%M:%SZ')

run_case() {
    local name="$1" payload="$2" expected_status="$3" expected_output="$4"
    local fixture="$TEST_ROOT/$name.json"
    local state="$TEST_ROOT/project/pipeline/logs/health-monitor-state.json"
    printf '%s\n' "$payload" > "$fixture"
    rm -f "$state"

    output=$(PATH="$TEST_ROOT/bin:$PATH" \
        HEALTH_FIXTURE="$fixture" \
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
}

base='"generatedAt":"'"$fresh"'","lastPublished":"'"$fresh"'","pipeline":{"lastRun":"'"$fresh"'"},"articleCount":10'
run_case missing "{$base}" invalid_health "Invalid health payload"
run_case empty "{\"status\":\"\",$base}" invalid_health "Invalid health payload"
run_case null "{\"status\":null,$base}" invalid_health "Invalid health payload"
run_case unknown "{\"status\":\"mystery\",$base}" invalid_health "Invalid health payload"
run_case non_string "{\"status\":42,$base}" invalid_health "Invalid health payload"
run_case ok "{\"status\":\"ok\",$base}" ok "Status ok — no alert"
run_case degraded "{\"status\":\"degraded\",$base}" degraded "Pipeline degraded"
quiet_base='"generatedAt":"'"$fresh"'","lastPublished":"'"$quiet_article"'","pipeline":{"lastRun":"'"$fresh"'"},"articleCount":10'
run_case content_quiet "{\"status\":\"degraded\",$quiet_base}" content_quiet "Status content_quiet — no alert"

# A valid payload recovers from the new non-healthy condition using the existing
# recovery path, regardless of the normal alert cooldown.
state="$TEST_ROOT/project/pipeline/logs/health-monitor-state.json"
printf '%s\n' '{"lastStatus":"invalid_health","lastAlertTime":0,"consecutiveFailures":1,"lastAlertCondition":"invalid_health"}' > "$state"
fixture="$TEST_ROOT/recovery.json"
printf '%s\n' "{\"status\":\"ok\",$base}" > "$fixture"
output=$(PATH="$TEST_ROOT/bin:$PATH" HEALTH_FIXTURE="$fixture" PROJECT_DIR="$TEST_ROOT/project" bash "$MONITOR" --dry-run)
[[ "$output" == *"Pipeline recovered"* ]] || {
    echo "recovery: expected recovery alert" >&2
    echo "$output" >&2
    exit 1
}

echo "health_monitor status regression: PASS (invalid statuses fail closed; ok/degraded/recovery preserved)"
