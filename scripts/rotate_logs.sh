#!/usr/bin/env bash
# =============================================================================
# rotate_logs.sh — pipeline log rotation for uutistenlukija.fi
#
# 1. Archives pipeline/logs/*.json older than 7 days → pipeline/logs/archive/YYYY-MM/
# 2. Gzip-compresses archived files
# 3. Deletes archive subdirs older than 30 days
# 4. Prints rotation summary (files moved, space reclaimed)
#
# Schedule: Weekly Sunday 06:00 UTC (see CRON.md)
# Usage: bash scripts/rotate_logs.sh [--dry-run]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
LOGS_DIR="$PROJECT_DIR/pipeline/logs"
ARCHIVE_DIR="$LOGS_DIR/archive"
ROTATE_DAYS=7        # files older than this get archived
KEEP_DAYS=30         # archive dirs older than this get deleted
DRY_RUN=false

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

log() { echo "[rotate_logs $(date -u '+%Y-%m-%d %H:%M UTC')] $*"; }
drylog() { [[ "$DRY_RUN" == "true" ]] && echo "  [dry-run] $*" || true; }

files_moved=0
bytes_saved=0
files_compressed=0

# ── 1. Archive *.json files older than ROTATE_DAYS ───────────────────────────
log "Scanning $LOGS_DIR for *.json files older than ${ROTATE_DAYS}d..."

while IFS= read -r -d '' file; do
    # Determine YYYY-MM from file mtime
    file_mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
    year_month=$(date -d "@$file_mtime" '+%Y-%m' 2>/dev/null || date -r "$file_mtime" '+%Y-%m' 2>/dev/null)
    dest_dir="$ARCHIVE_DIR/$year_month"
    dest_file="$dest_dir/$(basename "$file")"
    size_before=$(stat -c %s "$file" 2>/dev/null || stat -f %z "$file" 2>/dev/null || echo 0)

    log "  Archive: $(basename "$file") → archive/$year_month/"
    drylog "mv $file → $dest_file"

    if [[ "$DRY_RUN" == "false" ]]; then
        mkdir -p "$dest_dir"
        mv "$file" "$dest_file"

        # Compress
        gzip -f "$dest_file"
        size_after=$(stat -c %s "${dest_file}.gz" 2>/dev/null || stat -f %z "${dest_file}.gz" 2>/dev/null || echo 0)
        saved=$(( size_before - size_after ))
        bytes_saved=$(( bytes_saved + saved ))
        files_compressed=$(( files_compressed + 1 ))
    else
        drylog "gzip $dest_file"
    fi

    files_moved=$(( files_moved + 1 ))

done < <(find "$LOGS_DIR" -maxdepth 1 -name "*.json" \
    ! -name "health-monitor-state.json" \
    ! -name "publish-metrics.json" \
    ! -name "metrics_history.json" \
    -mtime +"$ROTATE_DAYS" -print0 2>/dev/null)

# ── 2. Delete archive subdirs older than KEEP_DAYS ───────────────────────────
log "Pruning archive dirs older than ${KEEP_DAYS}d..."

deleted_dirs=0
if [[ -d "$ARCHIVE_DIR" ]]; then
    while IFS= read -r -d '' old_dir; do
        log "  Delete old archive: $old_dir"
        drylog "rm -rf $old_dir"
        if [[ "$DRY_RUN" == "false" ]]; then
            rm -rf "$old_dir"
        fi
        deleted_dirs=$(( deleted_dirs + 1 ))
    done < <(find "$ARCHIVE_DIR" -mindepth 1 -maxdepth 1 -type d \
        -mtime +"$KEEP_DAYS" -print0 2>/dev/null)
fi

# ── 3. Summary ────────────────────────────────────────────────────────────────
if (( bytes_saved > 1048576 )); then
    space_str="$(( bytes_saved / 1048576 )) MB"
elif (( bytes_saved > 1024 )); then
    space_str="$(( bytes_saved / 1024 )) KB"
else
    space_str="${bytes_saved} B"
fi

log "Done. files_moved=$files_moved compressed=$files_compressed space_saved=$space_str old_dirs_deleted=$deleted_dirs"
[[ "$DRY_RUN" == "true" ]] && log "(dry-run: no changes made)"

exit 0
