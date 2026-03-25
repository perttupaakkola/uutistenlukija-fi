#!/usr/bin/env python3
"""
preflight_check.py — pre-flight validation before each auto_publish.sh cycle.

Checks (in order):
  1. Execute bit on all .sh files in pipeline/ and scripts/ — auto-fix if missing
  2. Stale lock file older than 30min — kill stuck PID and remove lock
  3. Syntax check: scanner.py, rewriter.py, publisher.py via py_compile
  4. Required env vars present: DISCORD_PIPELINE_WEBHOOK, OPENAI_API_KEY
  5. Disk space ≥ 500MB free on project filesystem

Output:
  pipeline/logs/preflight.json — JSON summary of all checks
  Stdout — human-readable summary
  Exit 0  — all checks passed (or auto-fixed, no hard failures)
  Exit 1  — hard failure: pipeline should not run

Discord alert only on hard failures (not on auto-fixed issues like +x restore).

Usage:
    python3 pipeline/preflight_check.py [--dry-run]
    # Called by auto_publish.sh at the top, before the lock check
"""

import json
import os
import py_compile
import shutil
import signal
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
PIPELINE_DIR = Path(__file__).parent
PROJECT_DIR  = PIPELINE_DIR.parent
SCRIPTS_DIR  = PROJECT_DIR / "scripts"
LOCK_FILE    = PIPELINE_DIR / ".pipeline_lock"
LOG_DIR      = PIPELINE_DIR / "logs"
OUTPUT_FILE  = LOG_DIR / "preflight.json"

# ── Config ────────────────────────────────────────────────────────────────────
STALE_LOCK_MINUTES   = 30
MIN_FREE_DISK_MB     = 500
SYNTAX_CHECK_FILES   = ["scanner.py", "rewriter.py", "publisher.py", "run_pipeline.py"]
REQUIRED_ENV_VARS    = ["DISCORD_PIPELINE_WEBHOOK", "OPENAI_API_KEY"]

WEBHOOK = os.environ.get("DISCORD_PIPELINE_WEBHOOK", "")


# ── Discord alert ─────────────────────────────────────────────────────────────

def _discord_alert(message: str) -> None:
    if not WEBHOOK:
        return
    try:
        import urllib.request
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            WEBHOOK, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        print(f"[preflight] Discord alert failed: {e}", file=sys.stderr)


# ── Check functions ───────────────────────────────────────────────────────────

def check_execute_bits(dry_run: bool = False) -> dict:
    """Check all .sh files in pipeline/ and scripts/ have execute bit. Auto-fix."""
    fixed = []
    missing = []

    for search_dir in [PIPELINE_DIR, SCRIPTS_DIR]:
        if not search_dir.exists():
            continue
        for sh_file in search_dir.glob("*.sh"):
            current_mode = sh_file.stat().st_mode
            if not (current_mode & stat.S_IXUSR):
                missing.append(str(sh_file.relative_to(PROJECT_DIR)))
                if not dry_run:
                    sh_file.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    fixed.append(str(sh_file.relative_to(PROJECT_DIR)))

    status = "ok"
    detail = None
    if fixed:
        status = "auto_fixed"
        detail = f"Restored +x on {len(fixed)} file(s): {', '.join(fixed)}"
        print(f"[preflight] ✅ execute_bits: {detail}")
    elif missing and dry_run:
        status = "would_fix"
        detail = f"Would fix {len(missing)} file(s): {', '.join(missing)}"
        print(f"[preflight] 🔧 execute_bits (dry-run): {detail}")
    else:
        print(f"[preflight] ✅ execute_bits: all .sh files have +x")

    return {"check": "execute_bits", "status": status, "detail": detail,
            "fixed": fixed, "hard_failure": False}


