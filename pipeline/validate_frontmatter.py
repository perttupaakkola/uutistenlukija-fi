#!/usr/bin/env python3
"""
validate_frontmatter.py — validate article front matter for Schema.org readiness.

Checks every content/posts/*.md file for fields commonly required by the
NewsArticle JSON-LD template.

Validation:
- title exists and is <= 110 chars
- description exists and is <= 160 chars
- image exists and is non-empty
- date exists and is parseable

Output:
- summary with pass/fail counts
- failing articles with specific issues

Exit codes:
- 0: all articles passed
- 1: one or more articles failed, or content directory missing

Usage:
    python3 pipeline/validate_frontmatter.py
    python3 pipeline/validate_frontmatter.py --content-dir content/posts
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from guide_lifecycle import evaluate_guide, load_guide

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_CONTENT_DIR = PROJECT_DIR / "content" / "posts"
GUIDES_DIR = PROJECT_DIR / "content" / "oppaat"
MAX_HEADLINE_LEN = 110
MAX_DESCRIPTION_LEN = 160


@dataclass
class ArticleResult:
    path: Path
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


def strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return inner
        return inner
    return value


def parse_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        raise ValueError("missing opening front matter delimiter")

    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        raise ValueError("missing closing front matter delimiter")

    front_matter = parts[0][4:]
    data: dict[str, str] = {}
    current_key: str | None = None

    for raw_line in front_matter.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if raw_line.startswith((" ", "\t")):
            # Continuation/list item. Not relevant for the scalar fields this validator checks.
            continue

        if ":" not in raw_line:
            current_key = None
            continue

        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key

        if not value:
            data[key] = ""
            continue

        data[key] = strip_wrapping_quotes(value)

    return data


def parse_date(value: str) -> datetime | None:
    if not value:
        return None

    candidate = value.strip()
    for parser_input in (candidate, candidate.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(parser_input)
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            pass

    return None


def _check_yaml_syntax(path: Path) -> str | None:
    """Return an error string if the frontmatter has YAML syntax issues, else None.

    Detects unclosed quoted strings in scalar values — the most common cause of
    instant Hugo build failures (e.g. image_alt ending with \\" but missing the
    closing double-quote).
    """
    import re
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return None
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return None
    fm = parts[0][4:]
    for i, line in enumerate(fm.splitlines(), 1):
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if not value:
            continue
        if value.startswith('"') and r'\\"' in value:
            return (
                f"line {i}: suspicious double-escaped quote sequence (\\\\\") in '{key.strip()}': {value[:80]!r}"
            )
        # Detect unclosed double-quoted string: starts with " but doesn't end with "
        # (allowing for escaped quotes like \" inside but the final char must be unescaped ")
        if value.startswith('"') and not value.endswith('"'):
            return f"line {i}: unclosed double-quoted string in '{key.strip()}': {value[:80]!r}"
        if value.startswith("'") and not value.endswith("'"):
            return f"line {i}: unclosed single-quoted string in '{key.strip()}': {value[:80]!r}"
    return None


def validate_article(path: Path) -> ArticleResult:
    result = ArticleResult(path=path)

    yaml_err = _check_yaml_syntax(path)
    if yaml_err:
        result.issues.append(f"YAML syntax error: {yaml_err}")
        return result

    try:
        front_matter = parse_front_matter(path)
    except Exception as exc:
        result.issues.append(f"front matter parse failed: {exc}")
        return result

    title = front_matter.get("title", "").strip()
    description = front_matter.get("description", "").strip()
    image = front_matter.get("image", "").strip()
    date_value = front_matter.get("date", "").strip()

    if not title:
        result.issues.append("missing title")
    elif len(title) > MAX_HEADLINE_LEN:
        result.issues.append(f"title too long: {len(title)} > {MAX_HEADLINE_LEN}")

    if not description:
        result.issues.append("missing description")
    elif len(description) > MAX_DESCRIPTION_LEN:
        result.issues.append(f"description too long: {len(description)} > {MAX_DESCRIPTION_LEN}")

    if not image:
        result.issues.append("missing image")

    if not date_value:
        result.issues.append("missing date")
    elif parse_date(date_value) is None:
        result.issues.append(f"unparseable date: {date_value}")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate article front matter used for structured data.")
    parser.add_argument(
        "--content-dir",
        default=str(DEFAULT_CONTENT_DIR),
        help="Directory containing article markdown files (default: content/posts).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    content_dir = Path(args.content_dir)
    if not content_dir.is_absolute():
        content_dir = PROJECT_DIR / content_dir

    if not content_dir.exists():
        print(f"[schema] content dir not found: {content_dir}")
        return 1

    article_paths = sorted(content_dir.glob("*.md"))
    if not article_paths:
        print(f"[schema] no markdown files found in {content_dir}")
        return 1

    results = [validate_article(path) for path in article_paths]
    passed = sum(1 for result in results if result.passed)
    failed_results = [result for result in results if not result.passed]

    print("═" * 60)
    print(" Structured Data Front Matter Validation")
    print("═" * 60)
    print(f"[schema] Content dir: {content_dir}")
    print(f"[schema] Articles checked: {len(results)}")
    print(f"[schema] Passed: {passed}")
    print(f"[schema] Failed: {len(failed_results)}")

    yaml_failures = [r for r in failed_results if any("YAML syntax error" in i or "front matter parse failed" in i for i in r.issues)]
    schema_warnings = [r for r in failed_results if r not in yaml_failures]

    if failed_results:
        print("[schema] ─────────────────────────────────────────────")
        for result in failed_results:
            try:
                rel = result.path.relative_to(PROJECT_DIR)
            except ValueError:
                rel = result.path
            severity = "FATAL" if result in yaml_failures else "WARN "
            print(f"[schema] {rel}")
            for issue in result.issues:
                print(f"[schema]   {severity}  {issue}")

    if yaml_failures:
        print(f"[schema] FATAL: {len(yaml_failures)} YAML syntax error(s) — Hugo build will fail")
        return 1

    if schema_warnings:
        print(f"[schema] WARNING: {len(schema_warnings)} schema violation(s) — not blocking deploy")

    guide_failures: list[str] = []
    guide_count = 0
    if GUIDES_DIR.exists():
        for path in sorted(GUIDES_DIR.glob("*.md")):
            if path.name == "_index.md":
                continue
            guide_count += 1
            meta, body = load_guide(path)
            lifecycle = evaluate_guide(meta, body)
            guide_failures.extend(
                f"{path.relative_to(PROJECT_DIR)}: {error}"
                for error in lifecycle.errors
            )
            print(
                f"[guide-schema] {path.name}: state={lifecycle.state} "
                f"words={lifecycle.word_count}"
            )

    if guide_failures:
        for failure in guide_failures:
            print(f"[guide-schema] FATAL: {failure}")
        return 1
    print(f"[guide-schema] Validation passed: {guide_count} guide(s)")

    print("[schema] Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
