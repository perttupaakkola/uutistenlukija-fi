#!/bin/bash
# install-crons.sh — idempotent cron installer for uutistenlukija.fi
#
# Usage:
#   ./scripts/install-crons.sh           # install missing cron entries
#   ./scripts/install-crons.sh --dry-run # preview only, no changes made
#   ./scripts/install-crons.sh --check   # exit 0=all installed, exit 1=missing
#
# Source of truth: pipeline/crons.txt
# Idempotency: matches on command path, not full line.
# Safe to run multiple times. Never removes existing entries.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CRONS_TXT="$PROJECT_DIR/pipeline/crons.txt"
BACKUP_FILE="/tmp/crontab-backup-$(date +%Y%m%d-%H%M%S).txt"

DRY_RUN=false
CHECK_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --check)   CHECK_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--check]"
            exit 0 ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 1 ;;
    esac
done

if [[ ! -f "$CRONS_TXT" ]]; then
    echo "ERROR: crons.txt not found at $CRONS_TXT" >&2
    exit 1
fi

CURRENT_CRONTAB="$(crontab -l 2>/dev/null || true)"
missing_count=0
entries_to_add=()

while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

    command_part="$(echo "$line" | awk '{for(i=6;i<=NF;i++) printf "%s%s", $i, (i<NF?" ":"\n")}')"
    dedup_key="$(echo "$command_part" | sed 's/^cd [^ ]* && //' | awk '{print $1}')"

    if echo "$CURRENT_CRONTAB" | grep -qF "$dedup_key"; then
        echo "ALREADY INSTALLED: $dedup_key"
    else
        echo "MISSING: $line"
        missing_count=$((missing_count + 1))
        entries_to_add+=("$line")
    fi
done < "$CRONS_TXT"

echo ""

if $CHECK_ONLY; then
    if [[ $missing_count -eq 0 ]]; then
        echo "All cron entries are installed."
        exit 0
    else
        echo "$missing_count entries missing."
        exit 1
    fi
fi

if [[ $missing_count -eq 0 ]]; then
    echo "All cron entries already installed. Nothing to do."
    exit 0
fi

if $DRY_RUN; then
    echo "DRY RUN -- $missing_count entries would be added. No changes made."
    exit 0
fi

echo "Backing up current crontab to $BACKUP_FILE"
echo "$CURRENT_CRONTAB" > "$BACKUP_FILE"

NEW_CRONTAB="$CURRENT_CRONTAB"
for entry in "${entries_to_add[@]}"; do
    NEW_CRONTAB="${NEW_CRONTAB}"$'\n'"${entry}"
done

echo "$NEW_CRONTAB" | crontab -

echo "Installed $missing_count new cron entries."
echo "Backup saved to: $BACKUP_FILE"
echo "Verify with: crontab -l"
