"""
quality_gate.py — Article quality scoring for Uutistenlukija pipeline.

Extends the existing post-rewrite gate with richer article-quality heuristics:
- length
- readability
- completeness
- duplication
- language

Articles are scored on the historical 0–80 internal scale for compatibility,
and also exposed as a normalized 0–10 score for easier reasoning/logging.
Articles below the configured threshold are rejected to pipeline/rejected/YYYY-MM-DD/.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import NamedTuple

from filler_gate import analyze_article as _analyze_filler_article, log_hits as _log_filler_hits
from source_confidence_guard import source_confidence_issues

# ── Config ────────────────────────────────────────────────────────────────────

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONTENT_POSTS_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "content", "posts"))
REJECTED_DIR = os.path.join(_PIPELINE_DIR, "rejected")
REJECTS_LOG = os.path.join(_PIPELINE_DIR, "logs", "quality_gate_rejects.log")
MIN_BODY_WORDS = 250

# Historical internal threshold (0–80). Corresponds to 5.0 / 10 normalized.
# TEMPORARILY lowered 40→30 (2026-04-02) to unblock publishing after 60h drought.
# Missing images zero out image score, pushing otherwise-good articles below 40.
# TODO: restore to 40 once image generation pipeline is fixed.
REJECT_THRESHOLD = 30
DEFAULT_NORMALIZED_THRESHOLD = 3.5
MAX_DUPLICATION_LOOKBACK = 50

_PLACEHOLDER_PATTERNS = re.compile(
    r"\bLorem\b|\bTODO\b|\bPLACEHOLDER\b|\[kuva\]",
    re.IGNORECASE,
)

_KW_STOPWORDS = {
    "ja", "on", "ei", "se", "että", "oli", "kun", "tai", "myös",
    "sekä", "ovat", "en", "et", "hän", "me", "te", "he",
    "olla", "joka", "jo", "niin", "kuin", "siis",
}

_GENERIC_ENDING_PATTERNS = (
    "tulevat viikot",
    "aika näyttää",
    "voidaan todeta",
    "on tärkeää",
)

_FINNISH_SIGNAL_WORDS = {
    "ja", "on", "että", "suomi", "suomen", "mutta", "myös", "kuten", "joka",
    "sekä", "oli", "ovat", "voi", "voidaan", "uutinen", "artikkeli", "tänään",
    "vielä", "sitten", "uusi", "nyt", "tässä", "sillä", "kanssa", "ilman",
    "mukaan", "kertoo", "sanoo", "osavaltio", "vuonna", "aikana", "mukaan",
    "lisäksi", "kuitenkin", "vuoden", "aikoo", "ole", "ovat", "eivät",
}

# ── Number extraction ─────────────────────────────────────────────────────────

_NUMBER_UNIT_PATTERN = (
    r"%|prosent[a-zäöå]*|miljard[a-zäöå]*|mrd|miljoon[a-zäöå]*|milj[.]?"
    r"|kg|km|m²|mw|gw|€|euro[a-zäöå]*|dollari[a-zäöå]*"
)
_NUMBER_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"
    rf"|\b\d{{1,3}}(?:[,.\s]\d{{3}})*(?:[,.]\d+)?\s*(?:{_NUMBER_UNIT_PATTERN})?",
    re.IGNORECASE,
)

_FINNISH_MONTHS = {
    "tammikuuta": 1,
    "helmikuuta": 2,
    "maaliskuuta": 3,
    "huhtikuuta": 4,
    "toukokuuta": 5,
    "kesäkuuta": 6,
    "heinäkuuta": 7,
    "elokuuta": 8,
    "syyskuuta": 9,
    "lokakuuta": 10,
    "marraskuuta": 11,
    "joulukuuta": 12,
}
_TEXTUAL_DATE_RE = re.compile(
    r"\b(\d{1,2})\.\s+(" + "|".join(_FINNISH_MONTHS) + r")(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[.]([01]?\d)[.](?:(\d{4})\b)?")


def _extract_numbers(text: str) -> set[str]:
    without_dates = _NUMERIC_DATE_RE.sub(" ", text or "")
    without_dates = _TEXTUAL_DATE_RE.sub(" ", without_dates)
    raw = _NUMBER_RE.findall(without_dates)
    normalised: set[str] = set()
    for token in raw:
        n = token.strip()
        unit_match = re.search(rf"({_NUMBER_UNIT_PATTERN})$", n, re.IGNORECASE)
        unit = unit_match.group(0).lower() if unit_match else ""
        if unit == "%" or unit.startswith("prosent"):
            unit = "%"
        elif unit == "mrd" or unit.startswith("miljard"):
            unit = "miljardi"
        elif unit.startswith("miljoon") or unit.startswith("milj"):
            unit = "miljoona"
        elif unit == "€" or unit.startswith("euro"):
            unit = "euro"
        elif unit.startswith("dollari"):
            unit = "dollari"
        num_part = n[:unit_match.start()].strip() if unit_match else n
        if re.match(r"^\d{1,3}(,\d{3})+$", num_part):
            num_part = num_part.replace(",", "")
        elif re.match(r"^\d{1,3}(\s\d{3})+$", num_part):
            num_part = re.sub(r"\s", "", num_part)
        else:
            num_part = re.sub(r"\s+", "", num_part).replace(",", ".")
        normalised.add((num_part + unit).lower())
    return normalised


def _date_signatures(text: str) -> set[tuple[int, int, int | None]]:
    signatures: set[tuple[int, int, int | None]] = set()
    for day, month, year in _NUMERIC_DATE_RE.findall(text or ""):
        signatures.add((int(day), int(month), int(year) if year else None))
    for day, month_name, year in _TEXTUAL_DATE_RE.findall(text or ""):
        signatures.add((
            int(day),
            _FINNISH_MONTHS[month_name.lower()],
            int(year) if year else None,
        ))
    return signatures


def check_numbers_sourced(source_text: str, content: str, title: str = "") -> list[str]:
    source_nums = _extract_numbers(source_text)
    article_text = (title or "") + " " + (content or "")
    article_nums = _extract_numbers(article_text)
    unsourced = article_nums - source_nums
    source_dates = _date_signatures(source_text)
    for day, month, year in _date_signatures(article_text):
        supported = any(
            source_day == day
            and source_month == month
            and (year is None or source_year == year)
            for source_day, source_month, source_year in source_dates
        )
        if not supported:
            unsourced.add(f"{day}.{month}" + (f".{year}" if year is not None else ""))
    return sorted(unsourced)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"\b[a-zäöåA-ZÄÖÅ]{2,}\b", (text or "").lower())


def _jaccard_similarity(a: str, b: str) -> float:
    sa = set(_tokenize_words(a))
    sb = set(_tokenize_words(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def _frontmatter_value(text: str, key: str) -> str:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not m:
        return ""
    return m.group(1).strip().strip('"')


def _first_paragraph(text: str) -> str:
    paras = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    return paras[0] if paras else ""


def _load_recent_published_articles(limit: int = MAX_DUPLICATION_LOOKBACK) -> list[dict]:
    posts: list[dict] = []
    if not os.path.isdir(_CONTENT_POSTS_DIR):
        return posts

    candidates = []
    for name in os.listdir(_CONTENT_POSTS_DIR):
        if not name.endswith(".md"):
            continue
        path = os.path.join(_CONTENT_POSTS_DIR, name)
        try:
            candidates.append((os.path.getmtime(path), path))
        except OSError:
            continue

    for _, path in sorted(candidates, reverse=True)[:limit]:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            parts = raw.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter = parts[1]
            body = parts[2]
            posts.append(
                {
                    "title": _frontmatter_value(frontmatter, "title"),
                    "description": _frontmatter_value(frontmatter, "description"),
                    "summary": _frontmatter_value(frontmatter, "summary"),
                    "content": body,
                }
            )
        except OSError:
            continue
    return posts


_RECENT_PUBLISHED_CACHE: list[dict] | None = None


def _recent_published_articles() -> list[dict]:
    global _RECENT_PUBLISHED_CACHE
    if _RECENT_PUBLISHED_CACHE is None:
        _RECENT_PUBLISHED_CACHE = _load_recent_published_articles()
    return _RECENT_PUBLISHED_CACHE


def _score_length(word_count: int) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if word_count < 180:
        score = 0.5
        reasons.append(f"length very short ({word_count} words)")
    elif word_count < 300:
        score = 2.5 + (word_count - 180) / 120 * 2.0
        reasons.append(f"length under target ({word_count} words)")
    elif word_count < 400:
        score = 5.0 + (word_count - 300) / 100 * 3.0
    elif word_count <= 1200:
        score = 10.0
    elif word_count <= 1600:
        score = 9.0 - ((word_count - 1200) / 400) * 2.0
    elif word_count <= 2000:
        score = 7.0 - ((word_count - 1600) / 400) * 3.0
        reasons.append(f"length long ({word_count} words)")
    else:
        score = max(1.0, 4.0 - (word_count - 2000) / 400)
        reasons.append(f"length very long ({word_count} words)")
    return _clamp(score), reasons


def _score_readability(content: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    paragraph_count = len(paragraphs)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", _normalize_text(content)) if s.strip()]
    sentence_lengths = [len(_tokenize_words(s)) for s in sentences if _tokenize_words(s)]

    score = 10.0
    if paragraph_count < 3:
        score -= 3.5
        reasons.append(f"readability few paragraphs ({paragraph_count})")
    elif paragraph_count < 5:
        score -= 1.0

    if paragraphs:
        longest_para = max(len(_tokenize_words(p)) for p in paragraphs)
        if longest_para > 220:
            score -= 2.5
            reasons.append("readability wall of text")
        elif longest_para > 160:
            score -= 1.0

    if sentence_lengths:
        avg_sentence = sum(sentence_lengths) / len(sentence_lengths)
        distinct_lengths = len(set(min(30, n // 4) for n in sentence_lengths))
        if avg_sentence > 28:
            score -= 2.0
            reasons.append(f"readability long sentences ({avg_sentence:.1f} avg words)")
        elif avg_sentence > 23:
            score -= 1.0
        if distinct_lengths < 3 and len(sentence_lengths) >= 5:
            score -= 1.5
            reasons.append("readability low sentence variety")
    else:
        score = 0.0
        reasons.append("readability no clear sentences")

    return _clamp(score), reasons


def _score_completeness(article: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    checks = {
        "title": bool((article.get("title") or "").strip()),
        "summary": bool((article.get("summary") or article.get("description") or "").strip()),
        "key_points": len(article.get("key_points") or []) >= 2,
        "image": bool((article.get("image") or "").strip()),
        "category": bool((article.get("category") or "").strip()),
        "source_url": bool((article.get("link") or article.get("source_url") or "").strip()),
    }
    missing = [name for name, ok in checks.items() if not ok]
    if missing:
        reasons.append("missing: " + ", ".join(missing))
    score = ((len(checks) - len(missing)) / len(checks)) * 10.0
    return _clamp(score), reasons


def _score_duplication(article: dict) -> tuple[float, list[str]]:
    reasons: list[str] = []
    current_title = article.get("title", "") or ""
    current_summary = article.get("summary", "") or article.get("description", "") or ""
    current_blob = f"{current_title} {current_summary}".strip()
    if not current_blob:
        return 4.0, ["duplication no title/summary to compare"]

    max_sim = 0.0
    max_title_sim = 0.0
    for prev in _recent_published_articles():
        prev_blob = f"{prev.get('title', '')} {prev.get('summary', '') or prev.get('description', '')}".strip()
        max_sim = max(max_sim, _jaccard_similarity(current_blob, prev_blob))
        max_title_sim = max(max_title_sim, _jaccard_similarity(current_title, prev.get("title", "")))

    worst = max(max_sim, max_title_sim)
    if worst >= 0.80:
        reasons.append(f"high duplication similarity ({worst:.2f})")
    elif worst >= 0.60:
        reasons.append(f"moderate duplication similarity ({worst:.2f})")

    score = 10.0 - worst * 10.0
    return _clamp(score), reasons


def _score_language(content: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    words = _tokenize_words(content)
    sample = words[:100]
    if not sample:
        return 0.0, ["language no text sample"]

    finnish_hits = sum(1 for w in sample if w in _FINNISH_SIGNAL_WORDS)
    finnish_ratio = finnish_hits / len(sample)

    diacritic_hits = sum(1 for w in sample if any(ch in w for ch in "äöå"))
    diacritic_ratio = diacritic_hits / len(sample)

    score = min(10.0, finnish_ratio * 60.0 + diacritic_ratio * 18.0)
    if len(sample) >= 40 and finnish_ratio < 0.06:
        reasons.append(f"language weak Finnish signal ({finnish_ratio:.1%})")
    elif len(sample) >= 40 and finnish_ratio < 0.11:
        reasons.append(f"language borderline Finnish signal ({finnish_ratio:.1%})")
    return _clamp(score), reasons


# ── Result types ──────────────────────────────────────────────────────────────

class ScoreBreakdown(NamedTuple):
    total: int
    normalized_score: float
    length_score: float
    readability_score: float
    completeness_score: float
    duplication_score: float
    language_score: float
    word_count_pts: int
    title_pts: int
    description_pts: int
    image_pts: int
    category_pts: int
    no_placeholder_pts: int
    hard_fails: list[str]
    soft_warnings: list[str]
    filler_labels: list[str]
    filler_penalty: int
    reasons: list[str]
    passes: bool


class GateResult(NamedTuple):
    passed: list[dict]
    rejected: list[dict]
    scores: dict[str, int]
    reject_reasons: dict
    stats: dict


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_article(article: dict) -> ScoreBreakdown:
    content = article.get("content", "") or ""
    title = article.get("title", "") or ""
    description = article.get("description", "") or ""
    image = article.get("image", "") or ""
    category = article.get("category", "") or ""
    source_text = article.get("source_text", "") or ""
    degraded_mode = bool(article.get("degraded_mode"))

    word_count = len(content.split())
    missing_image = not image.strip()

    # Historical scoring kept for compatibility/metrics.
    if word_count >= 500:
        wc_pts = 30
    elif word_count >= 350:
        wc_pts = 25
    elif word_count >= 200:
        wc_pts = 10
    else:
        wc_pts = 0

    title_pts = 10 if (title and len(title) < 100) else 0
    desc_len = len(description.strip())
    desc_pts = 10 if (50 <= desc_len <= 160) else 0
    image_pts = 10 if image.strip() or degraded_mode else 0
    cat_pts = 10 if category.strip() else 0
    placeholder_pts = 0 if _PLACEHOLDER_PATTERNS.search(content + title + description) else 10

    total = wc_pts + title_pts + desc_pts + image_pts + cat_pts + placeholder_pts
    soft_warnings: list[str] = []
    reasons: list[str] = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    # New normalized scoring (0–10)
    length_score, length_reasons = _score_length(word_count)
    readability_score, readability_reasons = _score_readability(content)
    completeness_score, completeness_reasons = _score_completeness(article)
    duplication_score, duplication_reasons = _score_duplication(article)
    language_score, language_reasons = _score_language(content)

    reasons.extend(length_reasons)
    reasons.extend(readability_reasons)
    reasons.extend(completeness_reasons)
    reasons.extend(duplication_reasons)
    reasons.extend(language_reasons)

    weighted_score = (
        length_score * 0.22
        + readability_score * 0.22
        + completeness_score * 0.22
        + duplication_score * 0.18
        + language_score * 0.16
    )

    if missing_image and not degraded_mode:
        weighted_score = max(0.0, weighted_score - 0.2)  # ~1.6 points on legacy 80-point scale

    if paragraphs:
        last_paragraph = paragraphs[-1].lower()
        matched_generic = [phrase for phrase in _GENERIC_ENDING_PATTERNS if phrase in last_paragraph]
        if matched_generic:
            total = max(0, total - 5)
            weighted_score = max(0.0, weighted_score - 0.5)
            soft_warnings.append("generic_ending: " + ", ".join(matched_generic))
            reasons.append("generic ending")

    hard_fails: list[str] = []
    filler_result = _analyze_filler_article(article)
    if filler_result.matches:
        total = max(0, total - filler_result.total_penalty)
        weighted_score = max(0.0, weighted_score - min(2.5, filler_result.total_penalty / 10.0))
        soft_warnings.append(
            f"filler_gate (-{filler_result.total_penalty}): " + ", ".join(filler_result.labels)
        )
        reasons.append("filler phrases")
        if filler_result.total_penalty >= 30:
            hard_fails.append(f"excessive_filler ({filler_result.total_penalty} pts: {', '.join(filler_result.labels[:3])})")
    source_text_words = len((source_text or "").split())
    if source_text_words > 0 and source_text_words < 60:
        hard_fails.append(f"thin_source ({source_text_words} words in source — likely paywall/stub)")

    if word_count < MIN_BODY_WORDS and not degraded_mode:
        hard_fails.append(f"too_short ({word_count} words, min {MIN_BODY_WORDS})")

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
    if len(content_words) >= 80:
        freq = Counter(content_words)
        top_word, top_count = freq.most_common(1)[0]
        ratio = top_count / len(content_words)
        if ratio > 0.06 and top_count >= 6:
            hard_fails.append(f"keyword stuffing: '{top_word}' {top_count}× ({ratio:.1%})")

    # Body-only unsourced numbers remain a warning because editorial rewrites can
    # reformat valid figures. New figures in the title or lead are central claims
    # and fail closed.
    if source_text:
        unsourced = check_numbers_sourced(source_text, content, title)
        if unsourced:
            sample = ", ".join(unsourced[:5])
            soft_warnings.append(f"unsourced_numbers: {sample}")
            reasons.append("unsourced numbers")
        lead = paragraphs[0] if paragraphs else ""
        central_unsourced = check_numbers_sourced(source_text, lead, title)
        if central_unsourced:
            sample = ", ".join(central_unsourced[:5])
            hard_fails.append(f"central unsourced number(s): {sample}")

    hard_fails.extend(source_confidence_issues(article))

    normalized_score = round(_clamp(weighted_score), 2)
    effective_threshold = max(DEFAULT_NORMALIZED_THRESHOLD, round(REJECT_THRESHOLD / 80 * 10, 2))
    passes = (total >= REJECT_THRESHOLD) and (normalized_score >= effective_threshold) and not hard_fails

    return ScoreBreakdown(
        total=total,
        normalized_score=normalized_score,
        length_score=round(length_score, 2),
        readability_score=round(readability_score, 2),
        completeness_score=round(completeness_score, 2),
        duplication_score=round(duplication_score, 2),
        language_score=round(language_score, 2),
        word_count_pts=wc_pts,
        title_pts=title_pts,
        description_pts=desc_pts,
        image_pts=image_pts,
        category_pts=cat_pts,
        no_placeholder_pts=placeholder_pts,
        hard_fails=hard_fails,
        soft_warnings=soft_warnings,
        filler_labels=filler_result.labels,
        filler_penalty=filler_result.total_penalty,
        reasons=sorted(set(reasons)),
        passes=passes,
    )


# ── Gate ──────────────────────────────────────────────────────────────────────

def run_gate(articles: list[dict], threshold: int = REJECT_THRESHOLD) -> GateResult:
    passed = []
    rejected = []
    scores: dict[str, int] = {}
    reason_counter: Counter = Counter()
    filler_results: list = []

    for article in articles:
        title = article.get("title", "?")[:60]
        breakdown = score_article(article)
        filler_result = _analyze_filler_article(article)
        filler_results.append(filler_result)
        scores[title] = breakdown.total

        if breakdown.soft_warnings:
            print(
                f"[quality] WARNING ({breakdown.total}/80, norm={breakdown.normalized_score}/10): '{title}' — "
                + " | ".join(breakdown.soft_warnings)
            )
        if breakdown.filler_labels:
            _log_filler_hits(article, filler_result)

        if breakdown.passes:
            passed.append(article)
        else:
            reasons: list[str] = []
            if breakdown.total < threshold or breakdown.normalized_score < DEFAULT_NORMALIZED_THRESHOLD:
                reasons.append(
                    f"score {breakdown.total}/{threshold} norm={breakdown.normalized_score}/10 "
                    f"(length={breakdown.length_score} readability={breakdown.readability_score} "
                    f"complete={breakdown.completeness_score} dup={breakdown.duplication_score} lang={breakdown.language_score})"
                )
            reasons.extend(breakdown.reasons)
            reasons.extend(breakdown.hard_fails)

            reason_str = " | ".join(dict.fromkeys(reasons))
            print(f"[quality] REJECTED ({breakdown.total}/80, norm={breakdown.normalized_score}/10): '{title}' — {reason_str}")

            _save_rejected(article, breakdown, reason_str)
            rejected.append(article)
            _log_reject(article, reason_str)

            if breakdown.total < threshold or breakdown.normalized_score < DEFAULT_NORMALIZED_THRESHOLD:
                reason_counter["low_score"] += 1
            for reason in breakdown.reasons:
                if reason.startswith("length"):
                    reason_counter["length"] += 1
                elif reason.startswith("readability"):
                    reason_counter["readability"] += 1
                elif reason.startswith("missing"):
                    reason_counter["completeness"] += 1
                elif "duplication" in reason:
                    reason_counter["duplication"] += 1
                elif reason.startswith("language"):
                    reason_counter["language"] += 1
                else:
                    reason_counter["other_soft"] += 1
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
                elif "thin_source" in hf:
                    reason_counter["thin_source"] += 1
                else:
                    reason_counter["other_hard"] += 1

    all_scores = list(scores.values())
    filler_hit_articles = 0
    filler_total_penalty = 0
    filler_pattern_counts: Counter = Counter()
    for filler_result in filler_results:
        if filler_result.matches:
            filler_hit_articles += 1
            filler_total_penalty += filler_result.total_penalty
            for label in filler_result.labels:
                filler_pattern_counts[label] += 1

    normalized_scores = []
    for article in articles:
        normalized_scores.append(score_article(article).normalized_score)

    stats = {
        "total": len(articles),
        "passed": len(passed),
        "rejected": len(rejected),
        "avg_score": round(sum(all_scores) / len(all_scores), 1) if all_scores else 0,
        "avg_normalized_score": round(sum(normalized_scores) / len(normalized_scores), 2) if normalized_scores else 0,
        "min_score": min(all_scores) if all_scores else 0,
        "max_score": max(all_scores) if all_scores else 0,
        "threshold": threshold,
        "normalized_threshold": DEFAULT_NORMALIZED_THRESHOLD,
        "filler_hits": filler_hit_articles,
        "filler_penalty_total": filler_total_penalty,
        "filler_patterns": dict(filler_pattern_counts),
    }

    if rejected:
        print(
            f"[quality] {len(rejected)} rejected, {len(passed)} passed "
            f"(avg score {stats['avg_score']}/80, avg norm {stats['avg_normalized_score']}/10, threshold {threshold})"
        )

    return GateResult(
        passed=passed,
        rejected=rejected,
        scores=scores,
        reject_reasons=dict(reason_counter),
        stats=stats,
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_rejected(article: dict, breakdown: ScoreBreakdown, reason: str) -> None:
    day_dir = os.path.join(REJECTED_DIR, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^\w\-]", "_", article.get("title", "unknown")[:40])
    path = os.path.join(day_dir, f"{ts}_{slug}.md")
    payload = {
        "score": breakdown.total,
        "normalized_score": breakdown.normalized_score,
        "reasons": breakdown.reasons,
        "hard_fails": breakdown.hard_fails,
        "soft_warnings": breakdown.soft_warnings,
        "length_score": breakdown.length_score,
        "readability_score": breakdown.readability_score,
        "completeness_score": breakdown.completeness_score,
        "duplication_score": breakdown.duplication_score,
        "language_score": breakdown.language_score,
        "rejected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        frontmatter = "---\n" + "\n".join(
            [
                f'title: {json.dumps(article.get("title", "unknown"), ensure_ascii=False)}',
                f"quality_score: {breakdown.total}",
                f"quality_score_normalized: {breakdown.normalized_score}",
                f"reject_reason: {json.dumps(reason, ensure_ascii=False)}",
                f"rejected_at: {json.dumps(payload['rejected_at'])}",
                "quality_breakdown:",
                f"  length: {breakdown.length_score}",
                f"  readability: {breakdown.readability_score}",
                f"  completeness: {breakdown.completeness_score}",
                f"  duplication: {breakdown.duplication_score}",
                f"  language: {breakdown.language_score}",
                "reasons:",
            ]
            + [f"  - {json.dumps(r, ensure_ascii=False)}" for r in breakdown.reasons]
            + ["hard_fails:"]
            + [f"  - {json.dumps(r, ensure_ascii=False)}" for r in breakdown.hard_fails]
            + ["soft_warnings:"]
            + [f"  - {json.dumps(r, ensure_ascii=False)}" for r in breakdown.soft_warnings]
            + ["---", "", json.dumps(article, ensure_ascii=False, indent=2)]
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(frontmatter + "\n")
    except OSError as e:
        print(f"[quality] WARNING: could not save rejected article: {e}")


def _log_reject(article: dict, reason: str) -> None:
    os.makedirs(os.path.dirname(REJECTS_LOG), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    title = article.get("title", "?")[:80]
    slug = article.get("slug", "?")
    words = len((article.get("content", "") or "").split())
    line = f"{ts}\t{words}w\t{slug}\t{reason}\t{title}\n"
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
        article = data.get("article", data)
        bd = score_article(article)
        title = article.get("title", "?")[:70]
        print(f"Score: {bd.total}/80  norm={bd.normalized_score}/10  passes={bd.passes}  (threshold {REJECT_THRESHOLD})")
        print(f"  length       : {bd.length_score:>4}/10")
        print(f"  readability  : {bd.readability_score:>4}/10")
        print(f"  completeness : {bd.completeness_score:>4}/10")
        print(f"  duplication  : {bd.duplication_score:>4}/10")
        print(f"  language     : {bd.language_score:>4}/10")
        print(f"  legacy_wc    : {bd.word_count_pts:2d}/30")
        print(f"  legacy_title : {bd.title_pts:2d}/10")
        print(f"  legacy_desc  : {bd.description_pts:2d}/10")
        print(f"  legacy_image : {bd.image_pts:2d}/10")
        print(f"  legacy_cat   : {bd.category_pts:2d}/10")
        print(f"  placeholders : {bd.no_placeholder_pts:2d}/10")
        if bd.reasons:
            print(f"  reasons      : {'; '.join(bd.reasons)}")
        if bd.hard_fails:
            print(f"  hard_fails   : {'; '.join(bd.hard_fails)}")
        if bd.soft_warnings:
            print(f"  soft_warnings: {'; '.join(bd.soft_warnings)}")
        print(f"  title        : {title!r}")

    if len(sys.argv) < 2:
        print("Usage: quality_gate.py <article.json> [<article.json> ...]")
        sys.exit(1)

    for fpath in sys.argv[1:]:
        print(f"\n{'='*60}")
        print(f"File: {fpath}")
        _score_file(fpath)
