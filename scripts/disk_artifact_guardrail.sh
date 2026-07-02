#!/usr/bin/env bash
# Inventory and quarantine regenerated disk artifacts that commonly trip root
# pressure alerts. Default mode is read-only; --apply moves only approved tmp
# build directories into a manifest-backed quarantine.
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/home/pertt/.openclaw/workspace/projects/uutistenlukija}"
TMP_ROOT="${TMP_ROOT:-/tmp}"
UV_CACHE="${UV_CACHE:-/home/pertt/.cache/uv}"
QUARANTINE_ROOT="${DISK_ARTIFACT_QUARANTINE_ROOT:-$PROJECT_ROOT/data/disk_artifact_guardrail/quarantine}"
MANIFEST_ROOT="${DISK_ARTIFACT_MANIFEST_ROOT:-$PROJECT_ROOT/data/disk_artifact_guardrail/manifests}"
MIN_TMP_AGE_MINUTES="${DISK_ARTIFACT_MIN_TMP_AGE_MINUTES:-30}"
APPLY=0

usage() {
    cat <<'EOF'
Usage: scripts/disk_artifact_guardrail.sh [--apply]

Default mode is read-only and prints a compact evidence report.

With --apply, the script moves only regenerated Uutistenlukija tmp build
directories matching /tmp/uut* or /tmp/uutistenlukija-* into
data/disk_artifact_guardrail/quarantine/ and writes a manifest. It does not
delete uv cache, secrets, source, .git, browser profiles, backups, live queues,
Hermes/OpenClaw DB/state, or project workspaces.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply)
            APPLY=1
            ;;
        --dry-run)
            APPLY=0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

now="$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$MANIFEST_ROOT"
manifest="$MANIFEST_ROOT/$now.tsv"

root_df="$(df -h / | awk 'NR==2 {print $2, $3, $4, $5, $6}')"
root_df_bytes="$(df -B1 / | awk 'NR==2 {print $2, $3, $4, $5, $6}')"
uv_size="$(du -sh "$UV_CACHE" 2>/dev/null | awk '{print $1}' || true)"
uv_size="${uv_size:-missing}"

{
    printf 'timestamp\t%s\n' "$now"
    printf 'mode\t%s\n' "$([ "$APPLY" -eq 1 ] && echo apply || echo dry-run)"
    printf 'root_df_h\t%s\n' "$root_df"
    printf 'root_df_bytes\t%s\n' "$root_df_bytes"
    printf 'uv_cache\t%s\t%s\n' "$UV_CACHE" "$uv_size"
    printf 'min_tmp_age_minutes\t%s\n' "$MIN_TMP_AGE_MINUTES"
} > "$manifest"

echo "timestamp=$now"
echo "mode=$([ "$APPLY" -eq 1 ] && echo apply || echo dry-run)"
echo "root_df_h=$root_df"
echo "root_df_bytes=$root_df_bytes"
echo "uv_cache_size=$uv_size"
echo "manifest=$manifest"

tmp_candidates=()
while IFS= read -r -d '' path; do
    tmp_candidates+=("$path")
done < <(
    find "$TMP_ROOT" -xdev -mindepth 1 -maxdepth 1 -type d \
        \( -name 'uut*' -o -name 'uutistenlukija-*' \) \
        -mmin +"$MIN_TMP_AGE_MINUTES" -print0 2>/dev/null
)

if [ "${#tmp_candidates[@]}" -eq 0 ]; then
    echo "tmp_candidates=0"
    printf 'tmp_candidates\t0\n' >> "$manifest"
else
    echo "tmp_candidates=${#tmp_candidates[@]}"
    printf 'tmp_candidates\t%s\n' "${#tmp_candidates[@]}" >> "$manifest"
fi

for path in "${tmp_candidates[@]}"; do
    real="$(readlink -f -- "$path")"
    case "$real" in
        /tmp/uut*|/tmp/uutistenlukija-*) ;;
        *)
            echo "skip_unsafe_tmp_path=$path real=$real"
            printf 'skip_unsafe_tmp_path\t%s\t%s\n' "$path" "$real" >> "$manifest"
            continue
            ;;
    esac
    if [ -e "$real/.git" ]; then
        echo "skip_git_tree=$real"
        printf 'skip_git_tree\t%s\n' "$real" >> "$manifest"
        continue
    fi
    size="$(du -sh "$real" 2>/dev/null | awk '{print $1}' || true)"
    mtime="$(stat -c '%y' "$real" 2>/dev/null || true)"
    if timeout 10s lsof +D "$real" >/tmp/disk_artifact_guardrail_lsof.$$ 2>/dev/null; then
        if [ -s /tmp/disk_artifact_guardrail_lsof.$$ ]; then
            echo "skip_open_handles=$real"
            printf 'skip_open_handles\t%s\t%s\t%s\n' "$real" "$size" "$mtime" >> "$manifest"
            rm -f /tmp/disk_artifact_guardrail_lsof.$$
            continue
        fi
    fi
    rm -f /tmp/disk_artifact_guardrail_lsof.$$
    printf 'tmp_candidate\t%s\t%s\t%s\n' "$real" "$size" "$mtime" >> "$manifest"
    echo "tmp_candidate path=$real size=$size mtime=$mtime"
    if [ "$APPLY" -eq 1 ]; then
        dest_dir="$QUARANTINE_ROOT/$now"
        mkdir -p "$dest_dir"
        dest="$dest_dir/${real##*/}"
        mv -- "$real" "$dest"
        printf 'quarantined\t%s\t%s\n' "$real" "$dest" >> "$manifest"
        echo "quarantined $real -> $dest"
    fi
done

cat <<EOF
uv_policy=manifest-only; use docs/uv-cache-maintenance-runbook.md before uv deletion because mapped uv files can affect Hermes/OpenClaw.
tmp_policy=$([ "$APPLY" -eq 1 ] && echo "quarantine-only" || echo "dry-run only")
protected_paths=secrets,source,.git,browser_profiles,backups,live_queues,Hermes/OpenClaw_DB_state,project_workspaces
EOF
