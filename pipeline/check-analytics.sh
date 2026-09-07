#!/usr/bin/env bash
# Existing scheduled entry point. All outputs are private to the selected directory.
# --output-dir PATH isolates audit runs; --dry-run/--no-write queries without writes.
# No webhook, public static export, token persistence, or scheduler side effects.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$PROJECT_DIR/scripts/collect_analytics.py" "$@"
