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
    ready_count = len(list((pipeline_dir / "queues/staged/ready").glob("*.json")))
    writing_count = len(list((pipeline_dir / "queues/staged/writing").glob("*.json")))
    outbox_count = len(list((pipeline_dir / "queues/staged/outbox").glob("*.json")))
    publisher_enabled = (pipeline_dir / "actions-publish.enabled").is_file()
    scanner_enabled = (pipeline_dir / "actions-scan.enabled").is_file()
    worker_enabled = (pipeline_dir / "monica-worker.enabled").is_file()
    remaining_cycles = (
        outbox_count + max_packets_per_cycle - 1
    ) // max_packets_per_cycle
    reasons = [
        "publisher_enabled" if publisher_enabled else "publisher_disabled",
        "scanner_enabled" if scanner_enabled else "scanner_disabled",
        "worker_enabled" if worker_enabled else "worker_disabled",
    ]

    # A healthy end-to-end pipeline is allowed to be idle. Outbox depletion was
    # a useful migration warning only while no durable Monica worker signal
    # existed; once scanner + transactional worker + publisher are all enabled,
    # zero queue depth means caught up rather than starved.
    if publisher_enabled and scanner_enabled and worker_enabled:
        replenishment_state = "end_to_end_enabled"
        reasons.append("queue_idle" if ready_count + writing_count + outbox_count == 0 else "queue_active")
    elif scanner_enabled and worker_enabled:
        replenishment_state = "scanner_worker_enabled_publisher_disabled"
        reasons.append("publisher_delivery_disabled")
    elif scanner_enabled:
        replenishment_state = "scanner_enabled_writer_unverified"
        reasons.append("writer_unverified")
    elif worker_enabled:
        replenishment_state = "worker_enabled_scanner_disabled"
        reasons.append("scanner_replenishment_disabled")
    else:
        replenishment_state = "disabled"

    if writing_count > 1:
        severity = "critical"
        reasons.append("multiple_writing_packets")
    elif not publisher_enabled:
        severity = "inactive"
    elif scanner_enabled and worker_enabled:
        severity = "ok"
    elif outbox_count <= 6:
        severity = "critical"
    elif outbox_count <= 12:
        severity = "warning"
    else:
        severity = "ok"

    if publisher_enabled and not (scanner_enabled and worker_enabled):
        reasons.append(f"outbox_{severity}")

    return {
        "readyCount": ready_count,
        "writingCount": writing_count,
        "outboxCount": outbox_count,
        "publisherEnabled": publisher_enabled,
        "scannerEnabled": scanner_enabled,
        "workerEnabled": worker_enabled,
        "maxPacketsPerCycle": max_packets_per_cycle,
        "worstCaseRemainingCycles": remaining_cycles,
        "replenishmentState": replenishment_state,
        "severity": severity,
        "reasons": reasons,
    }


def write_actions_summary(runway: dict, summary_path: Path) -> None:
    rows = (
        ("Ready packets", runway["readyCount"]),
        ("Writing packets", runway["writingCount"]),
        ("Outbox packets", runway["outboxCount"]),
        ("Publisher marker", "enabled" if runway["publisherEnabled"] else "disabled"),
        ("Scanner marker", "enabled" if runway["scannerEnabled"] else "disabled"),
        ("Monica worker marker", "enabled" if runway["workerEnabled"] else "disabled"),
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
