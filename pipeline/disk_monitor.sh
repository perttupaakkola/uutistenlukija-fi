#!/usr/bin/env bash
# Compatibility entrypoint for the legacy crontab path.
set -euo pipefail

PROJECT_ROOT="/home/pertt/.openclaw/workspace/projects/uutistenlukija"
exec "$PROJECT_ROOT/scripts/disk_space_monitor.sh" "$@"
