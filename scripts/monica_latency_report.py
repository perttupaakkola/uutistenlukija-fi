#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONICA_LOG = PROJECT_ROOT / "pipeline" / "logs" / "staged-monica-worker.log"
FAILED_DIR = PROJECT_ROOT / "pipeline" / "queues" / "staged" / "failed"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "monica-latency-report.json"

START_RE = re.compile(r"^\[(?P<ts>[^]]+)\] \[uutis-monica-worker\] START")
END_RE = re.compile(r"^\[(?P<ts>[^]]+)\] \[uutis-monica-worker\] END rc=(?P<rc>\d+) duration_s=(?P<dur>\d+)")
SKIP_RE = re.compile(r"^\[(?P<ts>[^]]+)\] \[uutis-monica-worker\] SKIP (?P<reason>\S+)")
PROCESS_RE = re.compile(
    r"monica-worker: processing (?P<file>\S+) priority=(?P<priority>-?[0-9.]+) "
    r"age_h=(?P<age>[0-9.]+) source_words=(?P<words>\d+) source_blocks=(?P<blocks>\d+)"
)
STATUS_RE = re.compile(r"monica-worker: (?P<status>ok|failed) (?P<detail>.*)$")
REPAIR_RE = re.compile(r"monica-worker: (?P<kind>repair pass|near-miss repair pass) ")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def failure_bucket(text: str) -> str:
    lowered = (text or "").lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "context overflow" in lowered:
        return "context_overflow"
    if "json" in lowered or "dispatch" in lowered or "openclaw" in lowered:
        return "writer_runtime"
    if "content too short" in lowered or "lead paragraph too short" in lowered:
        return "writer_short"
    if "schema" in lowered:
        return "schema_invalid"
    if any(token in lowered for token in ("lähde", "source", "aineisto", "otsikko", "otsikon", "riittä")):
        return "source_insufficient_or_mismatch"
    return "other"


def source_bucket(words: int) -> str:
    if words < 100:
        return "lt_100"
    if words < 200:
        return "100_199"
    if words < 300:
        return "200_299"
    return "gte_300"


def parse_worker_log(path: Path, cutoff: datetime) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    skips: list[dict[str, str]] = []
    current: dict[str, Any] | None = None

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []:
        start = START_RE.match(line)
        if start:
            current = {
                "start": parse_ts(start.group("ts")),
                "processed": [],
                "statuses": [],
                "repairs": 0,
                "near_miss_repairs": 0,
            }
            continue

        skip = SKIP_RE.match(line)
        if skip:
            ts = parse_ts(skip.group("ts"))
            if ts >= cutoff:
                skips.append({"timestamp": ts.isoformat(), "reason": skip.group("reason")})
            continue

        if current is not None:
            processed = PROCESS_RE.search(line)
            if processed:
                current["processed"].append(
                    {
                        "file": processed.group("file"),
                        "source_words": int(processed.group("words")),
                        "source_blocks": int(processed.group("blocks")),
                    }
                )

            repair = REPAIR_RE.search(line)
            if repair:
                if repair.group("kind").startswith("near"):
                    current["near_miss_repairs"] += 1
                else:
                    current["repairs"] += 1

            status = STATUS_RE.search(line)
            if status:
                current["statuses"].append(
                    {
                        "status": status.group("status"),
                        "bucket": failure_bucket(status.group("detail")),
                    }
                )

        end = END_RE.match(line)
        if end and current is not None:
            current["end"] = parse_ts(end.group("ts"))
            current["rc"] = int(end.group("rc"))
            current["duration_s"] = int(end.group("dur"))
            if current["start"] >= cutoff:
                runs.append(current)
            current = None

    durations = [run["duration_s"] for run in runs]
    packet_attempts = [packet for run in runs for packet in run["processed"]]
    statuses = [status for run in runs for status in run["statuses"]]
    timeout_runs = [run for run in runs if any(status["bucket"] == "timeout" for status in run["statuses"])]
    timeout_source_buckets = Counter(
        source_bucket(packet["source_words"])
        for run in timeout_runs
        for packet in run["processed"][:1]
    )
    timeout_stages = Counter(
        "near_miss_repair" if run["near_miss_repairs"] else "repair" if run["repairs"] else "initial"
        for run in timeout_runs
    )

    return {
        "log_path": str(path.relative_to(PROJECT_ROOT)),
        "runs": len(runs),
        "packet_attempts": len(packet_attempts),
        "status_counts": dict(Counter(status["status"] for status in statuses)),
        "failure_buckets": dict(Counter(status["bucket"] for status in statuses if status["status"] == "failed")),
        "duration_s": {
            "min": min(durations) if durations else None,
            "median": statistics.median(durations) if durations else None,
            "p90": percentile(durations, 0.9),
            "max": max(durations) if durations else None,
            "ge_350": sum(1 for value in durations if value >= 350),
        },
        "repair_runs": sum(1 for run in runs if run["repairs"] or run["near_miss_repairs"]),
        "timeout_runs": len(timeout_runs),
        "timeout_stages": dict(timeout_stages),
        "timeout_source_word_buckets": dict(timeout_source_buckets),
        "skip_reasons": dict(Counter(skip["reason"] for skip in skips)),
        "recent_timeout_attempts": [
            {
                "timestamp": run["start"].isoformat(),
                "duration_s": run["duration_s"],
                "packet_file": run["processed"][0]["file"] if run["processed"] else "",
                "source_words": run["processed"][0]["source_words"] if run["processed"] else None,
                "source_blocks": run["processed"][0]["source_blocks"] if run["processed"] else None,
                "stage": "near_miss_repair" if run["near_miss_repairs"] else "repair" if run["repairs"] else "initial",
            }
            for run in timeout_runs[-20:]
        ],
    }


