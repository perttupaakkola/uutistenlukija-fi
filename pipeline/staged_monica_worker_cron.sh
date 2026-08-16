#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${STAGED_MONICA_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REMOTE="${STAGED_MONICA_REMOTE:-origin}"
BRANCH="${STAGED_MONICA_BRANCH:-main}"
PYTHON_BIN="${STAGED_MONICA_PYTHON:-python3}"
READY_DIR="pipeline/queues/staged/ready"
WRITING_DIR="pipeline/queues/staged/writing"
OUTBOX_DIR="pipeline/queues/staged/outbox"
FAILED_DIR="pipeline/queues/staged/failed"
MAX_PACKETS="${STAGED_MONICA_MAX_PACKETS:-1}"
MAX_READY_AGE_HOURS="${STAGED_MONICA_MAX_READY_AGE_HOURS:-0}"
WORKER_LOCK_FD=""

log() {
  printf '[%s] [staged-monica-cron] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ERROR $*" >&2
  exit 1
}

is_monica_trajectory_artifact() {
  local path="$1"
  [[ "$path" != */* ]] || return 1
  case "$path" in
    agent:monica:explicit:monica-pipeline-*.trajectory.jsonl | \
      agent:monica:explicit:monica-pipeline-*.trajectory-path.json | \
      agent_monica_explicit_monica-pipeline-*.trajectory.jsonl | \
      agent_monica_explicit_monica-pipeline-*.trajectory-path.json)
      return 0
      ;;
  esac
  return 1
}

untracked_outside_monica_trajectories() {
  local path
  while IFS= read -r -d '' path; do
    is_monica_trajectory_artifact "$path" || printf '%s\n' "$path"
  done < <(git ls-files --others --exclude-standard -z)
}

transactional_worktree_status() {
  git status --porcelain --untracked-files=no
  local path
  while IFS= read -r path; do
    [[ -n "$path" ]] && printf '?? %s\n' "$path"
  done < <(untracked_outside_monica_trajectories)
}

require_clean_tree() {
  local status
  status="$(transactional_worktree_status)"
  [[ -z "$status" ]] || die "worktree is not clean before queue sync: ${status//$'\n'/; }"
}

configure_openclaw_trajectory_storage() {
  [[ -z "${OPENCLAW_TRAJECTORY_DIR:-}" ]] || return 0
  local trajectory_dir
  trajectory_dir="$(git rev-parse --git-path staged-monica-trajectories)"
  mkdir -p -- "$trajectory_dir"
  export OPENCLAW_TRAJECTORY_DIR="$trajectory_dir"
}

acquire_worker_lock() {
  command -v flock >/dev/null 2>&1 || die "flock is required for transactional worker locking"
  local lock_path
  lock_path="$(git rev-parse --git-path staged-monica-worker.lock)"
  exec {WORKER_LOCK_FD}>"$lock_path"
  if ! flock -n "$WORKER_LOCK_FD"; then
    log "SKIP another transactional Monica worker holds the repository lock"
    exit 0
  fi
}

recover_orphaned_writing() {
  shopt -s nullglob
  local writing_files=("$WRITING_DIR"/*.json)
  shopt -u nullglob
  ((${#writing_files[@]} <= 1)) || die "multiple interrupted writing packets require operator review"
  ((${#writing_files[@]} == 1)) || return 0

  local writing_path="${writing_files[0]}"
  local packet ready_path outbox_path failed_path ready_rel expected_blob actual_blob
  packet="$(basename "$writing_path")"
  ready_path="$READY_DIR/$packet"
  outbox_path="$OUTBOX_DIR/$packet"
  failed_path="$FAILED_DIR/$packet"
  ready_rel="$READY_DIR/$packet"
  [[ ! -e "$ready_path" ]] || die "interrupted packet exists in both ready and writing: $packet"
  [[ ! -e "$outbox_path" ]] || die "interrupted packet exists in both writing and outbox: $packet"
  [[ ! -e "$failed_path" ]] || die "interrupted packet exists in both writing and failed: $packet"
  expected_blob="$(git rev-parse "HEAD:$ready_rel" 2>/dev/null)" || die "writing packet is not the committed ready packet: $packet"
  actual_blob="$(git hash-object "$writing_path")"
  [[ "$actual_blob" == "$expected_blob" ]] || die "writing packet changed after admission: $packet"
  mkdir -p "$READY_DIR"
  mv -- "$writing_path" "$ready_path"
  log "restored interrupted packet to ready: $packet"
}

validate_pending_queue_commits() {
  local base="$1" commit subject packet outcome ready_rel destination_rel other_destination_rel
  local -a commits actual_changes expected_changes parent_fields
  mapfile -t commits < <(git rev-list --reverse "$base"..HEAD)
  ((${#commits[@]} > 0)) || return 1
  for commit in "${commits[@]}"; do
    read -r -a parent_fields <<<"$(git rev-list --parents -n 1 "$commit")"
    ((${#parent_fields[@]} == 2)) || return 1
    subject="$(git show -s --format=%s "$commit")"
    case "$subject" in
      "auto(staged): Monica ready to outbox "*.json)
        packet="${subject#auto(staged): Monica ready to outbox }"
        outcome="outbox"
        ;;
      "auto(staged): Monica ready to failed "*.json)
        packet="${subject#auto(staged): Monica ready to failed }"
        outcome="failed"
        ;;
      *) return 1 ;;
    esac
    [[ "$packet" == "$(basename "$packet")" && "$packet" == *.json ]] || return 1
    ready_rel="$READY_DIR/$packet"
    destination_rel="pipeline/queues/staged/$outcome/$packet"
    if [[ "$outcome" == "outbox" ]]; then
      other_destination_rel="$FAILED_DIR/$packet"
    else
      other_destination_rel="$OUTBOX_DIR/$packet"
    fi
    mapfile -t actual_changes < <(
      git diff-tree --no-commit-id --name-status --no-renames -r "$commit" | LC_ALL=C sort
    )
    expected_changes=("A"$'\t'"$destination_rel" "D"$'\t'"$ready_rel")
    mapfile -t expected_changes < <(printf '%s\n' "${expected_changes[@]}" | LC_ALL=C sort)
    [[ "${actual_changes[*]}" == "${expected_changes[*]}" ]] || return 1
    git cat-file -e "HEAD:$destination_rel" 2>/dev/null || return 1
    if git cat-file -e "HEAD:$ready_rel" 2>/dev/null; then
      return 1
    fi
    if git cat-file -e "HEAD:$other_destination_rel" 2>/dev/null; then
      return 1
    fi
  done
}

reject_duplicate_destinations() {
  shopt -s nullglob
  local ready_files=("$READY_DIR"/*.json)
  shopt -u nullglob
  local ready_path packet
  for ready_path in "${ready_files[@]}"; do
    packet="$(basename "$ready_path")"
    [[ ! -e "$OUTBOX_DIR/$packet" ]] || die "ready packet already has an outbox destination: $packet"
    [[ ! -e "$FAILED_DIR/$packet" ]] || die "ready packet already has a failed destination: $packet"
  done
}

sync_from_remote() {
  git fetch "$REMOTE" "$BRANCH"
  local remote_ref="$REMOTE/$BRANCH" head remote_head
  head="$(git rev-parse HEAD)"
  remote_head="$(git rev-parse "$remote_ref")"
  if [[ "$head" == "$remote_head" ]]; then
    return 0
  fi
  if git merge-base --is-ancestor HEAD "$remote_ref"; then
    git merge --ff-only "$remote_ref"
    return 0
  fi
  local base subject packet
  base="$(git merge-base HEAD "$remote_ref")"
  if validate_pending_queue_commits "$base"; then
    subject="$(git log -1 --format=%s)"
    packet="${subject##* }"
    [[ "$packet" == *.json ]] || die "pending queue commit has no recoverable packet id"
    log "retrying previously committed queue-only transition"
    reconcile_and_push "$packet" "$base"
    return 0
  fi
  die "local HEAD and $remote_ref diverged outside a validated queue-only retry"
}

stage_queue_pair() {
  local ready_rel="$1" destination_rel="$2"
  local -a staged_changes expected_changes
  git update-index --remove -- "$ready_rel"
  git add -f -- "$destination_rel"

  local unstaged untracked
  unstaged="$(git diff --name-only)"
  [[ -z "$unstaged" ]] || die "unstaged changes remain outside the queue transaction: ${unstaged//$'\n'/; }"
  untracked="$(untracked_outside_monica_trajectories)"
  [[ -z "$untracked" ]] || die "untracked files remain outside the queue transaction: ${untracked//$'\n'/; }"

  mapfile -t staged_changes < <(
    git diff --cached HEAD --name-status --no-renames | LC_ALL=C sort
  )
  expected_changes=("A"$'\t'"$destination_rel" "D"$'\t'"$ready_rel")
  mapfile -t expected_changes < <(printf '%s\n' "${expected_changes[@]}" | LC_ALL=C sort)
  [[ "${staged_changes[*]}" == "${expected_changes[*]}" ]] || die "staged delta is not an exact ready deletion plus destination addition"
  git diff --cached --check
}

reconcile_and_push() {
  local packet="$1" base_remote="$2" attempt remote_ref="$REMOTE/$BRANCH" remote_head
  for attempt in 1 2; do
    git fetch "$REMOTE" "$BRANCH"
    remote_head="$(git rev-parse "$remote_ref")"
    if [[ "$(git rev-parse HEAD)" == "$remote_head" ]]; then
      require_clean_tree
      log "remote already contains ready transition packet: $packet"
      return 0
    fi
    if git merge-base --is-ancestor HEAD "$remote_ref"; then
      git merge --ff-only "$remote_ref"
      require_clean_tree
      log "remote already contains ready transition packet: $packet"
      return 0
    fi
    if [[ "$remote_head" != "$base_remote" ]]; then
      if ! git -c merge.directoryRenames=false rebase "$remote_ref"; then
        git rebase --abort || true
        die "queue transition conflicted with concurrent main update"
      fi
      base_remote="$remote_head"
    fi
    validate_pending_queue_commits "$base_remote" || die "queue transition changed semantics after remote reconciliation"
    if git push "$REMOTE" HEAD:"$BRANCH"; then
      git fetch "$REMOTE" "$BRANCH"
      if [[ "$(git rev-parse HEAD)" != "$(git rev-parse "$remote_ref")" ]]; then
        git merge-base --is-ancestor HEAD "$remote_ref" || die "post-push remote verification lost the queue transition"
        git merge --ff-only "$remote_ref"
      fi
      require_clean_tree
      log "pushed ready transition packet: $packet"
      return 0
    fi
    log "push race on attempt $attempt; refreshing exact main"
  done
  die "queue transition push failed after bounded retry"
}

resume_completed_transition() {
  [[ -n "$(transactional_worktree_status)" ]] || return 0

  local -a deleted_ready
  mapfile -t deleted_ready < <(git diff HEAD --diff-filter=D --name-only -- "$READY_DIR")
  ((${#deleted_ready[@]} == 1)) || die "worktree is not clean and is not one resumable ready transition"
  local ready_rel="${deleted_ready[0]}" packet outbox_rel failed_rel writing_rel destination_rel outcome base_remote
  packet="$(basename "$ready_rel")"
  [[ "$ready_rel" == "$READY_DIR/$packet" && "$packet" == *.json ]] || die "invalid interrupted ready path: $ready_rel"
  outbox_rel="$OUTBOX_DIR/$packet"
  failed_rel="$FAILED_DIR/$packet"
  writing_rel="$WRITING_DIR/$packet"
  if [[ -f "$outbox_rel" && -f "$failed_rel" ]]; then
    die "interrupted transition has both outbox and failed destinations: $packet"
  elif [[ -f "$outbox_rel" ]]; then
    destination_rel="$outbox_rel"
    outcome="outbox"
  elif [[ -f "$failed_rel" ]]; then
    destination_rel="$failed_rel"
    outcome="failed"
  else
    die "interrupted transition has no matching outbox or failed packet: $packet"
  fi
  [[ ! -e "$writing_rel" ]] || die "interrupted transition still has a writing packet: $packet"

  stage_queue_pair "$ready_rel" "$destination_rel"
  base_remote="$(git rev-parse "$REMOTE/$BRANCH")"
  git commit -m "auto(staged): Monica ready to $outcome $packet"
  log "resuming completed ready-to-$outcome transition: $packet"
  reconcile_and_push "$packet" "$base_remote"
}

restore_after_worker_failure() {
  local rc="$1"
  if recover_orphaned_writing; then
    if [[ -z "$(git status --porcelain --untracked-files=all)" ]]; then
      log "worker failed rc=$rc; committed packet restored to ready"
    else
      log "worker failed rc=$rc; queue state requires operator review" >&2
    fi
  fi
  return "$rc"
}

cd "$PROJECT_DIR"
[[ "$MAX_PACKETS" == "1" ]] || die "transactional wrapper requires STAGED_MONICA_MAX_PACKETS=1"
git rev-parse --is-inside-work-tree >/dev/null
acquire_worker_lock
recover_orphaned_writing
resume_completed_transition
require_clean_tree
sync_from_remote
require_clean_tree
reject_duplicate_destinations

shopt -s nullglob
before_ready=("$READY_DIR"/*.json)
shopt -u nullglob
if ((${#before_ready[@]} == 0)); then
  log "no ready packets"
  exit 0
fi

base_remote="$(git rev-parse "$REMOTE/$BRANCH")"
worker_rc=0
configure_openclaw_trajectory_storage
"$PYTHON_BIN" pipeline/staged_publish.py monica-worker \
  --max-packets 1 \
  --max-ready-age-hours "$MAX_READY_AGE_HOURS" || worker_rc=$?
if ((worker_rc != 0)); then
  restore_after_worker_failure "$worker_rc"
  exit "$worker_rc"
fi

removed=()
for path in "${before_ready[@]}"; do
  [[ -e "$path" ]] || removed+=("$path")
done
((${#removed[@]} == 1)) || die "expected exactly one ready packet removal; got ${#removed[@]}"
packet="$(basename "${removed[0]}")"
ready_rel="$READY_DIR/$packet"
outbox_rel="$OUTBOX_DIR/$packet"
failed_rel="$FAILED_DIR/$packet"
writing_rel="$WRITING_DIR/$packet"
if [[ -f "$outbox_rel" && -f "$failed_rel" ]]; then
  die "worker produced both outbox and failed destinations: $packet"
elif [[ -f "$outbox_rel" ]]; then
  destination_rel="$outbox_rel"
  outcome="outbox"
elif [[ -f "$failed_rel" ]]; then
  destination_rel="$failed_rel"
  outcome="failed"
else
  die "worker did not create expected outbox or failed packet: $packet"
fi
[[ ! -e "$writing_rel" ]] || die "packet remains in writing after successful worker exit: $packet"

stage_queue_pair "$ready_rel" "$destination_rel"
git commit -m "auto(staged): Monica ready to $outcome $packet"
reconcile_and_push "$packet" "$base_remote"
