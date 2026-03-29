#!/usr/bin/env python3
"""Generate static/search-index.json for /haku/ Fuse.js client-side search.

Fields emitted match exactly what layouts/_default/haku.html expects:
  title, description, category, url, date
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
POSTS_DIR = PROJECT_DIR / "content" / "posts"
OUTPUT_PATH = PROJECT_DIR / "static" / "search-index.json"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse simple YAML frontmatter without external deps."""
    meta: dict = {}
    body = text

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        return meta, body

    fm_raw = match.group(1)
    body = match.group(2).strip()

    current_key = None
    list_buffer: list[str] = []

    def flush_list() -> None:
        nonlocal current_key, list_buffer
        if current_key is not None:
            meta[current_key] = list_buffer[:]
        current_key = None
        list_buffer = []

    for raw_line in fm_raw.splitlines():
        line = raw_line.rstrip()

        if re.match(r"^\s+-\s+", line):
            value = re.sub(r"^\s+-\s+", "", line).strip().strip('"\'')
            if current_key is not None:
                list_buffer.append(value)
            continue

        kv = re.match(r"^(\w[\w_-]*)\s*:\s*(.*)$", line)
        if not kv:
            continue

        flush_list()
        key = kv.group(1)
        value = kv.group(2).strip()

        if value == "":
            current_key = key
            list_buffer = []
            continue

        value = value.strip('"\'')
        lowered = value.lower()
        if lowered == "true":
            meta[key] = True
        elif lowered == "false":
            meta[key] = False
        else:
            meta[key] = value

    flush_list()
    return meta, body


def slugify_category(category: str) -> str:
    return category.strip().lower().replace(" ", "-")


def article_slug_from_path(path: Path) -> str:
    name = path.stem
    match = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", name)
    return match.group(1) if match else name


def build_url(path: Path, category: str) -> str:
    # Articles live at /posts/<slug>/ — not /categories/<cat>/<slug>/
    return f"/posts/{path.stem}/"


def build_record(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    meta, _body = parse_frontmatter(text)

    if meta.get("draft") is True:
        return None

    title = str(meta.get("title", "")).strip()
    description = str(meta.get("description", "")).strip()
    date = str(meta.get("date", "")).strip()

    categories = meta.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    category = str(categories[0]).strip() if categories else ""

    if not title or not category:
        return None

    return {
        "title": title,
        "description": description,
        "category": category,
        "url": build_url(path, category),
        "date": date[:10] if len(date) >= 10 else date,
    }


def main() -> int:
    articles: list[dict] = []

    for path in sorted(POSTS_DIR.glob("*.md"), reverse=True):
        try:
            record = build_record(path)
        except Exception as exc:
            print(f"[search-index] Skipping {path.name}: {exc}")
            continue
        if record:
            articles.append(record)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[search-index] Wrote {len(articles)} articles to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
