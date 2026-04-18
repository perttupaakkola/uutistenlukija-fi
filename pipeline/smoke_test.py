#!/usr/bin/env python3
"""
Pipeline smoke test: dry-import every .py module, verify cross-module
function references, check auto_publish.sh syntax.

Exit 0 = all clear, exit 1 = failures found.

Usage:
    python3 smoke_test.py          # run from pipeline/ directory
    python3 smoke_test.py --verbose # show all checks, not just failures
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent

# Modules that need external packages not always available in all environments.
# We still try to import them — if they fail due to missing 3rd-party deps
# (openai, requests, etc.) that's a WARN, not a FAIL.
EXTERNAL_DEP_MODULES = {"generate_descriptions", "ghost_publisher", "newsletter_api", "run_pipeline", "rewriter", "batch_improve_descriptions", "image_gen"}

# Cross-module function references that run_pipeline.py depends on.
CRITICAL_IMPORTS = {
    "scanner": ["scan_all_feeds"],
    "firehose": ["poll_firehose"],
    "research": ["enrich_with_research"],
    "monica_writer": ["rewrite_articles"],
    "publisher": ["publish_articles", "build_site"],
    "generate_descriptions": ["generate_for_article_dict"],
    "dedup": ["filter_new_articles", "check_published_duplicates", "dedup_within_batch", "mark_published"],
    "image_gen": ["generate_images_for_articles"],
    "pexels": ["fetch_images_for_articles"],
    "unsplash": ["fetch_images_for_articles"],
    "writers": ["assign_writer"],
    "health_check": ["notify_discord_failure", "notify_discord_warning", "notify_discord_crash", "write_metrics"],
}


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    fails = []
    warns = []
    ok_count = 0

    # ── 1. Dry-import every .py module ──────────────────────────────────────
    print("═" * 60)
    print(" Pipeline Smoke Test")
    print("═" * 60)
    print()
    print("── Module imports ──")

    py_files = sorted(PIPELINE_DIR.glob("*.py"))
    skip = {"smoke_test.py", "__init__.py", "test_ghost_publish.py", "test_key_points.py", "test_templates.py", "test_monica_writer.py"}

    for f in py_files:
        if f.name in skip:
            continue
        mod_name = f.stem
        try:
            importlib.import_module(mod_name)
            ok_count += 1
            if verbose:
                print(f"  ✓ {mod_name}")
        except (ImportError, SystemExit) as e:
            if mod_name in EXTERNAL_DEP_MODULES:
                warns.append(f"{mod_name}: {e} (external dep, OK on host)")
                print(f"  ⚠ {mod_name}: {e} (expected — needs host venv)")
            else:
                fails.append(f"IMPORT {mod_name}: {e}")
                print(f"  ✗ {mod_name}: {e}")
        except Exception as e:
            fails.append(f"IMPORT {mod_name}: {type(e).__name__}: {e}")
            print(f"  ✗ {mod_name}: {type(e).__name__}: {e}")

    # ── 2. Cross-module function checks ─────────────────────────────────────
    print()
    print("── Cross-module functions ──")

    for mod_name, funcs in CRITICAL_IMPORTS.items():
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            if mod_name in EXTERNAL_DEP_MODULES:
                if verbose:
                    print(f"  ⚠ {mod_name}: skipped (external dep)")
            continue
        except Exception:
            continue

        for fn_name in funcs:
            if hasattr(mod, fn_name):
                ok_count += 1
                if verbose:
                    print(f"  ✓ {mod_name}.{fn_name}")
            else:
                fails.append(f"MISSING {mod_name}.{fn_name}")
                print(f"  ✗ {mod_name}.{fn_name} — NOT FOUND")

    # ── 3. run_pipeline.py --dry-run ────────────────────────────────────────
    print()
    print("── Dry-run check ──")

    dry_run_script = PIPELINE_DIR / "run_pipeline.py"
    if dry_run_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(dry_run_script), "--dry-run"],
                capture_output=True, text=True, timeout=30,
                cwd=str(PIPELINE_DIR),
            )
            if result.returncode == 0:
                ok_count += 1
                print(f"  ✓ run_pipeline.py --dry-run (exit 0)")
                if verbose and result.stdout.strip():
                    for line in result.stdout.strip().split("\n")[:5]:
                        print(f"    {line}")
            else:
                all_output = ((result.stderr or "") + (result.stdout or "")).strip()
                stderr_short = all_output[:200]
                # Known external dep failures are warnings, not errors
                known_dep_errors = ["No module named 'openai'", "No module named 'fastapi'"]
                if any(dep in all_output for dep in known_dep_errors):
                    warns.append(f"DRY-RUN skipped (missing external dep on this env)")
                    print(f"  ⚠ run_pipeline.py --dry-run — skipped (needs openai, host-only)")
                else:
                    fails.append(f"DRY-RUN failed (exit {result.returncode}): {stderr_short}")
                    print(f"  ✗ run_pipeline.py --dry-run (exit {result.returncode})")
                    if stderr_short:
                        print(f"    {stderr_short}")
        except subprocess.TimeoutExpired:
            fails.append("DRY-RUN timed out (30s)")
            print(f"  ✗ run_pipeline.py --dry-run — TIMEOUT (30s)")
        except Exception as e:
            fails.append(f"DRY-RUN error: {e}")
            print(f"  ✗ run_pipeline.py --dry-run — {e}")

    # ── 4. auto_publish.sh syntax ───────────────────────────────────────────
    print()
    print("── Shell scripts ──")

    auto_pub = PIPELINE_DIR / "auto_publish.sh"
    if auto_pub.exists():
        result = subprocess.run(
            ["bash", "-n", str(auto_pub)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok_count += 1
            print(f"  ✓ auto_publish.sh (syntax OK)")
        else:
            fails.append(f"auto_publish.sh syntax: {result.stderr.strip()}")
            print(f"  ✗ auto_publish.sh: {result.stderr.strip()}")

        # Check execute bit
        if os.access(str(auto_pub), os.X_OK):
            ok_count += 1
            if verbose:
                print(f"  ✓ auto_publish.sh (+x)")
        else:
            fails.append("auto_publish.sh missing execute permission")
            print(f"  ✗ auto_publish.sh — not executable (chmod +x needed)")
    else:
        warns.append("auto_publish.sh not found")
        print(f"  ⚠ auto_publish.sh not found")

    firehose_cron = PIPELINE_DIR / "firehose_cron.sh"
    if firehose_cron.exists():
        result = subprocess.run(
            ["bash", "-n", str(firehose_cron)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            ok_count += 1
            if verbose:
                print(f"  ✓ firehose_cron.sh (syntax OK)")
        else:
            fails.append(f"firehose_cron.sh syntax: {result.stderr.strip()}")
            print(f"  ✗ firehose_cron.sh: {result.stderr.strip()}")

    # ── Summary ─────────────────────────────────────────────────────────────
    print()
    print("═" * 60)
    if fails:
        print(f" ✗ FAILED: {len(fails)} error(s), {len(warns)} warning(s), {ok_count} passed")
        for f in fails:
            print(f"   ✗ {f}")
        print("═" * 60)
        sys.exit(1)
    elif warns:
        print(f" ⚠ PASSED with {len(warns)} warning(s), {ok_count} checks OK")
        print("═" * 60)
        sys.exit(0)
    else:
        print(f" ✓ ALL CLEAR — {ok_count} checks passed")
        print("═" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()
