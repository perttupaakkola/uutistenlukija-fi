#!/bin/bash
# Shared retained-entrypoint guard. No checkout/reset/stash/rebase or auto-retry.
# Dirty/stale and postwork failures preserve evidence for explicit reconciliation.
legacy_die() { printf '[legacy-git] %s\n' "$*" >&2; exit 1; }
legacy_identity() {
    local root branch remote push_remote
    root=$(git rev-parse --show-toplevel) || legacy_die 'repository lookup failed'
    [[ "$root" == "$PROJECT_DIR" ]] || legacy_die 'wrong repository root'
    branch=$(git symbolic-ref --quiet HEAD) || legacy_die 'detached/unreadable branch'
    [[ "$branch" == refs/heads/main ]] || legacy_die 'main branch required'
    remote=$(git remote get-url --all origin) || legacy_die 'origin lookup failed'
    push_remote=$(git remote get-url --push --all origin) || legacy_die 'push origin lookup failed'
    case "$remote" in
        https://github.com/perttupaakkola/uutistenlukija-fi.git|git@github.com:perttupaakkola/uutistenlukija-fi.git) ;;
        *) legacy_die 'unexpected configured origin' ;;
    esac
    [[ "$push_remote" == "$remote" ]] || legacy_die 'different/multiple push origins'
}
legacy_fetch() {
    git fetch --no-tags origin '+refs/heads/main:refs/remotes/origin/main' || legacy_die 'fetch failed'
    LEGACY_REMOTE=$(git rev-parse --verify 'refs/remotes/origin/main^{commit}') || legacy_die 'main ref lookup failed'
}
legacy_clean() {
    local status
    status=$(git status --porcelain=v1 --untracked-files=all) || legacy_die 'status failed'
    [[ -z "$status" ]] || legacy_die 'preexisting tracked/untracked changes; preserved'
}
legacy_admit() {
    legacy_identity
    local common worker_lock
    common=$(git rev-parse --path-format=absolute --git-common-dir) || legacy_die 'common directory lookup failed'
    worker_lock=$(git rev-parse --git-path staged-monica-worker.lock) || legacy_die 'worker lock lookup failed'
    exec {LEGACY_LOCK_FD}>"$common/legacy-publishing.lock"
    flock -n "$LEGACY_LOCK_FD" || legacy_die 'another legacy publisher holds lock'
    exec {LEGACY_WORKER_FD}>"$worker_lock"
    flock -n "$LEGACY_WORKER_FD" || legacy_die 'transactional worker holds checkout lock'
    [[ ! -e "$PROJECT_DIR/pipeline/.pipeline_lock" ]] || legacy_die 'legacy PID lock exists; operator review required'
    legacy_clean
    LEGACY_BASE=$(git rev-parse --verify 'HEAD^{commit}') || legacy_die 'HEAD lookup failed'
    legacy_fetch
    [[ "$LEGACY_BASE" == "$LEGACY_REMOTE" ]] || legacy_die 'checkout is not exact current main; no work admitted'
    legacy_clean
}
legacy_postwork_check() {
    legacy_identity
    local head
    head=$(git rev-parse --verify 'HEAD^{commit}') || legacy_die 'postwork HEAD lookup failed'
    [[ "$head" == "$LEGACY_BASE" ]] || legacy_die 'local HEAD changed during work; preserved'
    legacy_fetch
    [[ "$LEGACY_REMOTE" == "$LEGACY_BASE" ]] || legacy_die 'main advanced during work; output preserved, no reconciliation attempted'
}
legacy_commit_and_push() {
    legacy_postwork_check
    local status line path rc
    # Do not reset an index another process has changed, or include staged source.
    if git diff --cached --quiet; then :; else
        rc=$?; legacy_die "index changed or diff failed ($rc); preserved"
    fi
    status=$(git -c core.quotePath=true status --porcelain=v1 --untracked-files=all) || legacy_die 'postwork status failed'
    [[ -n "$status" ]] || { printf '[legacy-git] no changes\n'; return; }
    ARTICLE_COUNT=0
    local -a paths=()
    while IFS= read -r line; do
        path=${line:3}
        # Quoted/newline/rename paths intentionally rejected rather than guessed.
        case "${line:0:2}" in ' M'|'??') ;; *) legacy_die 'unsupported output status; preserved' ;; esac
        case "$path" in
            content/*|public/*|static/images/articles/*|static/api/*|static/metrics/*|static/search-index.json|pipeline/metrics.jsonl) ;;
            *) legacy_die 'unexpected source/output change; preserved' ;;
        esac
        if [[ "${line:0:2}" == "??" && "$path" == content/posts/* ]]; then
            ARTICLE_COUNT=$((ARTICLE_COUNT + 1))
        fi
        paths+=("$path")
    done <<< "$status"
    git add -- "${paths[@]}" || legacy_die 'staging failed; output preserved'
    git commit -m "Auto-publish: guarded legacy output ($(date -u '+%Y-%m-%d %H:%M UTC'))" || legacy_die 'commit failed; output preserved'
    local commit
    commit=$(git rev-parse --verify 'HEAD^{commit}') || legacy_die 'commit lookup failed'
    # Normal push only. A race fails, retaining the local commit, never rebases it.
    git push origin "$commit:refs/heads/main" || legacy_die 'push failed; local commit preserved'
    legacy_fetch
    git merge-base --is-ancestor "$commit" "$LEGACY_REMOTE" || legacy_die 'pushed commit not verified on main'
    printf '[legacy-git] commit present on remote (deployment not verified)\n'
}
