#!/usr/bin/env python3
"""Generate a daily kooste (digest) frontmatter file for /paivan-kooste/.

Usage:
  python3 scripts/generate_kooste.py                # today
  python3 scripts/generate_kooste.py --date 2026-03-26
  python3 scripts/generate_kooste.py --dry-run      # preview only
  python3 scripts/generate_kooste.py --force        # overwrite existing
"""
import argparse, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
POSTS_DIR = PROJECT_DIR / "content" / "posts"
KOOSTE_DIR = PROJECT_DIR / "content" / "paivan-kooste"

SECTIONS = [
    ("kotimaa", "kotimaa"),
    ("ulkomaat", "ulkomaat"),
    ("talous", "talous"),
    ("teknologia", "teknologia"),
]
MIN_ARTICLES_DEFAULT = 3

FI_MONTHS = {
    1: "tammikuuta", 2: "helmikuuta", 3: "maaliskuuta",
    4: "huhtikuuta", 5: "toukokuuta", 6: "kesäkuuta",
    7: "heinäkuuta", 8: "elokuuta", 9: "syyskuuta",
    10: "lokakuuta", 11: "marraskuuta", 12: "joulukuuta"
}
FI_WEEKDAYS = {
    0: "maanantaina", 1: "tiistaina", 2: "keskiviikkona",
    3: "torstaina", 4: "perjantaina", 5: "lauantaina", 6: "sunnuntaina"
}


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    lines = text[3:end].splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith((" ", "\t")) or ":" not in line:
            index += 1
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip("\"'")
        if not v:
            items = []
            index += 1
            while index < len(lines) and lines[index].startswith((" ", "\t")):
                item = re.match(r"^\s*-\s+(.+?)\s*$", lines[index])
                if item:
                    items.append(item.group(1).strip().strip("\"'"))
                index += 1
            fm[k] = items if items else ""
            continue
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
        else:
            fm[k] = v
        index += 1
    return fm


def parse_article_date(raw):
    try:
        raw = raw.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        elif not re.search(r"[+-]\d{2}:\d{2}$", raw):
            raw += "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def day_window(date):
    s = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)
    return int(s.timestamp()), int((s + timedelta(days=1)).timestamp())


def fi_date_str(d):
    return f"{d.day}.{d.month}.{d.year}"


def fi_long_date(d):
    return f"{FI_WEEKDAYS[d.weekday()]} {d.day}. {FI_MONTHS[d.month]}"


def build_description(date, active):
    labels = [s for _, s in SECTIONS if s in active]
    if not labels:
        return f"Päivän kooste {fi_long_date(date)}."
    if len(labels) == 1:
        sec = labels[0]
    elif len(labels) == 2:
        sec = f"{labels[0]} ja {labels[1]}"
    else:
        sec = ", ".join(labels[:-1]) + f" ja {labels[-1]}"
    return (
        f"Tärkeimmät uutiset {fi_long_date(date)}: "
        f"{sec.capitalize()}uutiset koottuna yhteen."
    )


def scan_posts(date, min_articles):
    if not POSTS_DIR.exists():
        print(f"ERROR: {POSTS_DIR} not found", file=sys.stderr)
        return [], 0
    s, e = day_window(date)
    date_re = re.compile(
        r'^date\s*[:=]\s*["\']?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'
        r'(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)',
        re.MULTILINE
    )
    counts = {slug: 0 for slug, _ in SECTIONS}
    total = 0
    for p in POSTS_DIR.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            m = date_re.search(text)
            if not m:
                continue
            dt = parse_article_date(m.group(1))
            if dt is None:
                continue
            ts = int(dt.timestamp())
            if ts < s or ts >= e:
                continue
            fm = parse_frontmatter(text)
            if fm.get("draft", "false").lower() == "true":
                continue
            total += 1
            cats = fm.get("categories", [])
            if isinstance(cats, str):
                cats = [cats]
            for c in cats:
                slug = c.lower().strip()
                if slug in counts:
                    counts[slug] += 1
        except Exception as ex:
            print(f"Warning: {p.name}: {ex}", file=sys.stderr)
    active = [slug for slug, _ in SECTIONS if counts.get(slug, 0) > 0]
    return active, total


def write_kooste(date, active, total, dry_run, force):
    date_iso = date.strftime("%Y-%m-%d")
    out = KOOSTE_DIR / f"{date_iso}.md"
    secs = "\n".join(f" - {s}" for s in active)
    content = (
        f'---\ntitle: "Päivän kooste — {fi_date_str(date)}"\n'
        f'date: {date_iso}T00:00:00Z\n'
        f'description: "{build_description(date, active)}"\n'
        f'sections:\n{secs}\n---\n'
    )
    print(f"Date: {date_iso} | Articles: {total} | Sections: {','.join(active) or '(none)'}")
    print(content.strip())
    if dry_run:
        print("DRY RUN — nothing written.")
        return 0
    if out.exists() and not force:
        print(f"SKIP — {out.name} exists (--force to overwrite)")
        return 0
    KOOSTE_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"✅ Written: {out}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Generate daily kooste frontmatter.")
    ap.add_argument("--date", default="", help="Target date YYYY-MM-DD (default: today)")
    ap.add_argument("--dry-run", action="store_true", help="Preview only, don't write")
    ap.add_argument("--force", action="store_true", help="Overwrite existing file")
    ap.add_argument("--min-articles", type=int, default=MIN_ARTICLES_DEFAULT,
                    help="Minimum articles required (default: 3)")
    args = ap.parse_args()
    if args.date:
        try:
            target = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: bad date '{args.date}'", file=sys.stderr)
            return 1
    else:
        target = datetime.now(timezone.utc)
    active, total = scan_posts(target, args.min_articles)
    if total < args.min_articles:
        print(f"Only {total} articles — min {args.min_articles}. Skipping.")
        return 0
    return write_kooste(target, active, total, args.dry_run, args.force)


if __name__ == "__main__":
    sys.exit(main())
