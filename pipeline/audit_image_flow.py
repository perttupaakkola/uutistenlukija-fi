#!/usr/bin/env python3
"""Audit recent article image metadata for obvious Image Flow v2 mismatches."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_candidate_guard import build_image_intent, score_image_candidate  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = PROJECT_ROOT / "content" / "posts"


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    try:
        block = text.split("---", 2)[1]
    except IndexError:
        return {}
    data: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def _post_sort_key(path: Path) -> tuple[str, str]:
    fm = _frontmatter(path)
    return (fm.get("date", ""), path.name)


def audit_recent(limit: int) -> list[dict[str, object]]:
    posts = sorted(POSTS_DIR.glob("*.md"), key=_post_sort_key, reverse=True)[:limit]
    rows: list[dict[str, object]] = []
    for path in posts:
        fm = _frontmatter(path)
        image_source = fm.get("image_source") or ("category_fallback" if fm.get("image_category_fallback") == "true" else "")
        image = fm.get("image", "")
        source_url = fm.get("image_source_url", "")
        status = "ok"
        reason = image_source or "no source metadata"

        if image_source in {"unsplash", "pexels"} or source_url:
            candidate = {
                "id": fm.get("image_id") or path.stem,
                "alt": fm.get("image_alt", ""),
                "photo_page": source_url,
                "pexels_url": source_url,
                "url": image,
            }
            intent = build_image_intent(
                fm.get("title", ""),
                fm.get("category", ""),
                summary=fm.get("description", ""),
                query=fm.get("image_query", ""),
            )
            decision = score_image_candidate(
                candidate,
                intent=intent,
                query=fm.get("image_query", ""),
                title=fm.get("title", ""),
                summary=fm.get("description", ""),
                provider=image_source or "stock",
            )
            if not decision.accepted:
                status = "flag"
                reason = "; ".join(decision.reasons)
            else:
                reason = f"{image_source or 'stock'} score={decision.score}"
        elif not image:
            status = "missing"
            reason = "missing image"

        rows.append({
            "file": str(path.relative_to(PROJECT_ROOT)),
            "title": fm.get("title", ""),
            "date": fm.get("date", ""),
            "image": image,
            "image_source": image_source,
            "status": status,
            "reason": reason,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    rows = audit_recent(args.limit)
    flags = [row for row in rows if row["status"] != "ok"]
    print(f"image_flow_audit generated_at={datetime.now(timezone.utc).isoformat()} checked={len(rows)} flags={len(flags)}")
    for row in rows:
        print(f"{row['status']}\t{row['file']}\t{row['image_source'] or '-'}\t{row['reason']}")
    return 1 if any(row["status"] == "flag" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