def parse_failed_artifacts(path: Path, cutoff: datetime) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for artifact in path.glob("*.json") if path.exists() else []:
        try:
            mtime = datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc)
            if mtime < cutoff:
                continue
            data = json.loads(artifact.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        feedback = data.get("writer_failure_feedback") or {}
        packet = data.get("packet") or data
        failure = str(data.get("failure") or "")
        rows.append(
            {
                "artifact": artifact.name,
                "mtime": mtime.isoformat(),
                "bucket": failure_bucket(failure + " " + str(feedback.get("retry_classification") or "")),
                "retry_classification": feedback.get("retry_classification"),
                "category": feedback.get("category") or packet.get("category") or packet.get("category_hint"),
                "source_words": feedback.get("selected_source_words"),
                "source_blocks": feedback.get("selected_source_blocks"),
                "raw_response_bytes": len(str(data.get("raw_response") or "").encode("utf-8")),
            }
        )

    return {
        "failed_dir": str(path.relative_to(PROJECT_ROOT)),
        "artifacts": len(rows),
        "buckets": dict(Counter(row["bucket"] for row in rows)),
        "retry_classifications": dict(Counter(str(row["retry_classification"] or "missing") for row in rows)),
        "timeout_artifacts": [
            row for row in rows if row["bucket"] == "timeout"
        ][-50:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a redacted Monica writer latency and timeout report.")
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON artifact path.")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)
    report = {
        "schema": "uutistenlukija.monica_latency_report.v1",
        "generated_at": now.isoformat(),
        "window_hours": args.hours,
        "cutoff": cutoff.isoformat(),
        "redaction": {
            "prompt_text_included": False,
            "raw_response_text_included": False,
            "secret_values_included": False,
        },
        "worker_log": parse_worker_log(MONICA_LOG, cutoff),
        "failed_artifacts": parse_failed_artifacts(FAILED_DIR, cutoff),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(
        "summary "
        f"attempts={report['worker_log']['packet_attempts']} "
        f"timeouts={report['worker_log']['failure_buckets'].get('timeout', 0)} "
        f"ok={report['worker_log']['status_counts'].get('ok', 0)} "
        f"failed_artifacts={report['failed_artifacts']['artifacts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
