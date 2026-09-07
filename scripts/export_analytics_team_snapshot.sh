#!/bin/sh
# Installed host interface: same no-argument cron entrypoint, offline export.
set -eu
if [ "$#" -ne 0 ]; then
    printf '%s\n' 'This exporter takes no arguments.' >&2
    exit 2
fi
ROOT="${HOME}/.openclaw"
exec /usr/bin/python3 "$ROOT/workspace/scripts/uutistenlukija_current_main_job.py" \
    --name team-analytics-snapshot -- /usr/bin/python3 -B \
    scripts/analytics_projection.py --team-root "$ROOT"
