#!/usr/bin/env bash
# =============================================================================
# rotate_logs.sh — pipeline log rotation for uutistenlukija.fi
#
# 1. Archives pipeline/logs/*.json older than 7 days → pipeline/logs/archive/YYYY-MM/
# 2. Gzip-compresses archived files
# 3. Deletes archive subdirs older than 30 days
# 4. Trims metrics_history.json to 4 weeks, archives older entries
# 5. Rotates oversized log files (pipeline-failures.log, rejected_articles.log)
# 6. Prints rotation summary (files moved, space saved)
#
# Schedule: Weekly Sunday 06:00 UTC (see CRON.md)
# Usage: bash scripts/rotate_logs.sh [--dry-run]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
PIPELINE_DIR="$PROJECT_DIR/pipeline"
LOGS_DIR="$PROJECT_DIR/pipeline/logs"
ARCHIVE_DIR="$LOGS_DIR/archive"
ROTATE_DAYS=7        # files older than this get archived
KEEP_DAYS=30         # archive dirs older than this get deleted
TRIM_WEEKS=4         # keep this many weeks in metrics_history.json
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
    file_mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
    year_month=$(date -d "@$file_mtime" '+%Y-%m' 2>/dev/null || date -r "$file_mtime" '+%Y-%m' 2>/dev/null)
    dest_dir="$ARCHIVE_DIR/$year_month"
    dest_file="$dest_dir/$(basename "$file")"
    size_before=$(stat -c %s "$file" 2>/dev/null || stat -f %z "$file" 2>/dev/null || echo 0)

    log "  Archive: $(basename "$file") → archive/$year_month/"
    drylog "mv $file → $dest_file.gz"

    if [[ "$DRY_RUN" == "false" ]]; then
        mkdir -p "$dest_dir"
        mv "$file" "$dest_file"
        gzip -f "$dest_file"
        size_after=$(stat -c %s "${dest_file}.gz" 2>/dev/null || stat -f %z "${dest_file}.gz" 2>/dev/null || echo 0)
        bytes_saved=$(( bytes_saved + size_before - size_after ))
        files_compressed=$(( files_compressed + 1 ))
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

# ── 3. Trim metrics_history.json to TRIM_WEEKS of entries ────────────────────
METRICS_HISTORY="$LOGS_DIR/metrics_history.json"

if [[ -f "$METRICS_HISTORY" ]]; then
    cutoff_date=$(date -u -d "-${TRIM_WEEKS} weeks" '+%Y-%m-%d' 2>/dev/null || echo "")
    entry_count=$(python3 -c "import json; print(len(json.load(open('$METRICS_HISTORY'))))" 2>/dev/null || echo 0)

    if [[ -n "$cutoff_date" && "$entry_count" -gt 0 ]]; then
        log "Trimming metrics_history.json (cutoff: $cutoff_date, current entries: $entry_count)..."
        drylog "Would archive entries older than $cutoff_date"

        if [[ "$DRY_RUN" == "false" ]]; then
            week_label=$(date -u '+%Y-W%V')
            mkdir -p "$ARCHIVE_DIR"
            archive_json="$ARCHIVE_DIR/metrics-${week_label}.json.gz"

            python3 - "$METRICS_HISTORY" "$cutoff_date" "$archive_json" << 'PYEOF'
import json, gzip, sys
path, cutoff, archive_path = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(path))
keep = [r for r in data if r.get("date", "") >= cutoff]
archive = [r for r in data if r.get("date", "") < cutoff]
if archive:
    with gzip.open(archive_path, "wt", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False)
    print(f"[rotate_logs] Archived {len(archive)} entries → {archive_path.split('/')[-1]}")
with open(path, "w", encoding="utf-8") as f:
    json.dump(keep, f, indent=2, ensure_ascii=False)
print(f"[rotate_logs] metrics_history.json: kept {len(keep)}, archived {len(archive)}")
PYEOF
        fi
    else
        log "metrics_history.json: $entry_count entries, nothing to trim (cutoff: ${cutoff_date:-unavailable})"
    fi
fi

# ── 4. Rotate oversized log files ────────────────────────────────────────────
log "Checking log files for rotation..."

ROTATE_LOG_FILES=(
    "$LOGS_DIR/pipeline-failures.log"
    "$PIPELINE_DIR/rejected_articles.log"
)

for log_file in "${ROTATE_LOG_FILES[@]}"; do
    [[ -f "$log_file" ]] || continue
    size=$(stat -c %s "$log_file" 2>/dev/null || echo 0)
    (( size < 10240 )) && continue   # skip files under 10KB

    file_mtime=$(stat -c %Y "$log_file" 2>/dev/null)
    year_month=$(date -d "@$file_mtime" '+%Y-%m' 2>/dev/null || date -u '+%Y-%m')
    dest_dir="$ARCHIVE_DIR/$year_month"
    dest_gz="$dest_dir/$(basename "$log_file").gz"

    log "  Rotate: $(basename "$log_file") ($(( size / 1024 ))KB) → archive/$year_month/"
    drylog "gzip-copy $log_file → $dest_gz, then truncate"

    if [[ "$DRY_RUN" == "false" ]]; then
        mkdir -p "$dest_dir"
        gzip -c "$log_file" > "$dest_gz"
        {
            echo "# Rotated $(date -u)"
            echo "# Previous content archived to archive/$year_month/$(basename "$log_file").gz"
        } > "$log_file"
        bytes_saved=$(( bytes_saved + size ))
    fi
    files_moved=$(( files_moved + 1 ))
done

# ── 5. Summary ────────────────────────────────────────────────────────────────
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
