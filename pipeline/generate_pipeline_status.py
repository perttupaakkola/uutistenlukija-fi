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


def _summarize_outbox_supply(files: list[Path]) -> dict:
    try:
        from .staged_publish import summarize_outbox_supply
    except ImportError:  # pragma: no cover - direct script execution
        from staged_publish import summarize_outbox_supply
    return summarize_outbox_supply(files)


def build_staged_queue_runway(
    project_dir: Path = PROJECT_DIR,
    max_packets_per_cycle: int = MAX_PACKETS_PER_CYCLE,
    recent_published_packets: int = 0,
) -> dict:
    pipeline_dir = project_dir / "pipeline"
    ready_count = len(list((pipeline_dir / "queues/staged/ready").glob("*.json")))
    writing_count = len(list((pipeline_dir / "queues/staged/writing").glob("*.json")))
    outbox_files = list((pipeline_dir / "queues/staged/outbox").glob("*.json"))
    supply = _summarize_outbox_supply(outbox_files)
    outbox_count = supply["raw_outbox"]
    action_counts = supply["action_counts"]
    publish_eligible_count = action_counts["publish"]
    monica_review_count = action_counts["monica_review"]
    reject_count = action_counts["reject"]
    publisher_enabled = (pipeline_dir / "actions-publish.enabled").is_file()
    scanner_enabled = (pipeline_dir / "actions-scan.enabled").is_file()
    worker_enabled = (pipeline_dir / "monica-worker.enabled").is_file()
    raw_outbox_cycles = (
        outbox_count + max_packets_per_cycle - 1
    ) // max_packets_per_cycle
    publishable_cycles = (
        publish_eligible_count + max_packets_per_cycle - 1
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
    elif outbox_count > 0 and publish_eligible_count == 0:
        if scanner_enabled and worker_enabled and recent_published_packets >= 2:
            severity = "ok"
            reasons.append("eligible_supply_post_drain")
        else:
            severity = "critical"
            reasons.append("eligible_supply_stalled")
    elif scanner_enabled and worker_enabled:
        severity = "ok"
        if publish_eligible_count:
            reasons.append("eligible_supply_available")
    elif publish_eligible_count <= 6:
        severity = "critical"
    elif publish_eligible_count <= 12:
        severity = "warning"
    else:
        severity = "ok"

    if publisher_enabled and not (scanner_enabled and worker_enabled):
        reasons.append(f"eligible_supply_{severity}")

    return {
        "readyCount": ready_count,
        "writingCount": writing_count,
        "outboxCount": outbox_count,
        "publishEligibleCount": publish_eligible_count,
        "monicaReviewCount": monica_review_count,
        "rejectCount": reject_count,
        "preflightPrimaryReasonBuckets": supply["primary_reason_buckets"],
        "preflightReasonBuckets": supply["reason_buckets"],
        "publisherEnabled": publisher_enabled,
        "scannerEnabled": scanner_enabled,
        "workerEnabled": worker_enabled,
        "maxPacketsPerCycle": max_packets_per_cycle,
        "rawOutboxRemainingCycles": raw_outbox_cycles,
        "publishableRemainingCycles": publishable_cycles,
        "recentPublishedPackets": recent_published_packets,
        # Backward-compatible field name; its value is now deliberately based
        # on eligible supply, never raw depth.
        "worstCaseRemainingCycles": publishable_cycles,
        "replenishmentState": replenishment_state,
        "severity": severity,
        "reasons": reasons,
    }


def write_actions_summary(
    runway: dict,
    summary_path: Path,
    staged_cycles: dict | None = None,
) -> None:
    rows = (
        ("Ready packets", runway["readyCount"]),
        ("Writing packets", runway["writingCount"]),
        ("Outbox packets", runway["outboxCount"]),
        ("Publish-eligible packets", runway["publishEligibleCount"]),
        ("Monica-held packets", runway["monicaReviewCount"]),
        ("Hard-reject packets", runway["rejectCount"]),
        ("Publisher marker", "enabled" if runway["publisherEnabled"] else "disabled"),
        ("Scanner marker", "enabled" if runway["scannerEnabled"] else "disabled"),
        ("Monica worker marker", "enabled" if runway["workerEnabled"] else "disabled"),
        ("Max packets per cycle", runway["maxPacketsPerCycle"]),
        ("Raw outbox cycles", runway["rawOutboxRemainingCycles"]),
        ("Publishable remaining cycles", runway["publishableRemainingCycles"]),
        ("Replenishment", runway["replenishmentState"]),
        ("Severity", runway["severity"]),
        ("Reasons", ", ".join(runway["reasons"])),
    )
    with summary_path.open("a", encoding="utf-8") as output:
        output.write("## Staged queue runway\n\n| Field | Value |\n| --- | --- |\n")
        for label, value in rows:
            output.write(f"| {label} | {value} |\n")
        output.write("\n")
        if staged_cycles and staged_cycles.get("latest"):
            latest = staged_cycles["latest"]
            output.write(
                "## Staged publish cycle\n\n"
                "| Field | Value |\n| --- | --- |\n"
                f"| Cycle | {latest.get('cycleId') or '-'} |\n"
                f"| Admitted | {str(bool(latest.get('admitted'))).lower()} |\n"
                f"| Outcome | {latest.get('outcome') or '-'} |\n"
                f"| Result | {latest.get('result') or '-'} |\n"
                f"| Raw outbox | {latest.get('rawOutbox', 0)} |\n"
                f"| Publish eligible | {latest.get('publishEligible', 0)} |\n"
                f"| Monica review | {latest.get('monicaReview', 0)} |\n"
                f"| Reject | {latest.get('reject', 0)} |\n"
                f"| Published | {latest.get('published', 0)} |\n\n"
            )

    annotation = "warning" if runway["severity"] in {"critical", "warning"} else "notice"
    print(
        f"::{annotation} title=Staged queue runway {runway['severity']}::"
        f"outbox={runway['outboxCount']} "
        f"eligible={runway['publishEligibleCount']} "
        f"held={runway['monicaReviewCount']} "
        f"reject={runway['rejectCount']} "
        f"publishable_cycles={runway['publishableRemainingCycles']} "
        f"replenishment={runway['replenishmentState']} "
        f"reasons={','.join(runway['reasons'])}"
    )


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-summary", action="store_true")
    parser.add_argument("--cycle-outcome", type=Path)
    args = parser.parse_args(argv)

    # Import dashboard from same directory
    sys.path.insert(0, str(SCRIPT_DIR))
    from dashboard import build_dashboard, recent_post_dates

    hours = 24
    data = build_dashboard(hours=hours, actions_cycle_path=args.cycle_outcome)
    recent_posts = recent_post_dates(hours=hours)
    if recent_posts:
        data["articles"]["published"] = len(recent_posts)
        data["articles"]["last_published_ts"] = recent_posts[-1].isoformat()
    data["articles"]["production_truth_scope"] = (
        "rolling_24h_published_content" if recent_posts else "observed_cycle_records"
    )
    if isinstance(data.get("stagedPublishCycles"), dict):
        data["stagedPublishCycles"]["scope"] = "observed_cycle_records"
    staged_cycles = data.get("stagedPublishCycles")
    recent_published_packets = (
        staged_cycles.get("published", 0) if isinstance(staged_cycles, dict) else 0
    )
    runway = build_staged_queue_runway(
        recent_published_packets=recent_published_packets,
    )
    data["stagedQueueRunway"] = runway

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    if args.actions_summary:
        write_actions_summary(
            runway,
            Path(os.environ["GITHUB_STEP_SUMMARY"]),
            data.get("stagedPublishCycles"),
        )
    print(f"[generate_pipeline_status] Written: {OUT_FILE.relative_to(PROJECT_DIR)}"
          f" (published={data['articles']['published']} runs={data['runs']['total']}"
          f" runway={runway['severity']}/{runway['publishableRemainingCycles']} publishable cycles)")

if __name__ == "__main__":
    main()
