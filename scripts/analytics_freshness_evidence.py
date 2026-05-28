#!/usr/bin/env python3
"""Write redacted analytics freshness evidence after OAuth reauthorization checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_DIR / "analytics" / "post-reauth-freshness-evidence.json"
DEFAULT_STATIC_OUTPUT = PROJECT_DIR / "static" / "api" / "analytics-freshness-status.json"
DAILY_REPORT = PROJECT_DIR / "analytics" / "daily-report.json"
SEARCH_CONSOLE_REPORT = PROJECT_DIR / "static" / "api" / "search-console-data.json"
OAUTH_SENTINEL = PROJECT_DIR / "analytics" / "oauth-failure-sentinel.json"

SAFE_SOURCE_COMMANDS = [
    "cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && SECRETS_DIR=/home/pertt/.openclaw/workspace/.secrets bash pipeline/check-analytics.sh",
    "cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && scripts/run_with_project_env.sh python3 scripts/daily_traffic_card.py --dry-run",
    "cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && scripts/run_with_project_env.sh python3 scripts/fetch_search_console.py --dry-run",
]

SAFE_LOG_PATHS = [
    "pipeline/logs/analytics.log",
    "pipeline/logs/daily-traffic-card.log",
    "pipeline/logs/fetch-search-console.log",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(data, dict):
        return None, "not_object"
    return data, None


def file_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def age_hours(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    return round(max((now - value).total_seconds(), 0) / 3600, 2)


def newer_or_same(left: datetime | None, right: datetime | None) -> bool:
    return left is not None and right is not None and left >= right


def rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_DIR))


def summarize_daily_report(data: dict[str, Any] | None, error: str | None, now: datetime, max_age_hours: float) -> dict[str, Any]:
    generated_at = parse_time(data.get("generated_at") if data else None)
    mtime = parse_time(file_mtime(DAILY_REPORT))
    evidence_time = mtime or generated_at
    stale = True if evidence_time is None else age_hours(evidence_time, now) > max_age_hours

    daily_rows = data.get("daily_pageviews", []) if data else []
    top_pages = data.get("top_pages_7d", []) if data else []
    sources = data.get("traffic_sources_7d", []) if data else []
    search_console = data.get("search_console", {}) if data else {}

    return {
        "artifact": rel(DAILY_REPORT),
        "exists": DAILY_REPORT.exists(),
        "read_status": "ok" if error is None else error,
        "generated_at": data.get("generated_at") if data else None,
        "file_mtime": file_mtime(DAILY_REPORT),
        "age_hours": age_hours(evidence_time, now),
        "evidence_at": evidence_time.isoformat() if evidence_time else None,
        "fresh": not stale and error is None,
        "property_id": data.get("property_id") if data else None,
        "site": data.get("site") if data else None,
        "counts": {
            "daily_pageview_rows": len(daily_rows) if isinstance(daily_rows, list) else 0,
            "top_pages_7d": len(top_pages) if isinstance(top_pages, list) else 0,
            "traffic_sources_7d": len(sources) if isinstance(sources, list) else 0,
            "search_console_top_queries": len(search_console.get("top_queries", [])) if isinstance(search_console, dict) else 0,
        },
    }


def summarize_search_console(data: dict[str, Any] | None, error: str | None, now: datetime, max_age_hours: float) -> dict[str, Any]:
    generated_at = parse_time(data.get("generated_at") if data else None)
    mtime = parse_time(file_mtime(SEARCH_CONSOLE_REPORT))
    evidence_time = mtime or generated_at
    stale = True if evidence_time is None else age_hours(evidence_time, now) > max_age_hours

    rows = data.get("rows", []) if data else []
    return {
        "artifact": rel(SEARCH_CONSOLE_REPORT),
        "exists": SEARCH_CONSOLE_REPORT.exists(),
        "read_status": "ok" if error is None else error,
        "generated_at": data.get("generated_at") if data else None,
        "file_mtime": file_mtime(SEARCH_CONSOLE_REPORT),
        "age_hours": age_hours(evidence_time, now),
        "evidence_at": evidence_time.isoformat() if evidence_time else None,
        "fresh": not stale and error is None,
        "site": data.get("site") if data else None,
        "days": data.get("days") if data else None,
        "row_count": data.get("row_count", len(rows) if isinstance(rows, list) else 0) if data else 0,
    }


def summarize_oauth_blocker(
    data: dict[str, Any] | None,
    error: str | None,
    daily_summary: dict[str, Any],
    search_console_summary: dict[str, Any],
) -> dict[str, Any]:
    services = []
    if data and isinstance(data.get("services"), list):
        for service in data["services"]:
            if not isinstance(service, dict):
                continue
            services.append(
                {
                    "service": service.get("service"),
                    "status": service.get("status"),
                    "error_class": service.get("error_class"),
                    "reauth_command": service.get("reauth_command"),
                    "validation_command": service.get("validation_command"),
                }
            )

    checked_at = parse_time(data.get("checked_at") if data else None)
    mtime = parse_time(file_mtime(OAUTH_SENTINEL))
    evidence_at = checked_at or mtime
    fresh_validation_after_sentinel = bool(
        daily_summary.get("fresh")
        and search_console_summary.get("fresh")
        and newer_or_same(parse_time(daily_summary.get("evidence_at")), evidence_at)
        and newer_or_same(parse_time(search_console_summary.get("evidence_at")), evidence_at)
    )
    raw_blocked = bool(data and data.get("status") == "blocked_human_reauthorization_required")
    blocked = raw_blocked and not fresh_validation_after_sentinel
    return {
        "artifact": rel(OAUTH_SENTINEL),
        "exists": OAUTH_SENTINEL.exists(),
        "read_status": "ok" if error is None else error,
        "checked_at": data.get("checked_at") if data else None,
        "file_mtime": file_mtime(OAUTH_SENTINEL),
        "evidence_at": evidence_at.isoformat() if evidence_at else None,
        "blocked": blocked,
        "superseded_by_fresh_validation": raw_blocked and fresh_validation_after_sentinel,
        "blocked_by": data.get("blocked_by") if data else None,
        "services": services,
    }


def build_payload(max_age_hours: float, source_command: str) -> dict[str, Any]:
    now = utc_now()
    daily, daily_error = read_json(DAILY_REPORT)
    search_console, search_console_error = read_json(SEARCH_CONSOLE_REPORT)
    oauth, oauth_error = read_json(OAUTH_SENTINEL)

    daily_summary = summarize_daily_report(daily, daily_error, now, max_age_hours)
    search_console_summary = summarize_search_console(search_console, search_console_error, now, max_age_hours)
    oauth_summary = summarize_oauth_blocker(oauth, oauth_error, daily_summary, search_console_summary)

    blocked = oauth_summary["blocked"]
    fresh = bool(daily_summary["fresh"] and search_console_summary["fresh"] and not blocked)
    status = "fresh" if fresh else "blocked_oauth_reauthorization_required" if blocked else "stale_or_incomplete"

    return {
        "status": status,
        "checked_at": now.isoformat(),
        "max_age_hours": max_age_hours,
        "source_command": source_command,
        "safe_source_commands": SAFE_SOURCE_COMMANDS,
        "safe_log_paths": SAFE_LOG_PATHS,
        "redaction_policy": "Counts, timestamps, public property/site identifiers, safe command names, and log paths only. No credentials, token values, OAuth response bodies, Authorization headers, raw GA4 rows, raw Search Console queries, or account email are stored.",
        "blocked_by": "OPE-133" if blocked else None,
        "artifacts": {
            "daily_report": daily_summary,
            "search_console": search_console_summary,
            "oauth_blocker": oauth_summary,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--static-output", type=Path, default=DEFAULT_STATIC_OUTPUT)
    parser.add_argument("--max-age-hours", type=float, default=30.0)
    parser.add_argument(
        "--source-command",
        default="post-reauth validation commands",
        help="Redacted command name or command sequence that produced the source artifacts.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args.max_age_hours, args.source_command)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    for output in (args.output, args.static_output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print(f"[analytics-freshness-evidence] wrote {output.relative_to(PROJECT_DIR)} status={payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
