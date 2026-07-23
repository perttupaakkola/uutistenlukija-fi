#!/usr/bin/env python3
"""
generate_pipeline_status.py — Write pipeline dashboard data to static/api/pipeline-status.json

Called by auto_publish.sh after each pipeline run.
Output served at: https://uutistenlukija.fi/api/pipeline-status.json

Consumers: /tila/ page (live dashboard widget)
"""
import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
OUT_FILE    = PROJECT_DIR / "static" / "api" / "pipeline-status.json"
MAX_PACKETS_PER_CYCLE = 3


def build_staged_queue_runway(
    project_dir: Path = PROJECT_DIR,
    max_packets_per_cycle: int = MAX_PACKETS_PER_CYCLE,
) -> dict:
    pipeline_dir = project_dir / "pipeline"
    outbox_count = len(list((pipeline_dir / "queues/staged/outbox").glob("*.json")))
    publisher_enabled = (pipeline_dir / "actions-publish.enabled").is_file()
    scanner_enabled = (pipeline_dir / "actions-scan.enabled").is_file()
    remaining_cycles = (
        outbox_count + max_packets_per_cycle - 1
    ) // max_packets_per_cycle
    reasons = [
        "publisher_enabled" if publisher_enabled else "publisher_disabled",
        "scanner_enabled" if scanner_enabled else "scanner_disabled",
    ]

    # The Actions scanner replenishes ready/, not outbox/. Until a durable
    # Monica-writer signal exists, the scanner marker cannot suppress outbox
    # depletion severity or claim end-to-end replenishment.
    if scanner_enabled:
        replenishment_state = "scanner_enabled_writer_unverified"
        reasons.append("writer_unverified")
    else:
        replenishment_state = "disabled"

    if not publisher_enabled:
        severity = "inactive"
    elif outbox_count <= 6:
        severity = "critical"
    elif outbox_count <= 12:
        severity = "warning"
    else:
        severity = "ok"

    if publisher_enabled:
        reasons.append(f"outbox_{severity}")

    return {
        "outboxCount": outbox_count,
        "publisherEnabled": publisher_enabled,
        "scannerEnabled": scanner_enabled,
        "maxPacketsPerCycle": max_packets_per_cycle,
        "worstCaseRemainingCycles": remaining_cycles,
        "replenishmentState": replenishment_state,
        "severity": severity,
        "reasons": reasons,
    }


def write_actions_summary(runway: dict, summary_path: Path) -> None:
    rows = (
        ("Outbox packets", runway["outboxCount"]),
        ("Publisher marker", "enabled" if runway["publisherEnabled"] else "disabled"),
        ("Scanner marker", "enabled" if runway["scannerEnabled"] else "disabled"),
        ("Max packets per cycle", runway["maxPacketsPerCycle"]),
        ("Worst-case remaining cycles", runway["worstCaseRemainingCycles"]),
        ("Replenishment", runway["replenishmentState"]),
        ("Severity", runway["severity"]),
        ("Reasons", ", ".join(runway["reasons"])),
    )
    with summary_path.open("a", encoding="utf-8") as output:
        output.write("## Staged queue runway\n\n| Field | Value |\n| --- | --- |\n")
        for label, value in rows:
            output.write(f"| {label} | {value} |\n")
        output.write("\n")

    annotation = "warning" if runway["severity"] in {"critical", "warning"} else "notice"
    print(
        f"::{annotation} title=Staged queue runway {runway['severity']}::"
        f"outbox={runway['outboxCount']} "
        f"remaining_cycles={runway['worstCaseRemainingCycles']} "
        f"replenishment={runway['replenishmentState']} "
        f"reasons={','.join(runway['reasons'])}"
    )


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-summary", action="store_true")
    args = parser.parse_args(argv)

    # Import dashboard from same directory
    sys.path.insert(0, str(SCRIPT_DIR))
    from dashboard import build_dashboard

    data = build_dashboard(hours=24)
    runway = build_staged_queue_runway()
    data["stagedQueueRunway"] = runway

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    if args.actions_summary:
        write_actions_summary(runway, Path(os.environ["GITHUB_STEP_SUMMARY"]))
    print(f"[generate_pipeline_status] Written: {OUT_FILE.relative_to(PROJECT_DIR)}"
          f" (published={data['articles']['published']} runs={data['runs']['total']}"
          f" runway={runway['severity']}/{runway['worstCaseRemainingCycles']} cycles)")

if __name__ == "__main__":
    main()
