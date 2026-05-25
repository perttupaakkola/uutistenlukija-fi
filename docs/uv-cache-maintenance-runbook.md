# UV Cache Maintenance Window Runbook

Updated: 2026-05-25
Owner: Max
Scope: `/home/pertt/.cache/uv`

## Purpose

Use this runbook to safely reclaim disk space from the uv cache after OPE-131 found `/home/pertt/.cache/uv` at about 13G and previously mapped by the live Hermes gateway process. The cache is a valid cleanup target, but cleanup must happen only during an approved maintenance window because removing mapped shared objects can destabilize Hermes/OpenClaw.

Do not use this runbook as approval to delete files, kill processes, or restart gateways. Get explicit Felix/Perttu maintenance approval first.

## Preconditions

- Approval exists for a Hermes/OpenClaw maintenance window.
- Active user-facing work has been paused or accepted as interruptible.
- The target path is exactly `/home/pertt/.cache/uv`.
- The operator is prepared to abort if any guard fails.

## Preflight Evidence

Record all output before making any change:

```bash
date -u
df -h / /home
du -sh /home/pertt/.cache/uv
find /home/pertt/.cache/uv -maxdepth 0 -xdev -type d -printf 'path=%p type=%y dev=%D inode=%i\n'
readlink -f /home/pertt/.cache/uv
findmnt -T /home/pertt/.cache/uv -o TARGET,SOURCE,FSTYPE,OPTIONS
python3 - <<'PY'
from pathlib import Path
p = Path("/home/pertt/.cache/uv")
print("exists=", p.exists())
print("is_dir=", p.is_dir())
print("is_symlink=", p.is_symlink())
print("realpath=", p.resolve(strict=False))
print("parent=", p.parent)
print("parent_realpath=", p.parent.resolve(strict=False))
print("target_ok=", str(p.resolve(strict=False)) == "/home/pertt/.cache/uv")
PY
find /home/pertt/.cache/uv -xdev \( -name .git -o -name .hg -o -name .svn \) -print
find /home/pertt/.cache/uv -xdev -type l -printf '%p -> %l\n' | sed -n '1,120p'
systemctl --user --no-pager --plain status hermes-gateway.service openclaw-gateway.service
systemctl --user --no-pager --plain list-units '*hermes*' '*openclaw*'
systemctl --user --no-pager --plain list-timers '*hermes*' '*openclaw*'
pgrep -af 'hermes|openclaw|gateway'
```

Check live use of the cache with bounded commands. Prefer `/proc/*/maps` because `lsof +D` can be slow on this cache tree:

```bash
for p in /proc/[0-9]*; do
  pid=${p##*/}
  if [ -r "$p/maps" ] && grep -q '/home/pertt/.cache/uv' "$p/maps" 2>/dev/null; then
    printf 'PID %s ' "$pid"
    tr '\0' ' ' < "$p/cmdline" | cut -c1-240
    printf '\n'
    grep '/home/pertt/.cache/uv' "$p/maps" | sed -n '1,10p'
  fi
done
timeout 20s lsof +D /home/pertt/.cache/uv 2>/dev/null | sed -n '1,120p'; echo "lsof_rc=${PIPESTATUS[0]}"
```

Active-session context should also be recorded so the maintenance window has a visible interruption risk snapshot:

```bash
openclaw sessions --all-agents --active 60 --limit 20
```

If the CLI shape changes, use the OpenClaw session list/status tool and record the equivalent active-session output.

## Abort Criteria

Abort before deletion if any condition is true:

- No explicit maintenance approval exists.
- `/home/pertt/.cache/uv` is missing, is not a directory, is a symlink, or resolves anywhere except `/home/pertt/.cache/uv`.
- `findmnt -T /home/pertt/.cache/uv` does not resolve to the expected local filesystem.
- Any required command indicates the target would include parent directories, workspaces, backups, snapshots, active repositories, queues, Hermes venv, Monica log DB, or OpenClaw state outside uv cache.
- `/proc/*/maps` or bounded `lsof` shows live mappings under `/home/pertt/.cache/uv` after the planned restart.
- Hermes/OpenClaw gateway restart fails, health does not return, or active sessions are not in the expected maintenance state.
- Disk free space is already healthy enough that the cleanup risk is no longer justified.

## Safe Stop And Restart

Use service management, not direct process kills:

```bash
systemctl --user --no-pager --plain status hermes-gateway.service openclaw-gateway.service
systemctl --user stop hermes-gateway.service
systemctl --user restart openclaw-gateway.service
systemctl --user start hermes-gateway.service
systemctl --user --no-pager --plain status hermes-gateway.service openclaw-gateway.service
```

If the approved window only permits restarting Hermes, do not restart OpenClaw gateway. In that case:

```bash
systemctl --user restart hermes-gateway.service
systemctl --user --no-pager --plain status hermes-gateway.service
```

After services return, rerun the `/proc/*/maps` and bounded `lsof` checks. Cleanup may proceed only if no process maps or opens files under `/home/pertt/.cache/uv`.

## Cleanup Command

Run only after all preflight and post-restart guards pass:

```bash
rm -rf --one-file-system -- /home/pertt/.cache/uv
```

Do not delete `/home/pertt/.cache`, parent directories, workspaces, backups, snapshots, active repos, queues, Hermes venv, Monica log DB, or OpenClaw state.

## Rollback Notes

There is no meaningful file-level rollback for a cache deletion. Recovery is operational:

- If cleanup was performed and a Python workload later needs packages, allow uv to repopulate its cache.
- If Hermes/OpenClaw health regresses, restart the affected user service through `systemctl --user restart ...`; do not restore stale cache files over a running process.
- If package resolution fails after cleanup, rerun the affected deployment/bootstrap command so uv rebuilds the cache from package indexes.
- If service restart fails, stop further cleanup work and preserve logs from:

```bash
journalctl --user -u hermes-gateway.service -n 200 --no-pager
journalctl --user -u openclaw-gateway.service -n 200 --no-pager
systemctl --user --no-pager --plain status hermes-gateway.service openclaw-gateway.service
```

## Post-Cleanup Verification

Record evidence after cleanup or after aborting:

```bash
df -h / /home
du -sh /home/pertt/.cache/uv 2>&1 || true
systemctl --user --no-pager --plain status hermes-gateway.service openclaw-gateway.service
pgrep -af 'hermes|openclaw|gateway'
cd /home/pertt/.openclaw/workspace/projects/uutistenlukija
./scripts/disk_space_monitor.sh --dry-run --no-alert
```

Post the Linear evidence with:

- Whether cleanup was executed or aborted.
- Exact approval source.
- Before/after `df -h / /home`.
- Before/after uv cache size.
- Paths touched and paths explicitly untouched.
- Gateway/session status before and after.
- Disk monitor dry-run status.
- Any follow-up needed.
