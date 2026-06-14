#!/usr/bin/env python3
"""Create Buffer-ready draft payloads without calling Buffer or X APIs.

This is an approval-gated handoff helper. It selects the same recent articles as
the existing X dry-run path, composes post text locally, and emits JSON or text
for review. It never reads token contents and never queues, schedules, or posts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import x_auto_poster


CADENCE_TARGETS = (
    "draft-only morning slot, 07:00-08:30 Europe/Helsinki",
    "draft-only evening slot, 17:00-18:30 Europe/Helsinki",
)


def select_candidates(hours: int, limit: int) -> list[dict]:
    posted_urls = x_auto_poster.load_posted_urls()
    articles = x_auto_poster.load_recent_articles(hours=hours)
    candidates = [
        article
        for article in articles
        if article.get("title")
        and article.get("_url") not in posted_urls
        and not x_auto_poster.is_spam(article)
    ]
    candidates.sort(
        key=lambda article: (
            int(article.get("source_tier", 2)),
            -article["_pub_date"].timestamp(),
        )
    )
    return candidates[:limit]


def build_payload(candidates: list[dict], hours: int, max_posts: int) -> dict:
    profile_id = os.environ.get("BUFFER_PROFILE_ID") or "BUFFER_PROFILE_ID_PLACEHOLDER"
    profile_status = "env" if os.environ.get("BUFFER_PROFILE_ID") else "placeholder"
    drafts = []

    for index, article in enumerate(candidates):
        text = x_auto_poster.compose_tweet(article)
        drafts.append(
            {
                "provider": "buffer",
                "mode": "draft_only",
                "profile_id": profile_id,
                "profile_id_status": profile_status,
                "text": text,
                "url": article.get("_url", ""),
                "title": article.get("title", ""),
                "category": _first_category(article),
                "cadence_target": CADENCE_TARGETS[index % len(CADENCE_TARGETS)],
                "scheduled_at": None,
                "approval_required": True,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "pipeline/buffer_dry_run.py",
        "policy": {
            "public_actions_disabled": True,
            "allowed_use": "review Buffer draft payloads only",
            "requires_approval_before": [
                "account signup completion",
                "posting",
                "queueing",
                "scheduling",
                "replies",
                "direct_messages",
                "follows",
                "reposts",
                "payment",
                "campaign_launch",
            ],
        },
        "selection": {
            "hours": hours,
            "max_posts": max_posts,
            "draft_count": len(drafts),
        },
        "missing_fields": [
            "BUFFER_PROFILE_ID"
        ]
        if profile_status == "placeholder"
        else [],
        "drafts": drafts,
    }


def _first_category(article: dict) -> str:
    categories = article.get("categories", [])
    if isinstance(categories, list) and categories:
        return str(categories[0])
    if categories:
        return str(categories).split(",")[0].strip()
    return ""


def write_output(payload: dict, output: Path | None, output_format: str) -> None:
    if output_format == "text":
        rendered = render_text(payload)
    else:
        rendered = json.dumps(payload, indent=2, ensure_ascii=False)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"[buffer_dry_run] Wrote {len(payload['drafts'])} draft payload(s) to {output}")
    else:
        print(rendered)


def render_text(payload: dict) -> str:
    lines = [
        "Buffer draft payload dry-run",
        f"generated_at: {payload['generated_at']}",
        f"draft_count: {payload['selection']['draft_count']}",
        "public_actions_disabled: true",
        "",
    ]
    if payload["missing_fields"]:
        lines.append("missing_fields: " + ", ".join(payload["missing_fields"]))
        lines.append("")
    for index, draft in enumerate(payload["drafts"], 1):
        lines.extend(
            [
                f"Draft {index}",
                f"title: {draft['title']}",
                f"url: {draft['url']}",
                f"cadence_target: {draft['cadence_target']}",
                "text:",
                draft["text"],
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit Buffer-ready draft payloads without public Buffer/X actions."
    )
    parser.add_argument("--hours", type=int, default=3, help="Look back N hours for articles")
    parser.add_argument("--max-posts", type=int, default=3, help="Max draft payloads to emit")
    parser.add_argument("--output", type=Path, help="Optional output path for the dry-run payload")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()

    candidates = select_candidates(hours=args.hours, limit=args.max_posts)
    payload = build_payload(candidates, hours=args.hours, max_posts=args.max_posts)
    write_output(payload, args.output, args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
