#!/usr/bin/env python3
"""
backfill_thin_articles.py — Expand thin articles to 280+ words.

Scans content/posts/ for articles under a word-count threshold,
calls the OpenAI expansion API (same logic as rewriter.py Pass 3),
writes expanded content back to the markdown file, and commits in batches.

Usage:
    # Dry-run: see what would be expanded (no writes)
    python3 backfill_thin_articles.py --dry-run

    # Dry-run on only the worst offenders (<50 words)
    python3 backfill_thin_articles.py --dry-run --max-words 50

    # Expand all articles under 200 words (default), batch of 20, then commit
    python3 backfill_thin_articles.py --max-words 200 --batch 20

    # Expand only the <50w articles first
    python3 backfill_thin_articles.py --max-words 50 --batch 20

    # Resume from a specific article (skip already-done ones)
    python3 backfill_thin_articles.py --max-words 200 --batch 20 --resume

Environment:
    OPENAI_API_KEY — required (loaded from pipeline/.env if not set)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_DIR  = SCRIPT_DIR.parent
CONTENT_DIR  = PROJECT_DIR / "content" / "posts"
LOG_DIR      = SCRIPT_DIR / "logs"
PROGRESS_FILE = LOG_DIR / "backfill-progress.json"
ENV_FILE     = SCRIPT_DIR / ".env"

TARGET_WORDS  = 350   # minimum target after expansion
MIN_IMPROVED  = 50    # only save if we gained at least this many words

# ── Env loader ────────────────────────────────────────────────────────────────

def load_env():
    if not os.environ.get("OPENAI_API_KEY") and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


# ── Markdown parsing ───────────────────────────────────────────────────────────

def parse_article(path: Path) -> tuple[dict, str, str]:
    """Returns (frontmatter_dict, frontmatter_raw, body)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}, "", text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text[3:], ""
    fm_raw  = text[3:end]
    body    = text[end + 4:]
    fm = {}
    for line in fm_raw.splitlines():
        m = re.match(r'^(\w+):\s*(.+)$', line.strip())
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm, fm_raw, body


def word_count(text: str) -> int:
    clean = re.sub(r'[#*`\[\]()>]', ' ', text)
    return len(clean.split())


def write_back(path: Path, fm_raw: str, new_body: str):
    """Write frontmatter + expanded body back to file."""
    content = f"---\n{fm_raw}\n---\n{new_body}"
    path.write_text(content, encoding="utf-8")


# ── LLM expansion ─────────────────────────────────────────────────────────────

EXPANSION_SYSTEM = """Olet kokenut suomalainen uutistoimittaja. Sinulle annetaan lyhyt uutisartikkeli joka on laajennettava.

TEHTÄVÄ: Laajenna artikkeli VÄHINTÄÄN 350 sanaan (tavoite 350-400 sanaa).

SALLITUT LAAJENNUSTAVAT — käytä vain näitä:
- Selitä miksi tämä uutinen on tärkeä lukijalle (vaikutus arkeen, laajempi merkitys)
- Kuvaa tapahtuman maantieteellinen tai historiallinen konteksti yleistiedon pohjalta
- Avaa käsitteitä tai ilmiöitä joita lukija ei välttämättä tunne
- Laajenna alkuperäisessä lähdetekstissä mainittuja yksityiskohtia
- Lisää kysymyksiä joita tapaus herättää — ilman keksittyjä vastauksia

KIELLETTYÄ laajennuksessa:
- Tilastot, prosenttiluvut tai numerot joita alkuperäinen teksti ei mainitse
- Lainaukset tai kommentit joita alkuperäinen teksti ei mainitse
- Nimetyt henkilöt tai organisaatiot joita alkuperäinen teksti ei mainitse
- Tapahtumat joita alkuperäinen teksti ei mainitse

Palauta VAIN laajennettu artikkeli pelkkänä tekstinä. Ei JSON, ei koodiblokki. Käytä ## H2-väliotsikoita kun artikkeli on 300+ sanaa."""


def expand_article(title: str, body: str, current_words: int) -> str | None:
    """Call OpenAI to expand a thin article body. Returns expanded text or None on error."""
    try:
        from openai import OpenAI
    except ImportError:
        print("[expand] openai package not installed", file=sys.stderr)
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[expand] OPENAI_API_KEY not set", file=sys.stderr)
        return None

    client = OpenAI(api_key=api_key)
    prompt = (
        f"Tämä artikkeli on liian lyhyt ({current_words} sanaa). "
        f"Laajenna se VÄHINTÄÄN 350 sanaan.\n\n"
        f"Otsikko: {title}\n\n"
        f"Artikkeli:\n\n{body.strip()}\n\n"
        f"Lisää taustaa, kontekstia ja seurauksia. ÄLÄ lyhennä mitään. "
        f"Palauta VAIN laajennettu teksti. Ei JSON, ei muuta."
    )

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": EXPANSION_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.4,
                max_tokens=1200,
                timeout=60,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[expand] Attempt {attempt+1} failed: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    return None


# ── Progress tracking ─────────────────────────────────────────────────────────

def load_progress() -> set:
    if PROGRESS_FILE.exists():
        data = json.loads(PROGRESS_FILE.read_text())
        return set(data.get("done", []))
    return set()


def save_progress(done: set, stats: dict):
    LOG_DIR.mkdir(exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "done_count": len(done),
        "done": sorted(done),
        "stats": stats,
    }, indent=2, ensure_ascii=False))


# ── Git commit ────────────────────────────────────────────────────────────────