def check_stale_lock(dry_run: bool = False) -> dict:
    """Check for stale lock files. Kill stuck PID if lock is older than threshold."""
    if not LOCK_FILE.exists():
        print("[preflight] ✅ lock_file: no lock present")
        return {"check": "lock_file", "status": "ok", "detail": None, "hard_failure": False}

    try:
        lines = LOCK_FILE.read_text().splitlines()
        lock_pid = int(lines[0].strip()) if lines else 0
        lock_ts  = lines[1].strip() if len(lines) > 1 else ""
    except Exception as e:
        # Unreadable lock — remove it
        if not dry_run:
            LOCK_FILE.unlink(missing_ok=True)
        return {"check": "lock_file", "status": "auto_fixed",
                "detail": f"Unreadable lock removed: {e}", "hard_failure": False}

    # Check if PID is still alive
    pid_alive = False
    try:
        os.kill(lock_pid, 0)
        pid_alive = True
    except (ProcessLookupError, PermissionError):
        pid_alive = False

    if not pid_alive:
        # Dead PID — remove stale lock
        if not dry_run:
            LOCK_FILE.unlink(missing_ok=True)
        detail = f"Stale lock (PID {lock_pid} dead, started {lock_ts}) removed"
        print(f"[preflight] ⚠️  lock_file: {detail}")
        return {"check": "lock_file", "status": "auto_fixed", "detail": detail,
                "lock_pid": lock_pid, "lock_ts": lock_ts, "hard_failure": False}

    # PID alive — check age
    age_secs = 0
    if lock_ts:
        try:
            ts_dt = datetime.fromisoformat(lock_ts.replace("Z", "+00:00"))
            age_secs = int((datetime.now(timezone.utc) - ts_dt).total_seconds())
        except Exception:
            pass

    if age_secs > STALE_LOCK_MINUTES * 60:
        age_min = age_secs // 60
        if not dry_run:
            # SIGTERM → 2s → SIGKILL
            try:
                os.kill(lock_pid, signal.SIGTERM)
                time.sleep(2)
                os.kill(lock_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            LOCK_FILE.unlink(missing_ok=True)

        detail = f"Stuck pipeline killed: PID {lock_pid} running {age_min}min (limit: {STALE_LOCK_MINUTES}min)"
        print(f"[preflight] ⚠️  lock_file: {detail}")
        _discord_alert(
            f"⚠️ **Preflight: stuck pipeline killed** — PID {lock_pid} was running "
            f"for {age_min} minutes. Lock removed, new run starting."
        )
        return {"check": "lock_file", "status": "auto_fixed", "detail": detail,
                "lock_pid": lock_pid, "lock_ts": lock_ts, "age_secs": age_secs,
                "hard_failure": False}

    # Lock is alive and fresh — pipeline is running normally
    detail = f"Pipeline running (PID {lock_pid}, started {lock_ts}, age {age_secs}s)"
    print(f"[preflight] ✅ lock_file: {detail}")
    return {"check": "lock_file", "status": "ok", "detail": detail,
            "lock_pid": lock_pid, "lock_ts": lock_ts,
            "hard_failure": False, "pipeline_running": True}


def check_syntax(dry_run: bool = False) -> dict:
    """py_compile check on critical pipeline Python files."""
    errors = []
    checked = []

    for filename in SYNTAX_CHECK_FILES:
        path = PIPELINE_DIR / filename
        if not path.exists():
            # Not a hard failure — file might have been renamed/removed intentionally
            print(f"[preflight] ⚠️  syntax: {filename} not found (skipping)")
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            checked.append(filename)
        except py_compile.PyCompileError as e:
            errors.append(f"{filename}: {e}")
            print(f"[preflight] ❌ syntax: {filename} — {e}")

    if errors:
        detail = "; ".join(errors)
        print(f"[preflight] ❌ syntax: {len(errors)} file(s) have syntax errors")
        return {"check": "syntax", "status": "fail", "detail": detail,
                "errors": errors, "checked": checked, "hard_failure": True}

    print(f"[preflight] ✅ syntax: {len(checked)} file(s) OK")
    return {"check": "syntax", "status": "ok", "detail": f"{len(checked)} files checked",
            "checked": checked, "hard_failure": False}


def check_env_vars(dry_run: bool = False) -> dict:
    """Check required environment variables are set (non-empty)."""
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]

    if missing:
        detail = f"Missing env vars: {', '.join(missing)}"
        print(f"[preflight] ❌ env_vars: {detail}")
        return {"check": "env_vars", "status": "fail", "detail": detail,
                "missing": missing, "hard_failure": True}

    print(f"[preflight] ✅ env_vars: all {len(REQUIRED_ENV_VARS)} required vars present")
    return {"check": "env_vars", "status": "ok",
            "detail": f"{len(REQUIRED_ENV_VARS)} vars present", "hard_failure": False}


def check_disk_space(dry_run: bool = False) -> dict:
    """Check free disk space on project filesystem."""
    try:
        usage = shutil.disk_usage(str(PROJECT_DIR))
        free_mb = usage.free // (1024 * 1024)
    except Exception as e:
        return {"check": "disk_space", "status": "fail",
                "detail": f"Cannot check disk: {e}", "hard_failure": True}

    if free_mb < MIN_FREE_DISK_MB:
        detail = f"Only {free_mb}MB free (minimum: {MIN_FREE_DISK_MB}MB)"
        print(f"[preflight] ❌ disk_space: {detail}")
        return {"check": "disk_space", "status": "fail", "detail": detail,
                "free_mb": free_mb, "hard_failure": True}

    print(f"[preflight] ✅ disk_space: {free_mb}MB free")
    return {"check": "disk_space", "status": "ok",
            "detail": f"{free_mb}MB free", "free_mb": free_mb, "hard_failure": False}


# ── Main ──────────────────────────────────────────────────────────────────────

def run_preflight(dry_run: bool = False) -> tuple[list[dict], bool]:
    """Run all checks. Returns (results, any_hard_failure)."""
    results = []
    results.append(check_execute_bits(dry_run))
    results.append(check_stale_lock(dry_run))
    results.append(check_syntax(dry_run))
    results.append(check_env_vars(dry_run))
    results.append(check_disk_space(dry_run))
    any_hard_failure = any(r["hard_failure"] for r in results)
    return results, any_hard_failure


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(timezone.utc)

    print(f"[preflight] {'DRY RUN — ' if dry_run else ''}Running at {now.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    results, any_hard_failure = run_preflight(dry_run)

    # Write JSON summary
    summary = {
        "ran_at":          now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dry_run":         dry_run,
        "passed":          not any_hard_failure,
        "checks":          results,
    }

    if not dry_run:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(summary, indent=2))

    # Discord alert on hard failures
    hard_failures = [r for r in results if r["hard_failure"]]
    if hard_failures and not dry_run:
        lines = ["🔴 **Preflight check failed** — pipeline will NOT run:"]
        for r in hard_failures:
            lines.append(f"  • `{r['check']}`: {r.get('detail', 'unknown error')}")
        _discord_alert("\n".join(lines))

    # Summary line
    auto_fixed = [r for r in results if r["status"] == "auto_fixed"]
    ok_count   = sum(1 for r in results if r["status"] == "ok")
    status_str = "✅ PASS" if not any_hard_failure else "❌ FAIL"
    print(f"[preflight] {status_str} — {ok_count} OK, {len(auto_fixed)} auto-fixed, "
          f"{len(hard_failures)} hard failures")

    return 1 if any_hard_failure else 0


if __name__ == "__main__":
    sys.exit(main())
