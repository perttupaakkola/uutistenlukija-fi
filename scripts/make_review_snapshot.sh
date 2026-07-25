#!/usr/bin/env bash
# Create a lean scratch copy of this repository for review/diagnosis work.
#
# Ad-hoc `cp -a` of the working tree produces ~480 MB per copy, dominated by
# pipeline/queues (archived packet JSON, ~320 MB) and build/vendor output that
# no code review needs. Sixty-nine such copies filled /tmp with 14 GB in two
# days (2026-07-25). This helper keeps the same review ergonomics at ~1/4 the
# size, and names the copy so the daily /tmp janitor can reclaim it.
#
# Usage:
#   scripts/make_review_snapshot.sh OPE-NNN [suffix]
#
# Prints the snapshot path on stdout; everything else goes to stderr.
set -euo pipefail

usage() {
  echo "Usage: $0 OPE-NNN [suffix]" >&2
}

if [[ $# -lt 1 || ! $1 =~ ^OPE-[0-9]+$ ]]; then
  usage
  exit 2
fi

issue=$1
suffix=${2:-review}
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Keep the opeNNN- prefix: the daily janitor (crontab, 04:15) reclaims
# /tmp/ope* older than two days.
snapshot_dir="$(mktemp -d "/tmp/ope${issue#OPE-}-${suffix}.XXXXXX")"

# Excluded because reviews never read them and they dominate the byte count.
# Add to this list rather than reintroducing a bare `cp -a`.
excludes=(
  --exclude=.git/                 # use the real repo for history
  --exclude=pipeline/queues/      # archived packet JSON, ~320 MB
  --exclude=pipeline/logs/
  --exclude=pipeline/cache/
  --exclude=pipeline/rejected/    # historical rejected packets, ~32 MB
  --exclude=backups/              # repo-local backup generations, ~108 MB
  --exclude=public/               # Hugo build output; rebuild with verify_hugo.sh
  --exclude=node_modules/
  --exclude=artifacts/
  --exclude=resources/_gen/
  --exclude=.uv-cache/
)

if command -v rsync >/dev/null 2>&1; then
  rsync -a "${excludes[@]}" "$project_dir/" "$snapshot_dir/"
else
  # tar fallback: same exclusions, no rsync dependency.
  tar -C "$project_dir" -cf - \
    --exclude=.git --exclude=pipeline/queues --exclude=pipeline/logs \
    --exclude=pipeline/cache --exclude=pipeline/rejected --exclude=backups \
    --exclude=public --exclude=node_modules \
    --exclude=artifacts --exclude=resources/_gen --exclude=.uv-cache \
    . | tar -C "$snapshot_dir" -xf -
fi

echo "Review snapshot for ${issue}: ${snapshot_dir} ($(du -sh "$snapshot_dir" | cut -f1))" >&2
echo "Remove it when done: rm -rf ${snapshot_dir}" >&2
echo "$snapshot_dir"
