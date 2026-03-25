#!/usr/bin/env python3
"""
Test Ghost publish: reads a Hugo article, maps to Ghost Admin API payload,
validates structure, prints JSON. Use --live to actually POST to Ghost.

Usage:
    python3 test_ghost_publish.py                           # random article, dry-run
    python3 test_ghost_publish.py content/posts/2026-03-15-foo.md  # specific article
    python3 test_ghost_publish.py --live                    # publish to Ghost for real
"""

import argparse
import glob
import json
import os
import random
import re
import sys

# ── Parse Hugo markdown frontmatter ─────────────────────────────────────────

def parse_frontmatter(filepath: str) -> dict:
    """Parse YAML frontmatter + body from a Hugo markdown file."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    # Split on --- delimiters
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        raise ValueError(f"No valid frontmatter in {filepath}")

    yaml_block = match.group(1)
    body = match.group(2).strip()

    # Minimal YAML parser (avoids PyYAML dependency)
    meta = {}
    current_list_key = None
    for line in yaml_block.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item under current key
        if stripped.startswith("- ") and current_list_key:
            val = stripped[2:].strip().strip('"').strip("'")
            meta.setdefault(current_list_key, []).append(val)
            continue

        # Key: value
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            current_list_key = None

            if val == "":
                # Might be start of a list
                current_list_key = key
            elif val.lower() in ("true", "false"):
                meta[key] = val.lower() == "true"
            else:
                meta[key] = val
        else:
            current_list_key = None

    meta["_body"] = body
    meta["_filepath"] = filepath
    return meta


def frontmatter_to_article(meta: dict) -> dict:
    """Convert parsed frontmatter dict to pipeline article dict format."""
    categories = meta.get("categories", [])
    return {
        "title": meta.get("title", "Untitled"),
        "content": meta.get("_body", ""),
        "category": categories[0] if categories else "",
        "tags": meta.get("tags", []),
        "summary": meta.get("description", meta.get("summary", "")),
        "description": meta.get("description", ""),
        "image": meta.get("image", ""),
        "image_alt": meta.get("image_alt", ""),
        "source_name": meta.get("source_name", ""),
        "source_url": meta.get("source_url", ""),
        "source_domain": meta.get("source_domain", ""),
        "journalist_note": meta.get("journalist_note", ""),
        "content_type": meta.get("content_type", ""),
        "keywords": meta.get("keywords", []),
        "date": meta.get("date", ""),
    }


# ── Validation ──────────────────────────────────────────────────────────────

REQUIRED_FIELDS = ["title", "html", "status"]
VALID_STATUSES = ["draft", "published", "scheduled"]


def validate_payload(payload: dict) -> list:
    """Validate Ghost post payload. Returns list of issues (empty = valid)."""
    issues = []
    post = payload.get("posts", [{}])[0] if "posts" in payload else payload

    # Required fields
    for field in REQUIRED_FIELDS:
        if not post.get(field):
            issues.append(f"MISSING required field: {field}")

    # Status
    status = post.get("status", "")
    if status and status not in VALID_STATUSES:
        issues.append(f"INVALID status: '{status}' (must be one of {VALID_STATUSES})")

    # Title length
    title = post.get("title", "")
    if len(title) > 300:
        issues.append(f"Title too long: {len(title)} chars (Ghost max ~300)")

    # Tags format
    tags = post.get("tags", [])
    if not isinstance(tags, list):
        issues.append(f"Tags must be a list, got {type(tags).__name__}")
    else:
        for i, tag in enumerate(tags):
            if isinstance(tag, dict):
                if "name" not in tag:
                    issues.append(f"Tag [{i}] missing 'name' field: {tag}")
            elif not isinstance(tag, str):
                issues.append(f"Tag [{i}] invalid type: {type(tag).__name__}")

    # Image URL
    feature_image = post.get("feature_image", "")
    if feature_image and not feature_image.startswith(("http://", "https://", "/")):
        issues.append(f"Suspicious feature_image URL: {feature_image}")

    # HTML content
    html = post.get("html", "")
    if html and len(html) < 50:
        issues.append(f"HTML content suspiciously short: {len(html)} chars")

    # Meta fields
    meta_title = post.get("meta_title", "")
    if meta_title and len(meta_title) > 300:
        issues.append(f"meta_title too long: {len(meta_title)} chars (max 300)")

    meta_desc = post.get("meta_description", "")
    if meta_desc and len(meta_desc) > 500:
        issues.append(f"meta_description too long: {len(meta_desc)} chars (max 500)")

    custom_excerpt = post.get("custom_excerpt", "")
    if custom_excerpt and len(custom_excerpt) > 300:
        issues.append(f"custom_excerpt too long: {len(custom_excerpt)} chars (max 300)")

    return issues


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test Ghost publish payload")
    parser.add_argument("article", nargs="?", help="Path to Hugo markdown article (random if omitted)")
    parser.add_argument("--live", action="store_true", help="Actually publish to Ghost (requires env vars)")
    parser.add_argument("--publish", action="store_true", help="Set status=published (default: draft)")
    parser.add_argument("--all", action="store_true", help="Process all articles in content/posts/")
    args = parser.parse_args()

    # Find article(s)
    if args.article:
        files = [args.article]
    elif args.all:
        files = sorted(glob.glob("content/posts/*.md"))
    else:
        all_posts = glob.glob("content/posts/*.md")
        if not all_posts:
            print("ERROR: No articles found in content/posts/")
            sys.exit(1)
        files = [random.choice(all_posts)]

    print(f"Processing {len(files)} article(s)...\n")

    # Import GhostPublisher for payload mapping
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ghost_publisher import GhostPublisher

    total_issues = 0

    for filepath in files:
        print(f"{'='*70}")
        print(f"FILE: {filepath}")
        print(f"{'='*70}")

        try:
            meta = parse_frontmatter(filepath)
            article = frontmatter_to_article(meta)
        except Exception as e:
            print(f"  ❌ Parse error: {e}\n")
            total_issues += 1
            continue

        # Build Ghost payload using GhostPublisher's mapping
        try:
            gp = GhostPublisher.__new__(GhostPublisher)
            gp.api_url = os.environ.get("GHOST_API_URL", "https://cms.uutistenlukija.fi")
            post_data = gp._article_to_post(article, publish=args.publish)
        except Exception as e:
            print(f"  ❌ Mapping error: {e}\n")
            total_issues += 1
            continue

        payload = {"posts": [post_data]}

        # Validate
        issues = validate_payload(payload)
        if issues:
            print(f"\n  ⚠️  VALIDATION ISSUES ({len(issues)}):")
            for issue in issues:
                print(f"    - {issue}")
            total_issues += len(issues)
        else:
            print(f"\n  ✅ Payload valid")

        # Summary
        post = post_data
        print(f"\n  Title:     {post.get('title', '?')[:80]}")
        print(f"  Status:    {post.get('status', '?')}")
        print(f"  Tags:      {[t.get('name', t) if isinstance(t, dict) else t for t in post.get('tags', [])]}")
        print(f"  Image:     {post.get('feature_image', '(none)')[:80]}")
        print(f"  Excerpt:   {post.get('custom_excerpt', '(none)')[:80]}")
        print(f"  HTML len:  {len(post.get('html', ''))} chars")

        if not args.all:
            # Print full JSON for single article
            print(f"\n{'─'*70}")
            print("GHOST API PAYLOAD:")
            print(f"{'─'*70}")
            print(json.dumps(payload, indent=2, ensure_ascii=False))

        # Live publish
        if args.live:
            ghost_url = os.environ.get("GHOST_API_URL", "")
            ghost_key = os.environ.get("GHOST_ADMIN_API_KEY", "")
            if not ghost_url or not ghost_key:
                print(f"\n  ❌ Cannot publish: GHOST_API_URL and GHOST_ADMIN_API_KEY must be set")
            else:
                try:
                    gp_live = GhostPublisher()
                    url = gp_live.publish(article, publish=args.publish)
                    print(f"\n  🟢 Published: {url}")
                except Exception as e:
                    print(f"\n  🔴 Publish failed: {e}")

        print()

    # Summary
    if args.all:
        print(f"{'='*70}")
        print(f"TOTAL: {len(files)} articles, {total_issues} issues")
        print(f"{'='*70}")

    sys.exit(1 if total_issues > 0 else 0)


if __name__ == "__main__":
    main()
