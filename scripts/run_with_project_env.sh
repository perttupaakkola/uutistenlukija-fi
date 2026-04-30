#!/usr/bin/env bash
# Load uutistenlukija project environment variables for cron jobs, then exec the command.
# Keeps webhook/API secrets in .env instead of embedding them in crontab.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_DIR/.env"
  set +a
fi
exec "$@"
