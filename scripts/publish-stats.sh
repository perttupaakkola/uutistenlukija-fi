#!/usr/bin/env bash
# publish-stats.sh — print a publish-rate summary from publish-metrics.json
#
# Usage:
#   ./scripts/publish-stats.sh           # default summary
#   ./scripts/publish-stats.sh --discord # compact single-line for Discord
#   ./scripts/publish-stats.sh --days 14 # look back N days (default: 7)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
METRICS_FILE="$PROJECT_DIR/pipeline/logs/publish-metrics.json"

if [[ ! -f "$METRICS_FILE" ]]; then
  echo "❌ publish-metrics.json not found at $METRICS_FILE" >&2
  exit 1
fi

# Parse flags
DISCORD=0
DAYS=7
while [[ $# -gt 0 ]]; do
  case "$1" in
    --discord) DISCORD=1; shift ;;
    --days)    DAYS="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

python3 - "$METRICS_FILE" "$DISCORD" "$DAYS" << 'PYEOF'
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

metrics_file = Path(sys.argv[1])
discord_mode = sys.argv[2] == "1"
days = int(sys.argv[3])

# Load all records
records = []
for line in metrics_file.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        records.append(json.loads(line))
    except Exception:
        pass

if not records:
    print("No data in publish-metrics.json")
    sys.exit(0)

now = datetime.now(timezone.utc)
today_str = now.strftime("%Y-%m-%d")
cutoff = now - timedelta(days=days)

# Today's runs
today_runs = [r for r in records if r.get("ts", "").startswith(today_str)]
today_published = sum(r.get("published", 0) for r in today_runs)
today_success = sum(1 for r in today_runs if r.get("success"))
today_total = len(today_runs)

# Rolling window
window_runs = [
    r for r in records
    if r.get("ts") and datetime.fromisoformat(r["ts"]) >= cutoff
]
window_published = sum(r.get("published", 0) for r in window_runs)
window_attempted = sum(r.get("attempted", 0) for r in window_runs)
window_success = sum(1 for r in window_runs if r.get("success"))
window_total = len(window_runs)

days_in_window = max(1, len({r["ts"][:10] for r in window_runs}))
daily_avg = window_published / days_in_window if days_in_window > 0 else 0
success_rate = (window_success / window_total * 100) if window_total > 0 else 0
publish_rate = (window_published / window_attempted * 100) if window_attempted > 0 else 0

# Last successful run
successful = [r for r in records if r.get("success") and r.get("published", 0) > 0]
last_success = successful[-1] if successful else None

if discord_mode:
    # Compact single line for Discord
    last_ts = last_success["ts"][:16].replace("T", " ") + " UTC" if last_success else "N/A"
    print(
        f"📊 **Publish stats ({days}d)** — "
        f"today: {today_published} articles | "
        f"{days}d avg: {daily_avg:.1f}/day | "
        f"success rate: {success_rate:.0f}% | "
        f"last publish: {last_ts}"
    )
else:
    print(f"📊 Publish Stats — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'─'*44}")
    print(f"  Today ({today_str})")
    print(f"    Articles published : {today_published}")
    print(f"    Pipeline runs      : {today_total} ({today_success} ok / {today_total - today_success} failed)")
    print()
    print(f"  Last {days} days")
    print(f"    Articles published : {window_published}")
    print(f"    Daily average      : {daily_avg:.1f} articles/day")
    print(f"    Pipeline runs      : {window_total} ({window_success} ok / {window_total - window_success} failed)")
    print(f"    Pipeline success % : {success_rate:.1f}%")
    if window_attempted > 0:
        print(f"    Publish rate       : {publish_rate:.1f}% (published/attempted)")
    if last_success:
        last_ts = last_success["ts"][:16].replace("T", " ") + " UTC"
        print(f"    Last publish       : {last_ts} ({last_success['published']} article(s))")
    print(f"{'─'*44}")
PYEOF
