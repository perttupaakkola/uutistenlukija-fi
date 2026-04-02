# Operator Playbook: Clean Tree Before Automation

**Date:** 2026-04-02
**Author:** Monica (analysis) + Felix
**For:** Max (ops) + Felix (pipeline cron)

## Root Cause
Recurring failure: automation writes into tracked repo files → next `git pull --rebase` hits dirty working tree → pipeline blocks. This has happened multiple times.

## Rules

### 1. Pre-flight check before every cron/auto pull
```bash
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "PIPELINE BLOCKED: local changes present" >&2
    exit 1
fi
```
Add this to the top of `auto_publish.sh` and any script that does `git pull`.

### 2. Runtime files stay out of tracked paths
- Logs, state files, temp outputs, reports → outside repo OR in `.gitignore`d paths only
- If a cron/script writes into a tracked file, that is a bug — fix immediately
- Allowlisted paths for generated content: `content/` (articles only, via pipeline)

### 3. One recovery path
- Operator-owned generated drift in allowlisted paths → `git checkout -- <path>` automatically
- Anything else → stop, alert Felix, human resolves
- No automatic stash/rebase magic — that hides problems

## Action items
- [ ] Max: audit `auto_publish.sh` for the pre-flight check — add if missing
- [ ] Max: audit all cron scripts for writes into tracked files
- [ ] Felix: add runtime paths to `.gitignore` if any are missing
