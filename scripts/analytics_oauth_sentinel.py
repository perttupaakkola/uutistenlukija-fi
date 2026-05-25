#!/usr/bin/env python3
"""Write a non-secret analytics OAuth failure sentinel.

The sentinel is intentionally small and boring: it records which analytics
integration needs human OAuth reauthorization without copying token values,
OAuth responses, or Authorization headers into public/static artifacts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_DIR / "analytics" / "oauth-failure-sentinel.json"
DEFAULT_STATIC_OUTPUT = PROJECT_DIR / "static" / "api" / "analytics-oauth-status.json"

SERVICE_METADATA = {
    "ga4": {
        "label": "Google Analytics 4",
        "property_id": "529369568",
        "reauth_command": "cd /home/pertt/.openclaw/workspace && python3 scripts/reauth_ga4.py",
        "validation_command": (
            "cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && "
            "scripts/run_with_project_env.sh python3 scripts/daily_traffic_card.py --dry-run"
        ),
    },
    "search_console": {
        "label": "Google Search Console",
        "site": "sc-domain:uutistenlukija.fi",
        "reauth_command": "cd /home/pertt/.openclaw/workspace && python3 scripts/reauth_search_console.py",
        "validation_command": (
            "cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && "
            "scripts/run_with_project_env.sh python3 scripts/fetch_search_console.py --dry-run"
        ),
    },
}

SAFE_LOG_PATHS = [
    "pipeline/logs/analytics.log",
    "pipeline/logs/daily-traffic-card.log",
    "pipeline/logs/fetch-search-console.log",
]


def build_payload(services: list[str], source_command: str, source_log: str) -> dict:
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    service_entries = []
    for service in services:
        metadata = SERVICE_METADATA[service]
        entry = {
            "service": service,
            "label": metadata["label"],
            "status": "blocked_human_reauthorization_required",
            "error_class": "oauth_invalid_grant",
            "error_summary": "OAuth refresh failed with invalid_grant; token values are intentionally omitted.",
            "reauth_command": metadata["reauth_command"],
            "validation_command": metadata["validation_command"],
        }
        if "property_id" in metadata:
            entry["property_id"] = metadata["property_id"]
        if "site" in metadata:
            entry["site"] = metadata["site"]
        service_entries.append(entry)

    return {
        "status": "blocked_human_reauthorization_required",
        "checked_at": checked_at,
        "source_command": source_command,
        "source_log": source_log,
        "safe_log_paths": SAFE_LOG_PATHS,
        "blocked_by": "OPE-133",
        "account_hint_required": True,
        "token_policy": "No credentials, token values, OAuth response bodies, or Authorization headers are stored in this sentinel.",
        "services": service_entries,
        "post_reauth_validation": [
            (
                "cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && "
                "SECRETS_DIR=/home/pertt/.openclaw/workspace/.secrets bash pipeline/check-analytics.sh"
            ),
            SERVICE_METADATA["ga4"]["validation_command"],
            SERVICE_METADATA["search_console"]["validation_command"],
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service",
        action="append",
        choices=sorted(SERVICE_METADATA),
        required=True,
        help="Service that failed OAuth refresh. Repeat for multiple services.",
    )
    parser.add_argument(
        "--source-command",
        default="unknown",
        help="Command that observed the failure. Do not include secrets.",
    )
    parser.add_argument(
        "--source-log",
        default="unknown",
        help="Log path that contains the redacted operational evidence.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Private/non-public sentinel output path.",
    )
    parser.add_argument(
        "--static-output",
        type=Path,
        default=DEFAULT_STATIC_OUTPUT,
        help="Public-safe status output path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the sentinel payload without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    services = list(dict.fromkeys(args.service))
    payload = build_payload(services, args.source_command, args.source_log)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    for output in (args.output, args.static_output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print(f"[analytics-oauth-sentinel] wrote {output.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
