#!/usr/bin/env python3
"""
pre_publish_check.py — Pre-deploy gate for uutistenlukija.fi

Validates articles that are staged for commit (or passed as explicit paths).
Auto-fixes what it can. Un-stages articles that fail hard checks.

Hard blocks (article un-staged, logged to rejected.json):
  - No image (hero image missing)
  - Thin content (< 50 words)

Auto-fixed (no block):
  - Missing or empty description → filled from first 155 chars of body

Exit codes:
  0  All articles passed (or were auto-fixed)
  1  One or more articles were rejected (un-staged, logged)

Usage:
    python3 pre_publish_check.py                   # check git-staged files
    python3 pre_publish_check.py path/to/art.md    # explicit paths
    python3 pre_publish_check.py --dry-run         # report only, don't modify/unstage
    python3 pre_publish_check.py --all             # check entire content/posts/ dir
    python3 pre_publish_check.py --fix-only        # fix descriptions without blocking
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PIPELINE_DIR = Path(__file__).parent
PROJECT_DIR = PIPELINE_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content" / "posts"
LOGS_DIR = PIPELINE_DIR / "logs"
REJECTED_LOG = LOGS_DIR / "rejected.json"

MIN_WORDS = 50
MAX_DESC_LEN = 155

# ── Front matter helpers (shared logic with validate_articles.py) ─────────────

def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].strip()
    meta: dict = {}
    current_list_key = None
    for line in fm_block.splitlines():
        if re.match(r"^\s{2,}- ", line):
            if current_list_key:
                item = re.sub(r"^\s+-\s+", "", line).strip().strip('"\'')
                meta.setdefault(current_list_key, []).append(item)
            continue
        m = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if m:
            current_list_key = None
            key, val = m.group(1), m.group(2).strip().strip('"\'')
            if val == "":
                current_list_key = key
                meta[key] = []
            elif val.lower() == "true":
                meta[key] = True
            elif val.lower() == "false":
                meta[key] = False
            else:
                meta[key] = val
    return meta, body


def count_words(text: str) -> int:
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[#*_~>|]', ' ', text)
    return len(text.split())


def extract_description(body: str, max_len: int = MAX_DESC_LEN) -> str:
    text = re.sub(r'^#+\s+.*$', '', body, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_`#>]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    for sep in ('. ', '! ', '? ', ', '):
        pos = truncated.rfind(sep)
        if pos > max_len // 2:
            return truncated[:pos + 1].strip()
    return truncated.rsplit(' ', 1)[0].strip()


def inject_description(text: str, desc: str) -> str:
    """Write description into front matter, inserting after title line."""
    escaped = desc.replace('"', '\\"')
    new_line = f'description: "{escaped}"'
    # Replace existing empty description
    replaced = re.sub(
        r'^description:\s*["\']?["\']?\s*$',
        new_line,
        text,
        flags=re.MULTILINE,
    )
    if replaced != text:
        return replaced
    # Replace existing description with value
    replaced = re.sub(
        r'^description:.*$',
        new_line,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if replaced != text:
        return replaced
    # Insert after title
    return re.sub(
        r'^(title:.*)$',
        r'\1\n' + new_line,
        text,
        count=1,
        flags=re.MULTILINE,
    )


# ── Git helpers ───────────────────────────────────────────────────────────────

def get_staged_posts() -> list[Path]:
    """Return list of staged content/posts/*.md files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, cwd=PROJECT_DIR
        )
        paths = []
        for line in result.stdout.splitlines():
            if line.startswith("content/posts/") and line.endswith(".md"):
                paths.append(PROJECT_DIR / line)
        return paths
    except Exception as e:
        print(f"[warn] git diff failed: {e}", file=sys.stderr)
        return []


def unstage_file(path: Path) -> bool:
    """Remove file from git staging area (git restore --staged)."""
    try:
        subprocess.run(
            ["git", "restore", "--staged", str(path.relative_to(PROJECT_DIR))],
            check=True, cwd=PROJECT_DIR, capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[warn] Could not unstage {path.name}: {e}", file=sys.stderr)
        return False


def restage_file(path: Path) -> bool:
    """Re-add file after in-place fix."""
    try:
        subprocess.run(
            ["git", "add", str(path.relative_to(PROJECT_DIR))],
            check=True, cwd=PROJECT_DIR, capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[warn] Could not restage {path.name}: {e}", file=sys.stderr)
        return False


# ── Validation ────────────────────────────────────────────────────────────────

def check_article(
    path: Path,
    dry_run: bool = False,
    fix_only: bool = False,
) -> dict:
    """
    Validate a single article. Returns a result dict:
      status: "ok" | "fixed" | "rejected"
      fixes: list of applied fixes
      blocks: list of unfixable issues
    """
    text = path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)

    result = {
        "file": path.name,
        "slug": path.stem,
        "title": meta.get("title", ""),
        "status": "ok",
        "fixes": [],
        "blocks": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    draft = meta.get("draft", False)
    if draft is True:
        result["status"] = "skipped"
        result["reason"] = "draft"
        return result

    modified = False

    # ── Auto-fix: missing description ────────────────────────────────────────
    desc = meta.get("description", "")
    if not desc or not desc.strip():
        new_desc = extract_description(body)
        if new_desc:
            if not dry_run:
                new_text = inject_description(text, new_desc)
                if new_text != text:
                    path.write_text(new_text, encoding="utf-8")
                    modified = True
            result["fixes"].append(f"description auto-filled ({len(new_desc)} chars)")
            result["status"] = "fixed"
        else:
            result["fixes"].append("description: body empty, could not auto-fill")

    # ── Hard check: missing image ─────────────────────────────────────────────
    image = meta.get("image", "")
    if not image or not image.strip():
        result["blocks"].append("no_image: hero image missing")

    # ── Hard check: thin content ──────────────────────────────────────────────
    word_count = count_words(body)
    if word_count < MIN_WORDS:
        result["blocks"].append(f"thin_content: {word_count} words (min {MIN_WORDS})")

    # ── Final verdict ─────────────────────────────────────────────────────────
    if result["blocks"] and not fix_only:
        result["status"] = "rejected"
    elif modified:
        result["status"] = "fixed"

    if modified and not dry_run:
        # Re-stage the fixed file
        restage_file(path)

    return result


# ── Logging ───────────────────────────────────────────────────────────────────

def log_rejections(results: list[dict]) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    history = []
    if REJECTED_LOG.exists():
        try:
            history = json.loads(REJECTED_LOG.read_text())
        except json.JSONDecodeError:
            pass

    run_entry = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "rejected": [r for r in results if r["status"] == "rejected"],
        "fixed": [r for r in results if r["status"] == "fixed"],
        "ok": sum(1 for r in results if r["status"] == "ok"),
    }
    history.append(run_entry)
    history = history[-100:]  # keep last 100 runs
    REJECTED_LOG.write_text(json.dumps(history, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    fix_only = "--fix-only" in args
    check_all = "--all" in args

    # Explicit file paths
    explicit_paths = [Path(a) for a in args if not a.startswith("--")]

    # Determine files to check
    if explicit_paths:
        files = explicit_paths
    elif check_all:
        files = sorted(CONTENT_DIR.glob("*.md"))
    else:
        files = get_staged_posts()

    if not files:
        print("[pre-publish] No staged articles to check.")
        sys.exit(0)

    print(f"[pre-publish] Checking {len(files)} article(s)...", flush=True)

    results = []
    for path in files:
        if not path.exists():
            print(f"  [skip] {path.name} — not found", flush=True)
            continue
        r = check_article(path, dry_run=dry_run, fix_only=fix_only)
        results.append(r)

        status_icon = {"ok": "✅", "fixed": "🔧", "rejected": "❌", "skipped": "⏭"}.get(r["status"], "?")
        detail = ""
        if r["fixes"]:
            detail += f" | fixed: {'; '.join(r['fixes'])}"
        if r["blocks"]:
            detail += f" | BLOCKED: {'; '.join(r['blocks'])}"
        print(f"  {status_icon} {r['file']}{detail}", flush=True)

    # Un-stage rejected articles (unless dry-run or fix-only)
    rejected = [r for r in results if r["status"] == "rejected"]
    if rejected and not dry_run and not fix_only:
        for r in rejected:
            fpath = CONTENT_DIR / r["file"]
            if unstage_file(fpath):
                print(f"  [unstaged] {r['file']}", flush=True)

    # Summary
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_fixed = sum(1 for r in results if r["status"] == "fixed")
    n_rejected = len(rejected)
    n_skipped = sum(1 for r in results if r["status"] == "skipped")

    print(
        f"\n[pre-publish] ✅ {n_ok} ok  🔧 {n_fixed} fixed  ❌ {n_rejected} rejected  ⏭ {n_skipped} skipped",
        flush=True,
    )

    if not dry_run:
        log_rejections(results)

    if n_rejected > 0:
        print(
            f"[pre-publish] {n_rejected} article(s) rejected and un-staged. "
            f"Remaining {n_ok + n_fixed} article(s) will proceed to publish.",
            flush=True,
        )
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
