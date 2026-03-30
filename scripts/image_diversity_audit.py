#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
FIELD_RE = re.compile(r'^(?P<key>[A-Za-z0-9_]+):\s*(?P<value>.*)$')


def parse_frontmatter(text: str) -> dict[str, object]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    data: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list_key:
            data.setdefault(current_list_key, [])
            assert isinstance(data[current_list_key], list)
            data[current_list_key].append(_strip_quotes(line[4:].strip()))
            continue
        m_field = FIELD_RE.match(line)
        if not m_field:
            current_list_key = None
            continue
        key = m_field.group("key")
        value = m_field.group("value").strip()
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = _strip_quotes(value)
            current_list_key = None
    return data


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def canonicalize_image_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return url


def collect_articles(posts_dir: Path) -> list[dict[str, object]]:
    articles: list[dict[str, object]] = []
    for path in sorted(posts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        image = str(fm.get("image", "") or "").strip()
        if not image:
            continue
        categories = fm.get("categories", [])
        if not isinstance(categories, list):
            categories = [str(categories)] if categories else []
        articles.append({
            "path": str(path),
            "slug": path.stem,
            "title": str(fm.get("title", path.stem)),
            "date": str(fm.get("date", "")),
            "image": image,
            "image_base": canonicalize_image_url(image),
            "image_source_url": str(fm.get("image_source_url", "") or ""),
            "image_credit": str(fm.get("image_credit", "") or ""),
            "source_name": str(fm.get("source_name", "") or ""),
            "categories": categories,
            "category": categories[0] if categories else "",
        })
    return articles


def build_report(articles: list[dict[str, object]], min_count: int = 2) -> dict[str, object]:
    by_exact: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    by_base: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    host_counts: Counter[str] = Counter()

    for article in articles:
        image = str(article["image"])
        base = str(article["image_base"])
        by_exact[image].append(article)
        by_base[base].append(article)
        host = urlparse(image).netloc or "local"
        host_counts[host] += 1

    exact_dupes = [
        {
            "image": image,
            "count": len(items),
            "host": urlparse(image).netloc or "local",
            "titles": [item["title"] for item in items],
            "articles": items,
        }
        for image, items in by_exact.items()
        if len(items) >= min_count
    ]
    exact_dupes.sort(key=lambda x: (-x["count"], x["image"]))

    base_dupes = [
        {
            "image_base": image_base,
            "count": len(items),
            "host": urlparse(image_base).netloc or "local",
            "variants": len({str(item['image']) for item in items}),
            "titles": [item["title"] for item in items],
            "articles": items,
        }
        for image_base, items in by_base.items()
        if len(items) >= min_count
    ]
    base_dupes.sort(key=lambda x: (-x["count"], x["image_base"]))

    return {
        "total_articles_with_images": len(articles),
        "unique_exact_images": len(by_exact),
        "unique_base_images": len(by_base),
        "duplicate_exact_groups": len(exact_dupes),
        "duplicate_base_groups": len(base_dupes),
        "top_hosts": host_counts.most_common(10),
        "worst_exact_duplicates": exact_dupes[:20],
        "worst_base_duplicates": base_dupes[:20],
    }


def print_report(report: dict[str, object]) -> None:
    print("=" * 60)
    print(" Image Diversity Audit")
    print("=" * 60)
    print(f"Articles with images:     {report['total_articles_with_images']}")
    print(f"Unique exact image URLs: {report['unique_exact_images']}")
    print(f"Unique base image URLs:  {report['unique_base_images']}")
    print(f"Exact duplicate groups:  {report['duplicate_exact_groups']}")
    print(f"Base duplicate groups:   {report['duplicate_base_groups']}")
    print()
    print("Top image hosts:")
    for host, count in report["top_hosts"]:
        print(f"- {host}: {count}")
    print()
    print("Worst exact duplicates:")
    if not report["worst_exact_duplicates"]:
        print("- none")
    for group in report["worst_exact_duplicates"]:
        print(f"- {group['count']}x :: {group['host']} :: {group['image']}")
        for article in group["articles"][:8]:
            print(f"    • {article['date'][:10]} :: {article['title']}")
        if group['count'] > 8:
            print(f"    • … +{group['count'] - 8} more")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect duplicate featured images across articles")
    parser.add_argument("--posts-dir", default="content/posts", help="Path to Hugo posts directory")
    parser.add_argument("--min-count", type=int, default=2, help="Minimum duplicate count to report")
    parser.add_argument("--json-out", help="Optional path for machine-readable report")
    args = parser.parse_args()

    posts_dir = Path(args.posts_dir)
    articles = collect_articles(posts_dir)
    report = build_report(articles, min_count=args.min_count)
    print_report(report)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
