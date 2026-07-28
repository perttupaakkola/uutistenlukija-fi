#!/usr/bin/env python3
"""
story_packet.py — Build structured Monica writer packets from scanned articles.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from .category_guard import category_text, contains_token, protect_business_category, protect_tiede_category
    from .source_attribution import normalize_source_url, source_identity_key
except ImportError:  # pragma: no cover - direct script/test execution from pipeline cwd
    from category_guard import category_text, contains_token, protect_business_category, protect_tiede_category
    from source_attribution import normalize_source_url, source_identity_key

_ALLOWED_CATEGORIES = {
    "Kotimaa",
    "Ulkomaat",
    "Talous",
    "Teknologia",
    "Urheilu",
    "Kulttuuri",
    "Tiede",
    "Uutiset",
}

_SOURCE_LABEL_RE = re.compile(r"(?im)^\s*\[(?:lähde|source):[^\]]+\]\s*")
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SOURCE_SPLIT_RE = re.compile(r"\n\s*\n")
_KEYWORD_RE = re.compile(r"[a-z0-9äöå-]{4,}", re.IGNORECASE)

_COMMON_KEYWORDS = {
    "uutinen",
    "yhtiö",
    "yhtiön",
    "yritys",
    "yrityksen",
    "talous",
    "talouden",
    "markkina",
    "markkinat",
    "kasvu",
    "kasvun",
    "liikevaihto",
    "tulos",
    "euro",
    "euroa",
    "prosentti",
    "prosenttia",
    "uutiset",
    "suomi",
    "suomessa",
    "kertoo",
    "sanoo",
    "vuotta",
    "vuoden",
    "päivä",
    "viikon",
    "jälkeen",
    "sitten",
    "asiasta",
    "mukaan",
    "tämä",
    "tuo",
    "sekä",
    "myös",
    "joka",
    "jotka",
}

_BUSINESS_SOURCE_NAMES = {
    "kauppalehti",
    "kauppalehti kl-nyt",
    "taloussanomat",
    "suomen yrittäjät",
}

_BUSINESS_CONTEXT_KEYWORDS = {
    "talous",
    "talouden",
    "yritys",
    "yritykset",
    "yrityksen",
    "yrittäjä",
    "yrittäjät",
    "liikevaihto",
    "tulos",
    "pörssi",
    "osake",
    "markkina",
    "markkinat",
    "rahoitus",
    "investointi",
    "kasvu",
    "vienti",
}


_FOREIGN_TOPIC_TOKENS = {
    "trump",
    "biden",
    "washington",
    "fbi",
    "patel",
    "iran",
    "israel",
    "ukraina",
    "venäjä",
    "latvia",
    "liettua",
    "liettuan",
    "latvian",
    "eurooppa",
    "euroopassa",
    "yhdysvallat",
    "yhdysvaltain",
    "mexico",
    "spanja",
    "unkari",
    "orban",
    "orbán",
}


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _extract_source_provenance(text: str) -> tuple[str, str]:
    lines = (text or "").splitlines()
    if not lines:
        return "", ""
    first_line = lines[0].strip()
    match = re.match(r"\[(?:Lähde|Source):\s*([^\]]+?)\]", first_line, flags=re.IGNORECASE)
    if not match:
        return "", ""
    value = _normalize_ws(match.group(1))
    name, separator, url = value.partition(" | URL: ")
    return _normalize_ws(name), _normalize_ws(url) if separator else ""


def _extract_source_label(text: str) -> str:
    return _extract_source_provenance(text)[0]


def _source_domain(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")


def queue_root() -> Path:
    configured = os.environ.get("MONICA_QUEUE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent / "queues" / "monica"


def ensure_queue_dirs() -> dict[str, Path]:
    root = queue_root()
    paths = {
        "inbox": root / "inbox",
        "outbox": root / "outbox",
        "quarantine": root / "quarantine",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _sanitize_html(text: str) -> str:
    return _normalize_ws(_HTML_RE.sub(" ", html.unescape(text or "")))


def _sanitize_source_block(text: str) -> str:
    text = _normalize_ws(_sanitize_html(text))
    text = _SOURCE_LABEL_RE.sub("", text)
    return text.strip()


def _source_sections(research_text: str) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    current_label = ""
    current_url = ""
    current_lines: list[str] = []

    for line in (research_text or "").splitlines():
        label, source_url = _extract_source_provenance(line)
        if label:
            if current_lines:
                sections.append((current_label, current_url, "\n".join(current_lines).strip()))
            current_label = label
            current_url = source_url
            current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_label, current_url, "\n".join(current_lines).strip()))
    return sections


def _chunk_source_paragraphs(label: str, text: str, source_type: str = "research", source_url: str = "") -> list[dict]:
    paragraphs = [_sanitize_source_block(part) for part in _SOURCE_SPLIT_RE.split(text or "")]
    paragraphs = [part for part in paragraphs if part]
    chunks: list[dict] = []
    current: list[str] = []
    current_words = 0
    target_words = 140

    for paragraph in paragraphs:
        words = len(paragraph.split())
        if current and current_words + words > target_words:
            clean = _normalize_ws(" ".join(current))
            chunks.append(
                {
                    "source": label,
                    "source_url": source_url,
                    "source_domain": _source_domain(source_url),
                    "source_type": source_type,
                    "text": clean,
                    "word_count": len(clean.split()),
                }
            )
            current = []
            current_words = 0
        current.append(paragraph)
        current_words += words

    if current:
        clean = _normalize_ws(" ".join(current))
        chunks.append(
            {
                "source": label,
                "source_url": source_url,
                "source_domain": _source_domain(source_url),
                "source_type": source_type,
                "text": clean,
                "word_count": len(clean.split()),
            }
        )
    return chunks


def _source_words(blocks: list[dict]) -> int:
    return sum(int(block.get("word_count", 0) or 0) for block in blocks)


def _split_research_blocks(research_text: str) -> list[dict]:
    blocks: list[dict] = []
    if not research_text:
        return blocks

    sections = _source_sections(research_text)
    if sections:
        for idx, (label, source_url, section_text) in enumerate(sections, start=1):
            clean_label = label or f"source-{idx}"
            blocks.extend(_chunk_source_paragraphs(clean_label, section_text, source_url=source_url))
        return blocks

    parts = [part.strip() for part in _SOURCE_SPLIT_RE.split(research_text) if part.strip()]
    for idx, part in enumerate(parts, start=1):
        label = _extract_source_label(part) or f"source-{idx}"
        clean = _sanitize_source_block(part)
        if not clean:
            continue
        blocks.append(
            {
                "source": label,
                "source_url": "",
                "source_domain": "",
                "source_type": "research",
                "text": clean,
                "word_count": len(clean.split()),
            }
        )
    return blocks

_TEMPORAL_TOKENS = {
    "maanantai",
    "maanantaina",
    "maanantain",
    "tiistai",
    "tiistaina",
    "tiistain",
    "keskiviikko",
    "keskiviikkona",
    "keskiviikon",
    "torstai",
    "torstaina",
    "torstain",
    "perjantai",
    "perjantaina",
    "perjantain",
    "lauantai",
    "lauantaina",
    "lauantain",
    "sunnuntai",
    "sunnuntaina",
    "sunnuntain",
    "tänään",
    "eilen",
    "huomenna",
}


def _topical_support_tokens(text: str) -> set[str]:
    tokens = _keyword_tokens(text)
    return {token for token in tokens if token not in _COMMON_KEYWORDS and len(token) >= 5}


def _temporal_tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    found: set[str] = set()
    for token in _TEMPORAL_TOKENS:
        if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", lowered):
            found.add(token)
    return found

def _source_group_key(block: dict) -> str:
    source = _normalize_ws(str(block.get("source") or ""))
    if source:
        return source.lower()
    return _normalize_ws(str(block.get("source_type") or "")).lower() or "unknown"


def _has_specific_claim(text: str) -> bool:
    tokens = _topical_support_tokens(text)
    temporal = _temporal_tokens(text)
    return bool(temporal or len(tokens) >= 4 or any(token[:1].isupper() for token in re.findall(r"\b[\wÄÖÅäöå-]{5,}\b", text or "")))


def _supported_source_groups(article: dict, blocks: Iterable[dict]) -> set[str]:
    title = str(article.get("title", "") or "")
    description = str(article.get("description", "") or "")
    claim_text = " ".join(part for part in [title, description] if part)
    title_tokens = _topical_support_tokens(title)
    description_tokens = _topical_support_tokens(description)
    claim_tokens = title_tokens | description_tokens
    temporal_claims = _temporal_tokens(claim_text)
    if len(claim_tokens) < 2 and not temporal_claims:
        return set()
    high_specific_claim = len(claim_tokens) >= 6

    supported: set[str] = set()
    for block in blocks:
        if str(block.get("source_type") or "") in {"description", "rss_description"}:
            continue
        text = _normalize_ws(str(block.get("text", "") or ""))
        if not text:
            continue
        block_tokens = _topical_support_tokens(text)
        title_overlap = title_tokens & block_tokens
        description_overlap = description_tokens & block_tokens
        token_overlap = title_overlap | description_overlap
        block_temporal = _temporal_tokens(text)
        temporal_conflict = bool(temporal_claims and block_temporal and not (temporal_claims & block_temporal))
        if temporal_conflict:
            continue
        required_overlap = 3 if len(title_tokens) >= 4 else 2
        if len(title_overlap) >= required_overlap or (len(description_overlap) >= 2 and len(title_overlap) >= 1):
            supported.add(_source_group_key(block))
            continue
        if temporal_claims:
            if temporal_claims & block_temporal and len(token_overlap) >= 1:
                supported.add(_source_group_key(block))
            continue
        if high_specific_claim and len(token_overlap) >= 1 and any(neg in text.lower() for neg in ("ei kertonut", "ei kerrottu", "ei koske", "ei ollut")):
            continue
        if len(token_overlap) >= required_overlap:
            supported.add(_source_group_key(block))
    return supported


def _filter_topically_supported_sources(article: dict, blocks: list[dict]) -> list[dict]:
    if not blocks:
        return blocks
    supported_groups = _supported_source_groups(article, blocks)
    title = str(article.get("title", "") or "")
    description = str(article.get("description", "") or "")
    claim_text = " ".join(part for part in [title, description] if part)
    title_tokens = _topical_support_tokens(title)
    claim_tokens = _topical_support_tokens(claim_text)
    research_blocks = [block for block in blocks if str(block.get("source_type") or "") not in {"description", "rss_description"}]
    research_words = sum(len(str(block.get("text", "") or "").split()) for block in research_blocks)
    strict_claim = bool(_temporal_tokens(claim_text) or (len(claim_tokens) >= 6 and research_words >= 12))
    if not supported_groups:
        if _is_business_context(article, _keyword_tokens(claim_text)):
            return blocks
        return [] if strict_claim else blocks
    return [block for block in blocks if _source_group_key(block) in supported_groups]


def _fallback_source_blocks(article: dict) -> list[dict]:
    blocks: list[dict] = []
    description = _sanitize_source_block(str(article.get("description", "") or ""))
    if description:
        blocks.append(
            {
                "source": article.get("source", "") or "rss",
                "source_url": article.get("link", ""),
                "source_domain": _source_domain(article.get("link", "")),
                "source_type": "description",
                "text": description,
                "word_count": len(description.split()),
            }
        )
    return blocks


def _keyword_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _KEYWORD_RE.findall((text or "").lower()):
        token = raw.strip("-")
        if len(token) < 4 or token in _COMMON_KEYWORDS:
            continue
        tokens.add(token)
    return tokens


def _keyword_overlap(context_tokens: set[str], text: str) -> tuple[int, int]:
    if not context_tokens:
        return 0, 0
    block_tokens = _keyword_tokens(text)
    overlap_tokens = context_tokens & block_tokens
    strong_overlap = sum(1 for token in overlap_tokens if len(token) >= 6)
    return len(overlap_tokens), strong_overlap


def _is_business_context(article: dict, context_tokens: set[str]) -> bool:
    hint = _normalize_ws(str(article.get("category_hint") or article.get("category") or ""))
    source = _normalize_ws(str(article.get("source") or "")).lower()
    if hint == "Talous" or source in _BUSINESS_SOURCE_NAMES:
        title = str(article.get("title", "") or "")
        description = str(article.get("description", "") or "")
        # Keep the category hint useful, but do not let it override explicit
        # contradictory time markers in fetched sources (for example a
        # Thursday euribor claim backed only by Tuesday source text).
        if _temporal_tokens(title) or _temporal_tokens(description):
            return False
        return True
    return False


def _select_best_sources(article: dict, blocks: Iterable[dict], max_sources: int = 4) -> list[dict]:
    context_tokens = _keyword_tokens(
        " ".join(
            part
            for part in [
                str(article.get("title", "") or ""),
                str(article.get("description", "") or ""),
            ]
            if part
        )
    )
    business_context = _is_business_context(article, context_tokens)

    ranked: list[tuple[tuple[int, int, int, int, int], dict]] = []
    article_source = _normalize_ws(str(article.get("source", "") or ""))

    for block in blocks:
        text = _normalize_ws(str(block.get("text", "") or ""))
        if not text:
            continue

        source = _normalize_ws(str(block.get("source", "") or ""))
        source_type = _normalize_ws(str(block.get("source_type", "") or ""))
        words = len(text.split())
        is_fallback = source_type in {"description", "rss_description"} or source == article_source
        min_words = 8 if is_fallback else 12
        if words < min_words:
            continue

        overlap, strong = _keyword_overlap(context_tokens, text)
        if context_tokens and not is_fallback:
            if overlap < 1:
                continue
            if strong == 0 and overlap < 3:
                if not (business_context and words >= 80):
                    continue

        ranked.append(
            (
                (strong, overlap, 1 if is_fallback else 0, words, len(source)),
                {
                    **block,
                    "text": text,
                    "source": source,
                    "word_count": words,
                    "keyword_overlap": overlap,
                    "strong_overlap": strong,
                },
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict] = []
    seen_text: set[str] = set()
    selected_url_by_identity: dict[str, str] = {}
    for _, block in ranked:
        text = block["text"]
        if text in seen_text:
            continue
        url = normalize_source_url(block.get("source_url"))
        identity = str(block.get("source_identity") or source_identity_key(url))
        if identity and url:
            selected_url = selected_url_by_identity.get(identity)
            if selected_url and selected_url != url:
                continue
            selected_url_by_identity.setdefault(identity, url)
        seen_text.add(text)
        selected.append(block)
        if len(selected) >= max_sources:
            break
    return selected


def _annotate_source_identities(blocks: Iterable[dict]) -> list[dict]:
    """Attach alias-safe identities before source ranking without dropping evidence."""
    annotated: list[dict] = []
    for block in blocks:
        url = normalize_source_url(block.get("source_url"))
        identity = source_identity_key(url)
        annotated.append(
            {
                **block,
                **({"source_identity": identity} if identity else {}),
            }
        )
    return annotated


def _backfill_research_sources(
    selected: list[dict],
    all_blocks: list[dict],
    min_words: int = 80,
    max_sources: int = 4,
) -> list[dict]:
    """Add source-rich research blocks when keyword selection leaves a thin packet.

    Talous candidates from JS/paywalled feeds can pass the pipeline's combined
    source-word check thanks to fetched research, but strict keyword overlap may
    leave Monica with only a tiny RSS-description block. Do not lower gates or
    invent source text; just preserve the longest already-fetched research block
    as packet evidence when the selected packet is still below a usable size.
    """
    if _source_words(selected) >= min_words or len(selected) >= max_sources:
        return selected

    selected_sources = {str(block.get("source", "")).lower() for block in selected if block.get("source")}
    selected_text = " ".join(str(block.get("text", "")) for block in selected)
    selected_url_by_identity: dict[str, str] = {}
    for block in selected:
        url = normalize_source_url(block.get("source_url"))
        identity = str(block.get("source_identity") or source_identity_key(url))
        if identity and url:
            selected_url_by_identity.setdefault(identity, url)

    def _candidate_score(block: dict) -> tuple[int, int, int]:
        source = str(block.get("source", "")).lower()
        source_match = int(bool(source and source in selected_sources))
        overlap, strong = _keyword_overlap(_keyword_tokens(selected_text), str(block.get("text", "")))
        return (source_match, strong + overlap, int(block.get("word_count", 0) or 0))

    seen_text = {block.get("text", "") for block in selected}
    candidates = []
    for block in all_blocks:
        if block.get("source_type") != "research":
            continue
        if block.get("text") in seen_text:
            continue
        if int(block.get("word_count", 0) or 0) < 40:
            continue
        url = normalize_source_url(block.get("source_url"))
        identity = str(block.get("source_identity") or source_identity_key(url))
        if (
            identity
            and identity in selected_url_by_identity
            and selected_url_by_identity[identity] != url
        ):
            continue
        score = _candidate_score(block)
        if score[1] == 0:
            continue
        candidates.append(block)
    candidates.sort(key=_candidate_score, reverse=True)

    for block in candidates:
        selected.append(block)
        seen_text.add(block.get("text", ""))
        url = normalize_source_url(block.get("source_url"))
        identity = str(block.get("source_identity") or source_identity_key(url))
        if identity and url:
            selected_url_by_identity.setdefault(identity, url)
        if _source_words(selected) >= min_words or len(selected) >= max_sources:
            break
    return selected


def _source_diagnostics(all_blocks: list[dict], selected_blocks: list[dict]) -> dict:
    selected_words = _source_words(selected_blocks)
    return {
        "candidate_blocks": len(all_blocks),
        "candidate_source_words": _source_words(all_blocks),
        "selected_blocks": len(selected_blocks),
        "selected_source_words": selected_words,
        "zero_source_packet": selected_words == 0,
        "low_source_packet": 0 < selected_words < 80,
        "candidate_sources": [block.get("source", "") for block in all_blocks if block.get("source")],
        "selected_sources": [block.get("source", "") for block in selected_blocks if block.get("source")],
    }


def _hydrate_selected_source_provenance(article: dict, blocks: list[dict]) -> None:
    """Attach the seed URL only to blocks that actually name the seed source."""
    seed_name = _normalize_ws(str(article.get("source") or "")).casefold()
    seed_url = _normalize_ws(str(article.get("link") or ""))
    for block in blocks:
        if block.get("source_url") or _normalize_ws(str(block.get("source") or "")).casefold() != seed_name:
            continue
        block["source_url"] = seed_url
        block["source_domain"] = _source_domain(seed_url)


def selected_source_provenance_error(packet: dict) -> str:
    """Return why selected supporting blocks cannot form trustworthy attribution."""
    blocks = packet.get("clean_source_blocks") or []
    if not blocks:
        return ""
    by_name: dict[str, str] = {}
    by_url: dict[str, str] = {}
    for block in blocks:
        name = _normalize_ws(str(block.get("source") or ""))
        url = _normalize_ws(str(block.get("source_url") or ""))
        domain = _normalize_ws(str(block.get("source_domain") or "")) or _source_domain(url)
        if not name or not url or not domain:
            return "selected source block is missing name/url/domain; seed provenance cannot substitute"
        if _source_domain(url) != domain:
            return "selected source URL/domain mismatch"
        name_key = name.casefold()
        url_key = url.casefold()
        identity = source_identity_key(url)
        if not identity:
            return "selected source URL is invalid"
        if name_key in by_name and by_name[name_key] != identity:
            return "selected source name maps to multiple URL/domain tuples"
        if url_key in by_url and by_url[url_key] != name_key:
            return "selected source URL maps to multiple names"
        by_name[name_key] = identity
        by_url[url_key] = name_key
    return ""


def _primary_selected_source(blocks: list[dict]) -> dict:
    totals: dict[str, int] = {}
    display: dict[str, dict] = {}
    for block in blocks:
        url = _normalize_ws(str(block.get("source_url") or ""))
        key = source_identity_key(url) or url.casefold()
        totals[key] = totals.get(key, 0) + int(block.get("word_count", 0) or 0)
        display.setdefault(
            key,
            {
                "name": _normalize_ws(str(block.get("source") or "")),
                "url": url,
                "domain": _normalize_ws(str(block.get("source_domain") or "")),
            },
        )
    return display[max(totals, key=totals.get)] if totals else {}


def _infer_category(article: dict, selected_blocks: list[dict]) -> str:
    title_and_desc = " ".join(
        part
        for part in [
            str(article.get("title", "") or ""),
            str(article.get("description", "") or ""),
        ]
        if part
    ).lower()
    hint = _normalize_ws(
        str(
            article.get("category_hint")
            or article.get("category")
            or article.get("_guessed_category")
            or ""
        )
    )
    full_text = category_text(article, " ".join(block.get("text", "") for block in selected_blocks))

    business_category = protect_business_category(hint or "Kotimaa", full_text)
    if business_category == "Talous":
        return business_category

    # Trusted section hints should survive broad foreign-token matching for
    # business/market items. Otherwise a Talous feed item about Wall Street,
    # oil, China, Russia, or Iran gets counted as Ulkomaat and worsens the
    # category-mix drift. Generic/local hints can still be overridden.
    if hint in _ALLOWED_CATEGORIES and hint not in {"Kotimaa", "Uutiset"}:
        return protect_tiede_category(
            hint,
            category_text(article, " ".join(block.get("text", "") for block in selected_blocks)),
        )

    if any(contains_token(title_and_desc, token) for token in _FOREIGN_TOPIC_TOKENS):
        return "Ulkomaat"

    if hint in _ALLOWED_CATEGORIES:
        return protect_tiede_category(
            hint,
            category_text(article, " ".join(block.get("text", "") for block in selected_blocks)),
        )

    combined = " ".join(block.get("text", "") for block in selected_blocks).lower()
    if any(contains_token(combined, token) for token in _FOREIGN_TOPIC_TOKENS):
        return "Ulkomaat"
    return "Kotimaa"


def _story_confidence(blocks: list[dict], article: dict) -> float:
    source_score = min(0.35, len(blocks) * 0.10)
    word_count = sum(b.get("word_count", 0) for b in blocks)
    word_score = min(0.35, word_count / 600)
    meta_score = 0.15 if _normalize_ws(str(article.get("title", ""))) else 0.0
    meta_score += 0.10 if _normalize_ws(str(article.get("description", ""))) else 0.0
    overlap_bonus = 0.0
    if blocks:
        overlap_bonus = min(
            0.10,
            max(
                (block.get("keyword_overlap", 0) * 0.02) + (block.get("strong_overlap", 0) * 0.03)
                for block in blocks
            ),
        )
    return round(min(0.98, source_score + word_score + meta_score + overlap_bonus), 2)


def build_story_packet(article: dict) -> dict:
    title = _normalize_ws(article.get("title", ""))
    description = _sanitize_source_block(article.get("description", ""))
    seed = article.get("link") or f"{title}|{description}"
    digest = hashlib.sha1(str(seed).encode("utf-8", errors="ignore")).hexdigest()[:10]
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    packet_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{digest}"

    research_text = article.get("research_text") or article.get("research") or ""
    all_blocks = _split_research_blocks(str(research_text))
    all_blocks.extend(_fallback_source_blocks(article))
    all_blocks = _annotate_source_identities(all_blocks)
    supported_blocks = _filter_topically_supported_sources(article, all_blocks)
    selected_blocks = _select_best_sources(article, supported_blocks)
    selected_blocks = _backfill_research_sources(selected_blocks, all_blocks)
    _hydrate_selected_source_provenance(article, selected_blocks)
    source_text = "\n\n".join(block["text"] for block in selected_blocks)
    source_diagnostics = _source_diagnostics(all_blocks, selected_blocks)
    provenance_error = selected_source_provenance_error({"clean_source_blocks": selected_blocks})
    selected_source = _primary_selected_source(selected_blocks) if not provenance_error else {}

    source_names = list(dict.fromkeys(block.get("source", "") for block in selected_blocks if block.get("source")))
    source_urls: list[str] = []
    seen_source_identities: set[str] = set()
    for block in selected_blocks:
        url = _normalize_ws(str(block.get("source_url") or ""))
        identity = source_identity_key(url)
        if not url or not identity or identity in seen_source_identities:
            continue
        seen_source_identities.add(identity)
        source_urls.append(url)
    source_domains = list(dict.fromkeys(block.get("source_domain", "") for block in selected_blocks if block.get("source_domain")))

    inferred_category = _infer_category(article, selected_blocks)
    packet = {
        "packet_id": packet_id,
        "created_at": created_at,
        "headline_seed": title,
        "description_seed": description,
        "link": article.get("link", ""),
        "source": article.get("source", ""),
        "source_names": source_names,
        "source_urls": source_urls,
        "source_domains": source_domains,
        "selected_source": selected_source,
        "selected_source_provenance_error": provenance_error,
        "category_hint": inferred_category,
        "category": inferred_category,
        "story_confidence": _story_confidence(selected_blocks, article),
        "language_mix": [article.get("lang", "fi") or "fi"],
        "facts": {
            "who": [],
            "what": [title] if title else [],
            "where": [],
            "when": [],
            "why": [],
            "consequences": [],
        },
        "clean_source_blocks": selected_blocks,
        "source_text": source_text,
        "source_diagnostics": source_diagnostics,
        "source_selection_outcome": (
            "provenance_invalid" if provenance_error
            else "zero_source_packet" if source_diagnostics["zero_source_packet"]
            else "low_source_packet" if source_diagnostics["low_source_packet"]
            else "usable_source_packet"
        ),
        "editor_brief": (
            "Kirjoita tästä yksi julkaistava, luonnollinen suomenkielinen uutisartikkeli. "
            "Älä toista lähdetekstiä, älä vuoda lähdelabelia, älä jätä englanninkielisiä otsikkoja tai kappaleita."
        ),
        "article_snapshot": {
            "title": title,
            "description": description,
            "category_hint": article.get("category_hint", ""),
            "research_source": article.get("research_source", ""),
        },
    }
    return packet


def save_story_packet(packet: dict, queue: str = "inbox") -> Path:
    dirs = ensure_queue_dirs()
    target_dir = dirs.get(queue, dirs["inbox"])
    packet_id = packet.get("packet_id") or packet.get("packet", {}).get("packet_id") or "unknown"
    path = target_dir / f"{packet_id}.json"
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_packet(packet: dict, box: str = "inbox") -> Path:
    """Backward-compatible alias used by monica_writer.py."""
    return save_story_packet(packet, queue=box)
