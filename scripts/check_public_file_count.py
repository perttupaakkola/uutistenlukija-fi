#!/usr/bin/env python3
"""Fail CI when Hugo output is too close to Cloudflare Pages' file limit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def count_files(root: Path) -> tuple[int, list[tuple[str, int]]]:
    counts: dict[str, int] = {}
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        total += 1
        try:
            top = path.relative_to(root).parts[0]
        except IndexError:
            top = "."
        counts[top] = counts.get(top, 0) + 1
    return total, sorted(counts.items(), key=lambda item: item[1], reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", default="public", type=Path)
    parser.add_argument("--limit", default=20_000, type=int)
    parser.add_argument("--min-headroom", default=1_000, type=int)
    parser.add_argument("--top", default=10, type=int)
    args = parser.parse_args()

    public_dir = args.public_dir
    if not public_dir.exists():
        raise SystemExit(f"[file-count] Missing public directory: {public_dir}")

    total, top_dirs = count_files(public_dir)
    headroom = args.limit - total
    payload = {
        "status": "ok",
        "public_dir": str(public_dir),
        "files": total,
        "limit": args.limit,
        "headroom": headroom,
        "min_headroom": args.min_headroom,
        "top_dirs": [{"dir": name, "files": count} for name, count in top_dirs[: args.top]],
    }

    if total > args.limit:
        payload["status"] = "over_limit"
    elif headroom < args.min_headroom:
        payload["status"] = "low_headroom"

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