def git_commit_batch(batch_num: int, count: int):
    os.chdir(PROJECT_DIR)
    subprocess.run(["git", "add", "content/posts/"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--stat"], capture_output=True, text=True)
    if "content/posts" not in result.stdout:
        print(f"[git] No changes to commit for batch {batch_num}")
        return
    msg = f"backfill: expand {count} thin articles to 350+ words (batch {batch_num})"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    print(f"[git] Committed batch {batch_num}: {count} articles")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Expand thin articles to 280+ words")
    parser.add_argument("--dry-run",   action="store_true", help="Report only, no writes")
    parser.add_argument("--max-words", type=int, default=200,
                        help="Expand articles with fewer than this many words (default: 200)")
    parser.add_argument("--batch",     type=int, default=20,
                        help="Commit after every N expansions (default: 20)")
    parser.add_argument("--resume",    action="store_true",
                        help="Skip slugs already in backfill-progress.json")
    parser.add_argument("--limit",     type=int, default=None,
                        help="Max articles to process in this run")
    parser.add_argument("--push",      action="store_true",
                        help="Push after each commit (requires git push access)")
    args = parser.parse_args()

    load_env()
    LOG_DIR.mkdir(exist_ok=True)

    done_slugs = load_progress() if args.resume else set()

    # ── Scan ──────────────────────────────────────────────────────────────────
    candidates = []
    all_paths = sorted(CONTENT_DIR.glob("*.md"))
    for path in all_paths:
        slug = path.stem
        if slug in done_slugs:
            continue
        fm, fm_raw, body = parse_article(path)
        if not fm:
            continue
        wc = word_count(body)
        if wc < args.max_words:
            candidates.append({
                "path": path,
                "slug": slug,
                "title": fm.get("title", slug),
                "words": wc,
                "fm_raw": fm_raw,
                "body": body,
            })

    candidates.sort(key=lambda x: x["words"])  # worst first

    if args.limit:
        candidates = candidates[:args.limit]

    total = len(candidates)
    print(f"\n{'='*60}")
    print(f"BACKFILL: {total} articles under {args.max_words} words")
    if args.dry_run:
        print("MODE: DRY RUN (no writes)")
    print(f"{'='*60}\n")

    if args.dry_run:
        # Summary table
        buckets = {"<50": [], "50-99": [], "100-149": [], "150-199": []}
        for c in candidates:
            w = c["words"]
            if w < 50:   buckets["<50"].append(c)
            elif w < 100: buckets["50-99"].append(c)
            elif w < 150: buckets["100-149"].append(c)
            else:         buckets["150-199"].append(c)

        for label, items in buckets.items():
            if not items:
                continue
            print(f"  {label} words: {len(items)} articles")
            for c in items[:5]:
                print(f"    {c['words']:3d}w  {c['title'][:65]}")
            if len(items) > 5:
                print(f"    ... and {len(items)-5} more")
            print()

        print(f"Would expand {total} articles → target 350+ words each")
        print(f"Estimated cost: ~{total * 0.0001:.3f} USD @ gpt-4o-mini rates")
        print(f"Estimated time: ~{total * 3 // 60}m {total * 3 % 60}s at 3s/article\n")
        return

    # ── Expansion loop ────────────────────────────────────────────────────────
    stats = {"attempted": 0, "expanded": 0, "skipped": 0, "failed": 0,
             "total_words_before": 0, "total_words_after": 0}
    batch_expanded = []
    batch_num = 1

    for i, c in enumerate(candidates, 1):
        slug  = c["slug"]
        title = c["title"]
        wc    = c["words"]
        path  = c["path"]
        body  = c["body"]

        print(f"[{i:3d}/{total}] {wc:3d}w → {title[:55]}")
        stats["attempted"] += 1
        stats["total_words_before"] += wc

        expanded_text = expand_article(title, body, wc)
        if not expanded_text:
            print(f"         ❌ expansion failed")
            stats["failed"] += 1
            stats["total_words_after"] += wc
            continue

        new_wc = word_count(expanded_text)

        if new_wc < wc + MIN_IMPROVED:
            print(f"         ⚠ barely improved ({wc}w → {new_wc}w) — skipping save")
            stats["skipped"] += 1
            stats["total_words_after"] += wc
            continue

        # Write back
        write_back(path, c["fm_raw"], "\n\n" + expanded_text + "\n")
        print(f"         ✅ {wc}w → {new_wc}w  (+{new_wc-wc}w)")

        stats["expanded"] += 1
        stats["total_words_after"] += new_wc
        done_slugs.add(slug)
        batch_expanded.append(slug)

        save_progress(done_slugs, stats)

        # Batch commit
        if len(batch_expanded) >= args.batch:
            git_commit_batch(batch_num, len(batch_expanded))
            if args.push:
                subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_DIR, check=False)
            batch_num += 1
            batch_expanded = []

        # Rate limit: 1s between calls
        time.sleep(1)

    # Final commit for any remaining
    if batch_expanded:
        git_commit_batch(batch_num, len(batch_expanded))
        if args.push:
            subprocess.run(["git", "push", "origin", "main"], cwd=PROJECT_DIR, check=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    avg_before = stats["total_words_before"] / max(stats["attempted"], 1)
    avg_after  = stats["total_words_after"]  / max(stats["attempted"], 1)

    print(f"\n{'='*60}")
    print(f"BACKFILL COMPLETE")
    print(f"  Attempted:  {stats['attempted']}")
    print(f"  Expanded:   {stats['expanded']}")
    print(f"  Skipped:    {stats['skipped']}  (improvement too small)")
    print(f"  Failed:     {stats['failed']}")
    print(f"  Avg words:  {avg_before:.0f}w → {avg_after:.0f}w")
    print(f"  Progress:   {PROGRESS_FILE}")
    print(f"{'='*60}\n")

    save_progress(done_slugs, stats)


if __name__ == "__main__":
    main()
