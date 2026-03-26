#!/usr/bin/env python3
"""
ci_validate.py — run the full validation suite for CI.

Runs these validators in sequence:
- smoke_test.py
- test_templates.py
- validate_feeds.py
- validate_structured_data.py

Behavior:
- prints a header for each step
- runs all steps even if one fails
- prints a final pass/fail summary
- exits 1 if any step failed, else 0

Usage:
    python3 pipeline/ci_validate.py
    python3 pipeline/ci_validate.py --skip feeds
    python3 pipeline/ci_validate.py --skip feeds,templates
    python3 pipeline/ci_validate.py --skip feeds --skip structured-data
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    script: str


@dataclass
class StepResult:
    step: Step
    returncode: int
    duration: float
    stdout: str
    stderr: str
    skipped: bool = False

    @property
    def passed(self) -> bool:
        return (not self.skipped) and self.returncode == 0

    @property
    def failed(self) -> bool:
        return (not self.skipped) and self.returncode != 0


STEPS = [
    Step("smoke", "Smoke tests", "smoke_test.py"),
    Step("templates", "Template edge-case tests", "test_templates.py"),
    Step("feeds", "RSS feed validation", "validate_feeds.py"),
    Step("structured-data", "Structured data validation", "validate_structured_data.py"),
]

ALIASES = {
    "smoke": "smoke",
    "template": "templates",
    "templates": "templates",
    "feed": "feeds",
    "feeds": "feeds",
    "schema": "structured-data",
    "structured": "structured-data",
    "structured-data": "structured-data",
    "structured_data": "structured-data",
}


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = seconds - minutes * 60
    return f"{minutes}m {rem:.1f}s"


def parse_skip_values(values: list[str]) -> set[str]:
    skipped: set[str] = set()
    for raw in values:
        for token in raw.split(","):
            key = token.strip().lower()
            if not key:
                continue
            normalized = ALIASES.get(key)
            if not normalized:
                valid = ", ".join(sorted(ALIASES))
                raise SystemExit(f"Unknown --skip value: {token!r}. Valid values: {valid}")
            skipped.add(normalized)
    return skipped


def run_step(step: Step) -> StepResult:
    command = [sys.executable, str(SCRIPT_DIR / step.script)]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=SCRIPT_DIR.parent,
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - started
    return StepResult(
        step=step,
        returncode=completed.returncode,
        duration=duration,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )



def print_step_header(index: int, total: int, step: Step) -> None:
    print("═" * 60)
    print(f"[{index}/{total}] {step.label}")
    print(f"[ci] Script: pipeline/{step.script}")
    print("═" * 60)



def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full CI validation suite.")
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        help="Skip one or more steps: smoke, templates, feeds, structured-data",
    )
    args = parser.parse_args()

    skipped = parse_skip_values(args.skip)
    total_started = time.monotonic()
    results: list[StepResult] = []

    for index, step in enumerate(STEPS, start=1):
        print_step_header(index, len(STEPS), step)

        if step.key in skipped:
            print(f"[ci] Skipped: {step.key}")
            print()
            results.append(
                StepResult(
                    step=step,
                    returncode=0,
                    duration=0.0,
                    stdout="",
                    stderr="",
                    skipped=True,
                )
            )
            continue

        result = run_step(step)
        results.append(result)

        if result.stdout.strip():
            print(result.stdout.rstrip())
        if result.stderr.strip():
            print("[ci] stderr:")
            print(result.stderr.rstrip())

        status = "PASS" if result.returncode == 0 else f"FAIL (exit {result.returncode})"
        print(f"[ci] Result: {status}")
        print(f"[ci] Runtime: {format_duration(result.duration)}")
        print()

    total_duration = time.monotonic() - total_started
    failed = [result for result in results if result.failed]
    passed = [result for result in results if result.passed]
    skipped_results = [result for result in results if result.skipped]

    print("═" * 60)
    print("CI Validation Summary")
    print("═" * 60)
    for result in results:
        if result.skipped:
            icon = "⏭"
            detail = "skipped"
        elif result.passed:
            icon = "✅"
            detail = f"passed in {format_duration(result.duration)}"
        else:
            icon = "❌"
            detail = f"failed with exit {result.returncode} in {format_duration(result.duration)}"
        print(f"{icon} {result.step.key:<16} {detail}")

    print("[ci] ────────────────────────────────────────────────")
    print(f"[ci] Passed: {len(passed)}")
    print(f"[ci] Failed: {len(failed)}")
    print(f"[ci] Skipped: {len(skipped_results)}")
    print(f"[ci] Total runtime: {format_duration(total_duration)}")

    if failed:
        print("[ci] Validation suite failed")
        return 1

    print("[ci] Validation suite passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
