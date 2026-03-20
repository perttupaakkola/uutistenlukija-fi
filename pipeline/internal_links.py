#!/usr/bin/env python3
"""
internal_links.py — Internal linking optimizer for uutistenlukija.fi.

Builds a scored similarity index across all articles and writes 2-3 related
article slugs to each article's `related_articles:` front matter field.
Hugo's single.html template reads this field to render the "Lue myös" section
with curated links instead of generic category-matched fallbacks.

Scoring (each criterion adds to a per-pair score):
  +2.0  Same category
  +1.5  Each shared tag (capped at +4.5)
  +1.0  Each shared title keyword (capped at +3.0)
  +0.5  Each shared body keyword (capped at +1.5)
  Temporal penalty: score × (1 - days_apart/30) — articles >30 days apart score 0

Usage:
    python3 internal_links.py                    # process all articles
    python3 internal_links.py --dry-run          # preview top matches, no writes
    python3 internal_links.py --limit 50         # first N articles
    python3 internal_links.py --offset 50        # skip first N (batching)
    python3 internal_links.py --min-score 0.3    # similarity threshold (default 0.5)
    python3 internal_links.py --stats            # show link distribution

Output: related_articles field in each article's front matter (list of 2-3 slugs)
Log:    pipeline/logs/internal_links.json
"""

import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
LOGS_DIR = Path(__file__).parent / "logs"
LINKS_LOG = LOGS_DIR / "internal_links.json"

DEFAULT_MIN_SCORE = 0.5
MAX_RELATED = 3
TEMPORAL_WINDOW_DAYS = 30  # articles outside this window are excluded

FI_STOPWORDS = {
    "ja","tai","on","ei","se","hän","he","me","te","olla","oli","että","kun","jos",
    "niin","jo","vain","myös","sekä","mutta","kuin","mikä","miksi","missä","miten",
    "kuinka","joka","jotka","uusi","uuden","uutta","uudet","uusia","koko","kaikki",
    "yksi","kaksi","kolme","neljä","viisi","suuri","pieni","iso","vuosi","vuoden",
    "vuotta","yli","alle","noin","lähes","enää","sanoo","kertoo","mukaan","mukana",
    "jälkeen","ennen","suomi","suomen","suomessa","suomalainen","voitti","hävis",
    "julkaisi","ilmoitti","kertoi","totesi","uutiset","lehti","media","uutinen",
    "myös","tämä","tässä","sitten","vielä","mutta","koska","kaikki","maan","maa",
    "oma","nyt","vain","alue","myöhemmin","eikä","vai","jotta","vaikka","siksi",
    "lähes","noin","melko","erittäin","hyvin","aika","itse","sen","nämä","ne",
    "hänen","heidän","tähän","tätä","tähän","siitä","siinä","siihen","sillä",
    "sitten","yhä","vielä","juuri","jopa","erityisesti","lisäksi","kuitenkin",
    "mukaan","mukana","mukaan","pitää","pitäisi","piti","voi","voisi","voivat",
}


# ── Front matter parser ───────────────────────────────────────────────────────

def parse_article(fpath: Path) -> dict | None:
    """Parse article front matter and extract fields needed for scoring."""
    text = fpath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm_block = text[3:end]
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

    if meta.get("draft") is True:
        return None

    # Parse date
    date_str = meta.get("date", "")
    date = None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            date = datetime.strptime(date_str[:25], fmt[:len(date_str[:25])])
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            break
        except (ValueError, TypeError):
            continue

    cats = meta.get("categories", [])
    if isinstance(cats, str):
        cats = [cats]
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    title = meta.get("title", fpath.stem)
    title_kws = extract_keywords(title)
    body_kws = extract_keywords(body[:600])

    return {
        "slug": fpath.stem,
        "path": fpath,
        "title": title,
        "categories": [c.lower() for c in cats],
        "tags": [t.lower() for t in tags],
        "date": date,
        "title_kws": title_kws,
        "body_kws": body_kws,
        "text": text,       # full file text for injection
    }


