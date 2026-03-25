#!/bin/bash
# validate_critical_scripts.sh
# Guards critical pipeline shell scripts against silent permission regressions.
# Fails if tracked mode or working-tree execute bit is wrong.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CRITICAL_SCRIPTS=(
  "pipeline/auto_publish.sh"
  "pipeline/firehose_cron.sh"
  "scripts/pipeline-watchdog.sh"
)

FAIL=0

for script in "${CRITICAL_SCRIPTS[@]}"; do
  if [ ! -f "$script" ]; then
    echo "[critical-scripts] MISSING: $script"
    FAIL=1
    continue
  fi

  mode=$(git ls-files -s -- "$script" | awk '{print $1}')
  if [ "$mode" != "100755" ]; then
    echo "[critical-scripts] BAD GIT MODE: $script is ${mode:-untracked}, expected 100755"
    FAIL=1
  fi

  if [ ! -x "$script" ]; then
    echo "[critical-scripts] NOT EXECUTABLE: $script"
    FAIL=1
  fi
done

if [ "$FAIL" -ne 0 ]; then
  echo "[critical-scripts] Fix with: chmod +x pipeline/auto_publish.sh pipeline/firehose_cron.sh scripts/pipeline-watchdog.sh"
  echo "[critical-scripts] Then stage mode changes with: git update-index --chmod=+x pipeline/auto_publish.sh pipeline/firehose_cron.sh scripts/pipeline-watchdog.sh"
  exit 1
fi

echo "[critical-scripts] OK — critical pipeline scripts are executable and tracked as 100755"
