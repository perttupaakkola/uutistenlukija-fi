#!/usr/bin/env bash
# check_pipeline_silence.sh — alert #operations if publish pipeline has gone silent
#
# Priority for run timestamp:
#   1) pipeline/.last_run
#   2) latest timestamp parsable from pipeline/logs/cron.log
#
# Priority for publish timestamp:
#   1) latest metrics.jsonl record with published > 0
#   2) fall back to run timestamp above
#
# Idempotency:
#   - stores the last alerted publish timestamp in pipeline/.silence_alert_state
#   - does not re-alert until a newer successful publish/run occurs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
PIPELINE_DIR="${PIPELINE_DIR:-$PROJECT_DIR/pipeline}"
LOG_FILE="${LOG_FILE:-$PIPELINE_DIR/logs/cron.log}"
LAST_RUN_FILE="${LAST_RUN_FILE:-$PIPELINE_DIR/.last_run}"
METRICS_FILE="${METRICS_FILE:-$PIPELINE_DIR/metrics.jsonl}"
STATE_FILE="${STATE_FILE:-$PIPELINE_DIR/.silence_alert_state}"
THRESHOLD_SECONDS="${THRESHOLD_SECONDS:-7200}"
OPERATIONS_CHANNEL_ID="1482082645553713366"

load_env() {
  if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
  fi
  if [[ -f "$PIPELINE_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PIPELINE_DIR/.env"
    set +a
  fi
}

trim() {
  sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

parse_epoch() {
  local raw="$1"
  python3 - "$raw" <<'PY'
import sys
from datetime import datetime, timezone
raw = sys.argv[1].strip()
if not raw:
    raise SystemExit(1)
patterns = [raw]
if raw.endswith('Z'):
    patterns.append(raw.replace('Z', '+00:00'))
for candidate in patterns:
    try:
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        print(int(dt.timestamp()))
        raise SystemExit(0)
    except Exception:
        pass
for fmt in [
    '%a %b %d %I:%M:%S %p UTC %Y',
    '%a %b %d %H:%M:%S UTC %Y',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S',
]:
    try:
        dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        print(int(dt.timestamp()))
        raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)
PY
}

get_last_run_iso() {
  if [[ -f "$LAST_RUN_FILE" ]]; then
    head -n 1 "$LAST_RUN_FILE" | trim
    return 0
  fi

  if [[ -f "$LOG_FILE" ]]; then
    python3 - "$LOG_FILE" <<'PY'
import re, sys
from pathlib import Path
log = Path(sys.argv[1]).read_text(encoding='utf-8', errors='ignore').splitlines()
for line in reversed(log):
    m = re.search(r'completed at (.+?) ===?$', line)
    if m:
        print(m.group(1).strip())
        raise SystemExit(0)
    m = re.search(r'(\d{4}-\d{2}-\d{2}[T ][0-9:]+(?:Z|[+-][0-9:]+)?)', line)
    if m:
        print(m.group(1).strip())
        raise SystemExit(0)
raise SystemExit(1)
PY
    return 0
  fi

  return 1
}

get_last_publish_fields() {
  if [[ -f "$METRICS_FILE" ]]; then
    python3 - "$METRICS_FILE" <<'PY'
import json, sys
from pathlib import Path
rows = Path(sys.argv[1]).read_text(encoding='utf-8', errors='ignore').splitlines()
for line in reversed(rows):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if int(rec.get('published', 0) or 0) > 0:
        print(rec.get('ts', '').strip())
        print(int(rec.get('published', 0) or 0))
        raise SystemExit(0)
raise SystemExit(1)
PY
    return 0
  fi

  return 1
}

post_alert() {
  local message="$1"
  local webhook="$2"
  python3 - "$webhook" "$message" <<'PY'
import json, sys, urllib.request
webhook, message = sys.argv[1], sys.argv[2]
payload = json.dumps({"content": message}).encode("utf-8")
req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=20) as resp:
    print(resp.status)
PY
}

load_env
WEBHOOK="${DISCORD_METRICS_WEBHOOK:-}"
if [[ -z "$WEBHOOK" ]]; then
  echo "[check_pipeline_silence] DISCORD_METRICS_WEBHOOK not set — skipping alert." >&2
  exit 0
fi

now_epoch="$(date -u +%s)"
last_run_raw="$(get_last_run_iso 2>/dev/null || true)"
last_run_epoch=""
if [[ -n "$last_run_raw" ]]; then
  last_run_epoch="$(parse_epoch "$last_run_raw" 2>/dev/null || true)"
fi

publish_raw=""
published_count="0"
if publish_fields="$(get_last_publish_fields 2>/dev/null || true)"; then
  publish_raw="$(printf '%s' "$publish_fields" | sed -n '1p')"
  published_count="$(printf '%s' "$publish_fields" | sed -n '2p')"
fi

publish_epoch=""
if [[ -n "$publish_raw" ]]; then
  publish_epoch="$(parse_epoch "$publish_raw" 2>/dev/null || true)"
fi

if [[ -z "$publish_epoch" ]]; then
  publish_raw="$last_run_raw"
  publish_epoch="$last_run_epoch"
fi

if [[ -z "$publish_epoch" ]]; then
  echo "[check_pipeline_silence] Could not determine last publish/run timestamp." >&2
  exit 1
fi

age_seconds=$((now_epoch - publish_epoch))
age_hours="$(python3 - <<PY
age = $age_seconds / 3600
print(f"{age:.1f}")
PY
)"

alert_key="${publish_epoch}:${publish_raw}"
last_alerted_key=""
if [[ -f "$STATE_FILE" ]]; then
  last_alerted_key="$(head -n 1 "$STATE_FILE" | trim || true)"
fi

if (( age_seconds <= THRESHOLD_SECONDS )); then
  if [[ -f "$STATE_FILE" ]]; then
    rm -f "$STATE_FILE"
  fi
  echo "[check_pipeline_silence] OK — last publish/run ${age_hours}h ago (${publish_raw})."
  exit 0
fi

if [[ "$last_alerted_key" == "$alert_key" ]]; then
  echo "[check_pipeline_silence] Already alerted for ${publish_raw}; skipping duplicate alert."
  exit 0
fi

message="⚠️ Pipeline hiljaa yli 2h — viimeisin julkaisu/run **${age_hours}h** sitten (${publish_raw}). Tarkista cron / firehose / pipeline status. Channel: #operations (${OPERATIONS_CHANNEL_ID})."
post_alert "$message" "$WEBHOOK" >/dev/null
printf '%s\n' "$alert_key" > "$STATE_FILE"
echo "[check_pipeline_silence] Alert posted for ${publish_raw} (published=${published_count})."