def extract_keywords(text: str, max_kws: int = 30) -> set[str]:
    """Extract meaningful content words from Finnish text."""
    words = re.sub(r"[^\wäöå\s]", " ", text.lower()).split()
    kws = set()
    for w in words:
        # Strip common Finnish inflection suffixes
        stem = re.sub(
            r"(ssa|ssä|sta|stä|lle|lta|ltä|lla|llä|ksi|han|hen|hin|hun|hyn|een|ien|jen|den|ten|nen|sen)$",
            "", w
        )
        if len(stem) >= 4 and stem not in FI_STOPWORDS and w not in FI_STOPWORDS:
            kws.add(stem)
            if len(kws) >= max_kws:
                break
    return kws


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_pair(a: dict, b: dict) -> float:
    """Compute similarity score between two articles."""
    score = 0.0

    # Temporal proximity (hard cutoff at TEMPORAL_WINDOW_DAYS)
    if a["date"] and b["date"]:
        days_apart = abs((a["date"] - b["date"]).total_seconds()) / 86400
        if days_apart > TEMPORAL_WINDOW_DAYS:
            return 0.0
        # Linear decay from 1.0 at 0 days to 0.5 at 30 days
        temporal_factor = 1.0 - (days_apart / TEMPORAL_WINDOW_DAYS) * 0.5
    else:
        temporal_factor = 0.7  # unknown date — mild penalty

    # Category match
    shared_cats = set(a["categories"]) & set(b["categories"])
    # Exclude base category tags that are too broad to be meaningful
    meaningful_cats = {c for c in shared_cats if c not in ("kotimaa", "ulkomaat")}
    if shared_cats:
        score += 2.0
    if meaningful_cats:
        score += 1.0  # extra for meaningful category match

    # Tag overlap
    shared_tags = set(a["tags"]) & set(b["tags"])
    # Exclude base/category tags
    meaningful_tags = {t for t in shared_tags if t not in (
        "kotimaa", "ulkomaat", "talous", "urheilu", "kulttuuri", "tiede", "teknologia"
    )}
    score += min(len(meaningful_tags) * 1.5, 4.5)

    # Title keyword overlap
    shared_title = a["title_kws"] & b["title_kws"]
    score += min(len(shared_title) * 1.0, 3.0)

    # Body keyword overlap
    shared_body = a["body_kws"] & b["body_kws"]
    score += min(len(shared_body) * 0.5, 1.5)

    return score * temporal_factor


def find_related(article: dict, all_articles: list, min_score: float) -> list[dict]:
    """Return top MAX_RELATED related articles above min_score."""
    scored = []
    for other in all_articles:
        if other["slug"] == article["slug"]:
            continue
        s = score_pair(article, other)
        if s >= min_score:
            scored.append((s, other))

    scored.sort(key=lambda x: -x[0])
    return [(s, a) for s, a in scored[:MAX_RELATED]]


# ── Front matter injection ────────────────────────────────────────────────────

def write_related_articles(text: str, slugs: list[str]) -> str:
    """Inject/replace related_articles field in front matter."""
    # Remove existing related_articles block
    cleaned = re.sub(
        r'^related_articles:.*?\n(?:  - .*\n)*',
        '',
        text,
        flags=re.MULTILINE
    )

    block = "related_articles:\n" + "".join(f"  - {s}\n" for s in slugs)

    # Insert after tags block, falling back to draft: or before closing ---
    for pattern in [r'^(tags:(?:.*\n)(?:  - .*\n)*)', r'^(draft:.*\n)', r'^(categories:(?:.*\n)(?:  - .*\n)*)']:
        m = re.search(pattern, cleaned, re.MULTILINE)
        if m:
            return cleaned[:m.end()] + block + cleaned[m.end():]

    end = cleaned.find("\n---", 3)
    if end != -1:
        return cleaned[:end] + "\n" + block.rstrip() + cleaned[end:]
    return cleaned


