"""
quality_gate.py — Article quality scoring for Uutistenlukija pipeline.

Scores each article 0–80 across six criteria. Articles below the threshold
are rejected to pipeline/rejected/ before publishing.

Scoring breakdown (max 80):
  Word count        30pts  (<100→0, 100-200→10, 200-400→25, 400+→30)
  Title             10pts  (non-empty, <100 chars)
  Meta description  10pts  (non-empty, 50–160 chars)
  Image             10pts  (non-empty image field)
  Category          10pts  (non-empty category)
  No placeholders   10pts  (no "Lorem", "TODO", "PLACEHOLDER", "[kuva]")

Hard disqualifiers (applied after score, cause instant reject regardless of score):
  - Fewer than 3 paragraphs
  - Lead paragraph < 30 words
  - >60% bullet lines (pure listicle)
  - Keyword stuffing: any word >5% of content words

Default reject threshold: 40 / 80 (50%).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import NamedTuple

# ── Config ────────────────────────────────────────────────────────────────────

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
REJECTED_DIR  = os.path.join(_PIPELINE_DIR, "rejected")
REJECTS_LOG   = os.path.join(_PIPELINE_DIR, "logs", "quality_gate_rejects.log")
MIN_BODY_WORDS = 280   # SEO minimum — align hard floor with rewriter threshold

REJECT_THRESHOLD = 40   # minimum score to pass (out of 80)

_PLACEHOLDER_PATTERNS = re.compile(
    r"\bLorem\b|\bTODO\b|\bPLACEHOLDER\b|\[kuva\]",
    re.IGNORECASE,
)

_KW_STOPWORDS = {
    "ja", "on", "ei", "se", "että", "oli", "kun", "tai", "myös",
    "sekä", "ovat", "en", "et", "hän", "me", "te", "he",
    "olla", "joka", "jo", "niin", "kuin", "siis",
}

# ── Number extraction ─────────────────────────────────────────────────────────

# Matches: 4-digit years first, then integers/decimals with optional units
_NUMBER_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"                                                          # years 1900-2099
    r"|\b\d{1,3}(?:[,.\s]\d{3})*(?:[,.]\d+)?\s*(?:%|prosentt[ia]|milj(?:oona[a-z]*)?|mrd|kg|km|m²|MW|GW|€|euroa|dollari[a-z]*)?",
    re.IGNORECASE,
)

def _extract_numbers(text: str) -> set[str]:
    """Extract and normalise numeric tokens from text."""
    raw = _NUMBER_RE.findall(text or "")
    normalised: set[str] = set()
    for token in raw:
        n = token.strip()
        # Split off any trailing unit
        unit_match = re.search(r"(%|prosentt[ia]|milj(?:oona[a-z]*)?|mrd|kg|km|m²|MW|GW|€|euroa|dollari[a-z]*)$", n, re.IGNORECASE)
        unit = unit_match.group(0).lower() if unit_match else ""
        num_part = n[:unit_match.start()].strip() if unit_match else n
        # Normalise thousands separators: remove spaces and commas used as separators
        # Detect if comma is thousands separator (followed by exactly 3 digits at end)
        if re.match(r"^\d{1,3}(,\d{3})+$", num_part):
            num_part = num_part.replace(",", "")  # 30,000 → 30000
        elif re.match(r"^\d{1,3}(\s\d{3})+$", num_part):
            num_part = re.sub(r"\s", "", num_part)  # 30 000 → 30000
        else:
            # Remaining commas/spaces are decimal separators or noise
            num_part = re.sub(r"\s+", "", num_part).replace(",", ".")
        normalised.add((num_part + unit).lower())
    return normalised


def check_numbers_sourced(source_text: str, content: str, title: str = "") -> list[str]:
    """
    Return list of numeric tokens present in (title + content) but absent from source_text.
    Empty list means all numbers are sourced.
    """
    source_nums = _extract_numbers(source_text)
    article_nums = _extract_numbers((title or "") + " " + (content or ""))
    unsourced = article_nums - source_nums
    return sorted(unsourced)

# ── Result types ──────────────────────────────────────────────────────────────

class ScoreBreakdown(NamedTuple):
    total: int                  # 0–80
    word_count_pts: int         # 0/10/25/30
    title_pts: int              # 0/10
    description_pts: int        # 0/10
    image_pts: int              # 0/10
    category_pts: int           # 0/10
    no_placeholder_pts: int     # 0/10
    hard_fails: list[str]       # structural disqualifiers (non-scoring)
    passes: bool                # True if total >= threshold AND no hard_fails


class GateResult(NamedTuple):
    passed: list[dict]
    rejected: list[dict]        # articles that failed
    scores: dict[str, int]      # title → score (for logging/metrics)
    reject_reasons: dict        # reason_key → count
    stats: dict                 # summary stats


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_article(article: dict) -> ScoreBreakdown:
    """Score a single article. Returns ScoreBreakdown."""
    content     = article.get("content", "") or ""
    title       = article.get("title", "") or ""
    description = article.get("description", "") or ""
    image       = article.get("image", "") or ""
    category    = article.get("category", "") or ""
    source_text = article.get("source_text", "") or ""

    # ── Scoring criteria ──────────────────────────────────────────────────────

    # 1. Word count (30 pts)
    word_count = len(content.split())
    if word_count >= 400:
        wc_pts = 30
    elif word_count >= 200:
        wc_pts = 25
    elif word_count >= 100:
        wc_pts = 10
    else:
        wc_pts = 0

    # 2. Title (10 pts)
    title_pts = 10 if (title and len(title) < 100) else 0

    # 3. Meta description (10 pts)
    desc_len = len(description.strip())
    desc_pts = 10 if (50 <= desc_len <= 160) else 0

    # 4. Image (10 pts)
    image_pts = 10 if image.strip() else 0

    # 5. Category (10 pts)
    cat_pts = 10 if category.strip() else 0

    # 6. No placeholder text (10 pts)
    placeholder_pts = 0 if _PLACEHOLDER_PATTERNS.search(content + title + description) else 10

    total = wc_pts + title_pts + desc_pts + image_pts + cat_pts + placeholder_pts

    # ── Hard disqualifiers (structural, don't affect score but cause rejection) ──
    hard_fails: list[str] = []

    # Minimum word count (SEO gate — thin articles hurt rankings)
    if word_count < MIN_BODY_WORDS:
        hard_fails.append(f"too_short ({word_count} words, min {MIN_BODY_WORDS})")

    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if len(paragraphs) < 3:
        hard_fails.append(f"only {len(paragraphs)} paragraphs (min 3)")

    if paragraphs:
        lead_words = len(paragraphs[0].split())
        if lead_words < 30:
            hard_fails.append(f"lead paragraph too short ({lead_words} words, min 30)")

    lines = [l for l in content.splitlines() if l.strip()]
    if lines:
        bullet_lines = sum(1 for l in lines if re.match(r"^\s*[-*]\s", l))
        if bullet_lines / len(lines) > 0.60:
            hard_fails.append(f"listicle ({bullet_lines}/{len(lines)} bullet lines)")

    words_alpha = re.findall(r"\b[a-zäöåA-ZÄÖÅ]{4,}\b", content.lower())
    content_words = [w for w in words_alpha if w not in _KW_STOPWORDS]
    if len(content_words) >= 20:
        freq = Counter(content_words)
        top_word, top_count = freq.most_common(1)[0]
        ratio = top_count / len(content_words)
        if ratio > 0.05:
            hard_fails.append(
                f"keyword stuffing: '{top_word}' {top_count}× ({ratio:.1%})"
            )

    # Unsourced number check — only when source_text is available
    if source_text:
        unsourced = check_numbers_sourced(source_text, content, title)
        if unsourced:
            sample = ", ".join(unsourced[:5])
            hard_fails.append(f"unsourced numbers: {sample}")

    passes = (total >= REJECT_THRESHOLD) and not hard_fails

    return ScoreBreakdown(
        total=total,
        word_count_pts=wc_pts,
        title_pts=title_pts,
        description_pts=desc_pts,
        image_pts=image_pts,
        category_pts=cat_pts,
        no_placeholder_pts=placeholder_pts,
        hard_fails=hard_fails,
        passes=passes,
    )


# ── Gate ──────────────────────────────────────────────────────────────────────

def run_gate(articles: list[dict], threshold: int = REJECT_THRESHOLD) -> GateResult:
    """
    Score all articles and split into passed/rejected.

    Args:
        articles: list of article dicts from rewriter
        threshold: minimum score to pass (default REJECT_THRESHOLD)

    Returns:
        GateResult with passed list, rejected list, scores dict, and stats
    """
    passed = []
    rejected = []
    scores: dict[str, int] = {}
    reason_counter: Counter = Counter()

    for article in articles:
        title = article.get("title", "?")[:60]
        breakdown = score_article(article)
        scores[title] = breakdown.total

        if breakdown.passes:
            passed.append(article)
        else:
            # Build reject reason string
            reasons: list[str] = []
            if breakdown.total < threshold:
                reasons.append(
                    f"score {breakdown.total}/{threshold} "
                    f"(wc={breakdown.word_count_pts} title={breakdown.title_pts} "
                    f"desc={breakdown.description_pts} img={breakdown.image_pts} "
                    f"cat={breakdown.category_pts} placeholder={breakdown.no_placeholder_pts})"
                )
            reasons.extend(breakdown.hard_fails)

            reason_str = " | ".join(reasons)
            print(f"[quality] REJECTED ({breakdown.total}/80): '{title}' — {reason_str}")

            # Save to rejected dir
            _save_rejected(article, reason_str, breakdown.total)
            rejected.append(article)

            # Append to quality_gate_rejects.log
            _log_reject(article, reason_str)

            # Bucket reason keys for metrics
            if breakdown.total < threshold:
                reason_counter["low_score"] += 1
            for hf in breakdown.hard_fails:
                if "too_short" in hf:
                    reason_counter["too_short"] += 1
                elif "paragraphs" in hf:
                    reason_counter["few_paragraphs"] += 1
                elif "lead" in hf:
                    reason_counter["thin_lead"] += 1
                elif "listicle" in hf:
                    reason_counter["listicle"] += 1
                elif "stuffing" in hf:
                    reason_counter["keyword_stuffing"] += 1
                elif "unsourced numbers" in hf:
                    reason_counter["unsourced_numbers"] += 1
                else:
                    reason_counter["other"] += 1

    # Summary stats
    all_scores = list(scores.values())
    stats = {
        "total": len(articles),
        "passed": len(passed),
        "rejected": len(rejected),
        "avg_score": round(sum(all_scores) / len(all_scores), 1) if all_scores else 0,
        "min_score": min(all_scores) if all_scores else 0,
        "max_score": max(all_scores) if all_scores else 0,
        "threshold": threshold,
    }

    if rejected:
        print(
            f"[quality] {len(rejected)} rejected, {len(passed)} passed "
            f"(avg score {stats['avg_score']}/80, threshold {threshold})"
        )

    return GateResult(
        passed=passed,
        rejected=rejected,
        scores=scores,
        reject_reasons=dict(reason_counter),
        stats=stats,
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_rejected(article: dict, reason: str, score: int) -> None:
    """Save rejected article to pipeline/rejected/ for post-run review."""
    os.makedirs(REJECTED_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^\w\-]", "_", article.get("title", "unknown")[:40])
    path = os.path.join(REJECTED_DIR, f"{ts}_{slug}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"score": score, "reason": reason, "article": article},
                      f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[quality] WARNING: could not save rejected article: {e}")


def _log_reject(article: dict, reason: str) -> None:
    """Append one line to quality_gate_rejects.log for observability."""
    import re as _re
    os.makedirs(os.path.dirname(REJECTS_LOG), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    title = article.get("title", "?")[:80]
    slug  = article.get("slug", "?")
    words = len((article.get("content", "") or "").split())
    line  = f"{ts}\t{words}w\t{slug}\t{reason}\t{title}\n"
    try:
        with open(REJECTS_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(f"[quality] WARNING: could not write rejects log: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    def _score_file(path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        article = data.get("article", data)  # support raw or rejected-wrapper format
        bd = score_article(article)
        title = article.get("title", "?")[:70]
        print(f"Score: {bd.total}/80  passes={bd.passes}  (threshold {REJECT_THRESHOLD})")
        print(f"  word_count   : {bd.word_count_pts:2d}/30")
        print(f"  title        : {bd.title_pts:2d}/10")
        print(f"  description  : {bd.description_pts:2d}/10")
        print(f"  image        : {bd.image_pts:2d}/10")
        print(f"  category     : {bd.category_pts:2d}/10")
        print(f"  no_placeholder: {bd.no_placeholder_pts:2d}/10")
        if bd.hard_fails:
            print(f"  hard_fails   : {'; '.join(bd.hard_fails)}")
        print(f"  title        : {title!r}")

    if len(sys.argv) < 2:
        print("Usage: quality_gate.py <article.json> [<article.json> ...]")
        sys.exit(1)

    for fpath in sys.argv[1:]:
        print(f"\n{'='*60}")
        print(f"File: {fpath}")
        _score_file(fpath)
