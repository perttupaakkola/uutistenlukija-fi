#!/usr/bin/env python3
"""
auto_tag.py — Keyword-based auto-tagger for uutistenlukija.fi articles.

Generates 3-5 Finnish tags per article by matching title + body keywords
against a curated tag taxonomy. No LLM calls — pure pattern matching.

Usage:
    python3 auto_tag.py                    # tag all untagged articles
    python3 auto_tag.py --dry-run          # preview without writing
    python3 auto_tag.py --limit 50         # first N untagged articles
    python3 auto_tag.py --offset 50        # skip first N (for batching)
    python3 auto_tag.py --overwrite        # re-tag already-tagged articles
    python3 auto_tag.py --stats            # show tag distribution and exit

Tags are written to `tags:` front matter field as a YAML list.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CONTENT_DIR = Path(__file__).parent.parent / "content" / "posts"
LOGS_DIR = Path(__file__).parent / "logs"
TAG_LOG = LOGS_DIR / "auto_tag.json"

MIN_TAGS = 3
MAX_TAGS = 5

# ── Tag taxonomy ──────────────────────────────────────────────────────────────
# Format: "tag": [match_patterns...]
# Patterns are checked against lowercased title + first 400 chars of body.
# First matching pattern wins (order matters within each tag entry).
# Tags are sorted by specificity score (more pattern matches = higher score).

TAG_RULES: dict[str, list[str]] = {

    # ── Politics / Government ─────────────────────────────────────────────────
    "hallitus":     ["hallitus", "hallituksen", "hallitukselle", "hallitusta", "pääministeri", "orpo"],
    "eduskunta":    ["eduskunta", "kansanedustaja", "eduskunnan", "täysistunto", "kyselytunti"],
    "politiikka":   ["politiikka", "poliittinen", "puolue", "vaalit", "vaali", "äänestys", "oppositio"],
    "kokoomus":     ["kokoomus", "kokoomuksen", "kokoomuslai"],
    "sdp":          [r"\bsdp\b", "sosiaalidemokraatti", "marinin"],
    "perussuomalaiset": ["perussuomalai", "purra"],
    "budjetti":     ["budjetti", "talousarvio", "menot", "tulot", "julkinen talous", "valtiontalous"],
    "verotus":      ["verotus", "vero", "verot", "veropohja", "verotuotto", "verohallinto", "veropetos"],
    "leikkaukset":  ["leikkaus", "säästö", "säästöt", "karsinta", "supistus"],

    # ── Economy / Finance ─────────────────────────────────────────────────────
    "talous":       ["talous", "talouskasvu", "bkt", "taloudellinen", "talousennuste"],
    "korot":        ["korko", "korot", "ohjauskorko", "euribor", "korkojen"],
    "pörssi":       ["pörssi", "osake", "osakkeet", "osakekurss", "helsinki nasdaq", "porssissa"],
    "energia":      ["energia", "sähkö", "sähköhinta", "pörssisähkö", "energiakriisi", "öljy", "kaasu"],
    "inflaatio":    ["inflaatio", "hintataso", "hintojen nousu", "ostovoima"],
    "yritys":       ["yritys", "yhtiö", "liiketoiminta", "tulos", "liikevaihto"],
    "pankki":       ["pankki", "pankit", "fed", "ekp", "europankki", "keskuspankki"],
    "öljy":         ["öljy", "öljyn hinta", "raakaöljy", "öljyntuotanto"],
    "asuminen":     ["asunto", "asuminen", "kiinteistö", "asuntomarkkina", "vuokra"],

    # ── Defence / Security / Foreign policy ───────────────────────────────────
    "nato":         [r"\bnato\b", "naton"],
    "puolustus":    ["puolustus", "puolustusvoimat", "armeija", "sotilaat", "asevoimat"],
    "turvallisuus": ["turvallisuus", "kansallinen turvallisuus", "tiedustelupalvelu"],
    "sota":         [r"\bsota\b", "sotaan", "sodan", "aseellinen konflikti", "taistelut"],
    "ukraina":      ["ukraina", "ukrainan"],
    "venäjä":       ["venäjä", "venäjän", "venäläinen", "moskova", "kreml", "putin"],
    "israel":       ["israel", "israelin", "idf"],
    "iran":         [r"\biran\b", "iranin", "iranilais"],
    "yhdysvallat":  ["yhdysvallat", "yhdysvaltojen", "trump", "usa", "washington"],
    "kiina":        [r"\bkiina\b", "kiinan", "kiinalai", "peking"],
    "eu":           [r"\beu\b", "euroopan unioni", "euroopan parlamentti", "brysseli"],
    "pakolaiset":   ["pakolais", "turvapaikanhakija", "maahanmuutto"],

    # ── Crime / Courts / Justice ──────────────────────────────────────────────
    "poliisi":      ["poliisi", "poliisit", "rikostutkinta", "epäilty", "rikosepäily"],
    "rikos":        ["rikos", "rikokset", "rikostuomio", "rangaistus", "tuomio", "tuomittiin"],
    "oikeus":       ["tuomioistuin", "oikeus", "käräjäoikeus", "hovioikeus", "syyttäjä", "syyte"],
    "murha":        ["murha", "murhasta", "tappo", "surma", "henkirikos"],

    # ── Health / Medicine ─────────────────────────────────────────────────────
    "terveys":      ["terveys", "terveyden", "sairaala", "terveydenhuolto", "lääkäri"],
    "lääketiede":   ["lääke", "lääkitys", "lääkäri", "hoito", "diagnoosi", "potilas"],
    "mielenterveys": ["mielenterveys", "masennus", "ahdistus", "uupumus", "burnout"],
    "rokote":       ["rokote", "rokotus", "influenssa", "virus", "pandemia"],

    # ── Education ─────────────────────────────────────────────────────────────
    "koulutus":     ["koulutus", "koulu", "opetus", "oppilaitos", "yliopisto", "ammattikoulu"],
    "opiskelijat":  ["opiskelija", "opiskelijat", "opinnot", "tutkinto"],

    # ── Environment / Nature ──────────────────────────────────────────────────
    "ilmasto":      ["ilmasto", "ilmastonmuutos", "hiilidioksidi", "päästöt", "ilmastopolitiikka"],
    "luonto":       ["luonto", "luonnonsuojelu", "ympäristö", "biodiversiteetti", "metsä", "eläimet"],
    "sää":          ["sää", "lämpötila", "lumi", "pakkanen", "helteet", "sääennuste"],

    # ── Sports ────────────────────────────────────────────────────────────────
    "jalkapallo":   ["jalkapallo", "jalkapallon", "huuhkajat", "veikkausliiga", "championsl"],
    "jääkiekko":    ["jääkiekko", "sm-liiga", "nhl", "kiekko", "hockey"],
    "urheilu":      ["urheilu", "urheilija", "kilpailu", "mestaruus", "olympia"],
    "formula":      ["formula", "f1", "gp", "grand prix"],
    "tennis":       ["tennis", "wimbledon", "atp", "wta"],
    "hiihto":       ["hiihto", "hiihtäjä", "maastohiihto", "laskettelu", "mäkihyppy"],
    "yleisurheilu": ["yleisurheilu", "juoksu", "hyppy", "heitto", "mm-hallit"],
    "snooker":      ["snooker", "sullivan"],
    "golf":         [r"\bgolf\b", "golfin"],

    # ── Technology ────────────────────────────────────────────────────────────
    "tekoäly":      ["tekoäly", "tekoälyn", "tekoälyä", r"\bai\b", "kielimalli", "gpt", "llm"],
    "teknologia":   ["teknologia", "digitaalinen", "ohjelmisto", "sovellus", "startup"],
    "kyberturvallisuus": ["kyber", "tietoturva", "hakkeri", "tietomurto", "haittaohjelma"],
    "nokia":        ["nokia"],
    "nvidia":       ["nvidia"],

    # ── Media / Culture ───────────────────────────────────────────────────────
    "kulttuuri":    ["kulttuuri", "taide", "näyttely", "museo", "teatteri"],
    "musiikki":     ["musiikki", "konsertti", "albumi", "bändi", "artisti", "laulu"],
    "elokuva":      ["elokuva", "elokuvan", "leffa", "oscar", "cannes", "leffat"],
    "kirjallisuus": ["kirja", "romaani", "kirjailija", "teos", "kirjallisuus"],
    "viihde":       ["viihde", "tv-ohjelma", "sarjan", "netflix", "streaming"],

    # ── Social affairs ────────────────────────────────────────────────────────
    "työelämä":     ["työelämä", "työssä", "työnantaja", "palkka", "palkkaus", "rekrytointi"],
    "työttömyys":   ["työttömyys", "työtön", "työttömät", "työtöntä", "työttömyysaste"],
    "eläke":        ["eläke", "eläkeikä", "eläkeläinen", "eläkejärjestelmä"],
    "lapset":       ["lapsi", "lapset", "lasten", "perhe", "vanhemmat", "päiväkoti"],
    "väestö":       ["väestö", "väestönkasvu", "ikääntyminen", "syntyvyys"],

    # ── Transport / Infrastructure ────────────────────────────────────────────
    "liikenne":     ["liikenne", "liikenteen", "tie", "moottoritie", "valtatie", "onnettomuus"],
    "rautatiet":    ["juna", "rautatie", "vr ", "liikennehäiriö"],
    "lentoliikenne": ["lentokone", "lentokenttä", "lentoliikenne", "lentoyhtiö"],

    # ── Science / Research ────────────────────────────────────────────────────
    "tiede":        ["tutkimus", "tiede", "tutkijat", "tiedejulkaisu", "löydös"],
    "avaruus":      ["avaruus", "planeetta", "tähti", "nasa", "avaruusalus"],
    "fysiikka":     ["fysiikka", "hiukkasfysiikka", "kvantti", "reaktori"],

    # ── Finland / Regions ─────────────────────────────────────────────────────
    "helsinki":     ["helsinki", "helsingin", "helsingissä"],
    "tampere":      ["tampere", "tampereen", "tampereella"],
    "oulu":         [r"\boulu\b", "oulun", "oulussa"],
    "lappi":        [r"\blappi\b", "lapin", "lapissa", "rovaniemi"],
}

# Category → guaranteed base tags (always included regardless of keyword match)
CATEGORY_BASE_TAGS: dict[str, list[str]] = {
    "Kotimaa":    ["kotimaa"],
    "Ulkomaat":   ["ulkomaat"],
    "Talous":     ["talous"],
    "Teknologia": ["teknologia"],
    "Urheilu":    ["urheilu"],
    "Kulttuuri":  ["kulttuuri"],
    "Tiede":      ["tiede"],
}


# ── Front matter helpers ──────────────────────────────────────────────────────

def parse_fm(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
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
            elif val.lower() in ("true", "false"):
                meta[key] = val.lower() == "true"
            else:
                meta[key] = val
    return meta, body


def write_tags(text: str, tags: list[str]) -> str:
    """Inject/replace tags field in front matter."""
    # Remove existing tags block if present
    cleaned = re.sub(r'^tags:.*?\n(?:  - .*\n)*', '', text, flags=re.MULTILINE)

    tag_block = "tags:\n" + "".join(f"  - {t}\n" for t in tags)

    # Insert after draft: or categories block, falling back to before closing ---
    for pattern in [r'^(draft:.*\n)', r'^(categories:(?:.*\n)(?:  - .*\n)*)', r'^(author:.*\n)']:
        m = re.search(pattern, cleaned, re.MULTILINE)
        if m:
            insert_pos = m.end()
            return cleaned[:insert_pos] + tag_block + cleaned[insert_pos:]

    # Fallback: insert before closing ---
    end = cleaned.find("\n---", 3)
    if end != -1:
        return cleaned[:end] + "\n" + tag_block.rstrip() + cleaned[end:]
    return cleaned


# ── Tagging logic ─────────────────────────────────────────────────────────────

def score_tags(title: str, body_excerpt: str, category: str) -> list[str]:
    """Return 3-5 tags for an article based on keyword matching."""
    searchable = (title + " " + body_excerpt).lower()

    # Score each candidate tag
    scores: dict[str, int] = {}
    for tag, patterns in TAG_RULES.items():
        for pattern in patterns:
            if re.search(pattern, searchable):
                scores[tag] = scores.get(tag, 0) + 1

    # Start with category base tags
    base = CATEGORY_BASE_TAGS.get(category, [])
    selected = list(base)

    # Add keyword-matched tags by score, excluding already-selected and base-category duplicates
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    for tag, _ in ranked:
        if tag not in selected:
            selected.append(tag)
        if len(selected) >= MAX_TAGS:
            break

    # Pad to MIN_TAGS with category-specific fallbacks if needed
    fallbacks = {
        "Kotimaa":    ["politiikka", "suomi"],
        "Ulkomaat":   ["kansainvälinen", "politiikka"],
        "Talous":     ["yritys", "rahoitus"],
        "Teknologia": ["digitalisaatio", "innovaatio"],
        "Urheilu":    ["kilpailu", "liikunta"],
        "Kulttuuri":  ["taide", "viihde"],
        "Tiede":      ["tutkimus", "tiede"],
    }
    for fallback in fallbacks.get(category, []):
        if len(selected) >= MIN_TAGS:
            break
        if fallback not in selected:
            selected.append(fallback)

    return selected[:MAX_TAGS]


def find_untagged(limit: int | None = None, offset: int = 0) -> list[Path]:
    files = sorted(CONTENT_DIR.glob("*.md"))
    untagged = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        meta, _ = parse_fm(text)
        if meta.get("draft") is True:
            continue
        tags = meta.get("tags", [])
        if not tags:
            untagged.append(f)
    untagged = untagged[offset:]
    if limit:
        untagged = untagged[:limit]
    return untagged


# ── Main ──────────────────────────────────────────────────────────────────────

def run(
    dry_run: bool = False,
    limit: int | None = None,
    offset: int = 0,
    overwrite: bool = False,
) -> dict:
    if overwrite:
        files = sorted(CONTENT_DIR.glob("*.md"))
        targets = [f for f in files if not parse_fm(f.read_text())[0].get("draft")]
        targets = targets[offset:]
        if limit:
            targets = targets[:limit]
    else:
        targets = find_untagged(limit=limit, offset=offset)

    total = len(targets)
    print(f"🏷  Auto-tagger — {total} articles to tag (dry_run={dry_run})")

    if not total:
        print("✅ Nothing to tag.")
        return {"total": 0, "tagged": 0}

    tagged_count = 0
    log_entries = []

    for fpath in targets:
        text = fpath.read_text(encoding="utf-8")
        meta, body = parse_fm(text)
        title = meta.get("title", fpath.stem)
        cats = meta.get("categories", [])
        category = cats[0] if isinstance(cats, list) and cats else "Kotimaa"
        body_excerpt = body[:400]

        tags = score_tags(title, body_excerpt, category)

        entry = {
            "file": fpath.name,
            "title": title[:60],
            "category": category,
            "tags": tags,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if dry_run:
            print(f"  [{category:12s}] {title[:50]:50s} → {tags}")
        else:
            new_text = write_tags(text, tags)
            fpath.write_text(new_text, encoding="utf-8")
            tagged_count += 1
            if tagged_count % 50 == 0:
                print(f"  … {tagged_count}/{total}")

        log_entries.append(entry)

    if not dry_run:
        LOGS_DIR.mkdir(exist_ok=True)
        existing = []
        if TAG_LOG.exists():
            try:
                existing = json.loads(TAG_LOG.read_text())
            except json.JSONDecodeError:
                pass
        existing.extend(log_entries)
        TAG_LOG.write_text(json.dumps(existing[-5000:], indent=2))  # keep last 5000
        print(f"\n✅ Tagged {tagged_count}/{total} articles")
    else:
        print(f"\n[dry-run] Would tag {total} articles")

    return {"total": total, "tagged": tagged_count, "entries": log_entries}


def show_stats():
    """Print current tag distribution."""
    from collections import Counter
    tag_ctr: Counter = Counter()
    tagged = 0
    total = 0
    for f in sorted(CONTENT_DIR.glob("*.md")):
        meta, _ = parse_fm(f.read_text())
        if meta.get("draft"):
            continue
        total += 1
        tags = meta.get("tags", [])
        if tags:
            tagged += 1
            tag_ctr.update(tags)

    print(f"Articles: {total} total, {tagged} tagged ({total - tagged} untagged)")
    print("\nTop 30 tags:")
    for tag, count in tag_ctr.most_common(30):
        print(f"  {count:4d}  {tag}")


def main():
    args = sys.argv[1:]
    if "--stats" in args:
        show_stats()
        return

    dry_run = "--dry-run" in args
    overwrite = "--overwrite" in args
    limit = None
    offset = 0

    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    if "--offset" in args:
        idx = args.index("--offset")
        if idx + 1 < len(args):
            offset = int(args[idx + 1])

    run(dry_run=dry_run, limit=limit, offset=offset, overwrite=overwrite)


if __name__ == "__main__":
    main()