# ── Main ──────────────────────────────────────────────────────────────────────

def run(
    dry_run: bool = False,
    limit: int | None = None,
    offset: int = 0,
    min_score: float = DEFAULT_MIN_SCORE,
) -> dict:
    # Load all articles
    all_files = sorted(CONTENT_DIR.glob("*.md"))
    print(f"🔗 Loading {len(all_files)} articles...", flush=True)

    all_articles = []
    for f in all_files:
        art = parse_article(f)
        if art:
            all_articles.append(art)

    print(f"   Loaded {len(all_articles)} publishable articles")

    # Determine target batch
    targets = all_articles[offset:]
    if limit:
        targets = targets[:limit]

    total = len(targets)
    print(f"🔗 Internal links — {total} articles to process (min_score={min_score}, dry_run={dry_run})")

    linked = 0
    no_match = 0
    log_entries = []

    for i, article in enumerate(targets):
        if i % 100 == 0 and i > 0:
            print(f"  … {i}/{total}", flush=True)

        matches = find_related(article, all_articles, min_score)
        slugs = [a["slug"] for _, a in matches]

        entry = {
            "slug": article["slug"],
            "title": article["title"][:60],
            "related": [
                {"slug": a["slug"], "score": round(s, 2), "title": a["title"][:50]}
                for s, a in matches
            ],
        }

        if dry_run:
            if matches:
                print(f"\n  [{article['categories'][0] if article['categories'] else '?':10s}] {article['title'][:50]}")
                for s, rel in matches:
                    print(f"    {s:.2f}  {rel['title'][:60]}")
            else:
                print(f"  [no match] {article['title'][:60]}")
        else:
            if slugs:
                new_text = write_related_articles(article["text"], slugs)
                article["path"].write_text(new_text, encoding="utf-8")
                linked += 1
            else:
                no_match += 1

        log_entries.append(entry)

    if not dry_run:
        LOGS_DIR.mkdir(exist_ok=True)
        existing = []
        if LINKS_LOG.exists():
            try:
                existing = json.loads(LINKS_LOG.read_text())
            except json.JSONDecodeError:
                pass
        # Keep a run record
        run_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": total,
            "linked": linked,
            "no_match": no_match,
            "min_score": min_score,
            "entries": log_entries[:200],  # cap for log size
        }
        existing.append(run_record)
        LINKS_LOG.write_text(json.dumps(existing[-10:], indent=2))  # keep 10 runs
        print(f"\n✅ Done: {linked} linked, {no_match} no matches / {total} total")

    return {"total": total, "linked": linked, "no_match": no_match}


def show_stats():
    """Show distribution of related_articles across the corpus."""
    from collections import Counter
    counts = Counter()
    for f in sorted(CONTENT_DIR.glob("*.md")):
        text = f.read_text()
        m = re.search(r'^related_articles:', text, re.MULTILINE)
        slugs = re.findall(r'^  - (.+)$', text[m.start():m.start()+200], re.MULTILINE) if m else []
        counts[len(slugs)] += 1

    total = sum(counts.values())
    with_links = total - counts.get(0, 0)
    print(f"Articles: {total} total, {with_links} with related_articles")
    for n, c in sorted(counts.items()):
        print(f"  {n} related: {c} articles")


def main():
    args = sys.argv[1:]

    if "--stats" in args:
        show_stats()
        return

    dry_run = "--dry-run" in args
    limit = None
    offset = 0
    min_score = DEFAULT_MIN_SCORE

    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    if "--offset" in args:
        idx = args.index("--offset")
        if idx + 1 < len(args):
            offset = int(args[idx + 1])

    if "--min-score" in args:
        idx = args.index("--min-score")
        if idx + 1 < len(args):
            min_score = float(args[idx + 1])

    run(dry_run=dry_run, limit=limit, offset=offset, min_score=min_score)


if __name__ == "__main__":
    main()
