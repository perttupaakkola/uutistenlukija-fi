
## [ERR-20260508-001] wrong_workdir_pipeline_checks

**Logged**: 2026-05-08T15:31:30Z
**Priority**: medium
**Status**: pending
**Area**: ops

### Summary
Linear OPE reconciliation initially ran uutistenlukija pipeline health commands from the workspace root, where `scripts/cron_health_monitor.py` and `pipeline/health_check.py` do not exist.

### Error
```
python3: can't open file '/home/pertt/.openclaw/workspace/scripts/cron_health_monitor.py': [Errno 2] No such file or directory
find: ‘pipeline’: No such file or directory
```

### Context
- Command attempted during OPE reconciliation cycle.
- Correct project root is `/home/pertt/.openclaw/workspace/projects/uutistenlukija`.

### Suggested Fix
Use `projects/uutistenlukija` as `workdir` for uutistenlukija pipeline checks/tests, or add a small wrapper in workspace root if this recurs.

### Metadata
- Reproducible: yes
- Related Files: projects/uutistenlukija/scripts/cron_health_monitor.py, projects/uutistenlukija/pipeline/health_check.py

---

## [ERR-20260508-002] project_hugo_not_on_path

**Logged**: 2026-05-08T15:35:20Z
**Priority**: low
**Status**: pending
**Area**: tests

### Summary
Running `hugo --minify --quiet` from the uutistenlukija project failed because `hugo` was not on PATH in this runtime.

### Error
```
/bin/bash: line 1: hugo: command not found
```

### Context
- Workspace has a Hugo binary at `/home/pertt/.openclaw/workspace/hugo`.
- Use the absolute binary for project build verification in cron/sandbox sessions.

### Suggested Fix
Prefer `/home/pertt/.openclaw/workspace/hugo --minify --quiet` in automated checks unless PATH is known to include the workspace binary.

### Metadata
- Reproducible: yes
- Related Files: /home/pertt/.openclaw/workspace/hugo

---

## [ERR-20260512-1529] wrong_cwd_uutistenlukija_check

**Logged**: 2026-05-12T15:29:00Z
**Priority**: medium
**Status**: pending
**Area**: ops

### Summary
A reconciliation health check used `git -C projects/uutistenlukija` while already running from the uutistenlukija directory, producing a nested non-existent path.

### Error
```text
fatal: cannot change to 'projects/uutistenlukija': No such file or directory
```

### Context
- Command attempted from `/home/pertt/.openclaw/workspace/projects/uutistenlukija` but also passed `git -C projects/uutistenlukija`.
- Correct pattern: either run from workspace root with `git -C projects/uutistenlukija ...` or run from project root with plain `git ...`.

### Suggested Fix
For project health checks, set workdir explicitly to `/home/pertt/.openclaw/workspace/projects/uutistenlukija` and avoid nested `git -C` arguments.

### Metadata
- Reproducible: yes
- Related Files: projects/uutistenlukija
- See Also: prior cwd mistake logged 2026-05-12 around OPE reconciliation

---
