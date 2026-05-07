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
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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


def _extract_source_label(text: str) -> str:
    lines = (text or "").splitlines()
    if not lines:
        return ""
    first_line = lines[0].strip()
    match = re.match(r"\[(?:Lähde|Source):\s*([^\]]+?)\]", first_line, flags=re.IGNORECASE)
    if not match:
        return ""
    return _normalize_ws(match.group(1))


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


def _source_sections(research_text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_label = ""
    current_lines: list[str] = []

    for line in (research_text or "").splitlines():
        label = _extract_source_label(line)
        if label:
            if current_lines:
                sections.append((current_label, "\n".join(current_lines).strip()))
            current_label = label
            current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_label, "\n".join(current_lines).strip()))
    return sections


def _chunk_source_paragraphs(label: str, text: str, source_type: str = "research") -> list[dict]:
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
                "source_type": source_type,
                "text": clean,
                "word_count": len(clean.split()),
            }
        )
    return chunks


def _split_research_blocks(research_text: str) -> list[dict]:
    blocks: list[dict] = []
    if not research_text:
        return blocks

    sections = _source_sections(research_text)
    if sections:
        for idx, (label, section_text) in enumerate(sections, start=1):
            clean_label = label or f"source-{idx}"
            blocks.extend(_chunk_source_paragraphs(clean_label, section_text))
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
                "source_type": "research",
                "text": clean,
                "word_count": len(clean.split()),
            }
        )
    return blocks

def _fallback_source_blocks(article: dict) -> list[dict]:
    blocks: list[dict] = []
    description = _sanitize_source_block(str(article.get("description", "") or ""))
    if description:
        blocks.append(
            {
                "source": article.get("source", "") or "rss",
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
        return True
    return bool(context_tokens & _BUSINESS_CONTEXT_KEYWORDS)


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
            if strong == 0 and overlap < 3:
                if not (business_context and words >= 80):
                    continue
            if overlap < 1:
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
    for _, block in ranked:
        text = block["text"]
        if text in seen_text:
            continue
        seen_text.add(text)
        selected.append(block)
        if len(selected) >= max_sources:
            break
    return selected


def _infer_category(article: dict, selected_blocks: list[dict]) -> str:
    title_and_desc = " ".join(
        part
        for part in [
            str(article.get("title", "") or ""),
            str(article.get("description", "") or ""),
        ]
        if part
    ).lower()
    hint = _normalize_ws(str(article.get("category_hint") or article.get("category") or ""))

    # Trusted section hints should survive broad foreign-token matching for
    # business/market items. Otherwise a Talous feed item about Wall Street,
    # oil, China, Russia, or Iran gets counted as Ulkomaat and worsens the
    # category-mix drift. Generic/local hints can still be overridden.
    if hint in _ALLOWED_CATEGORIES and hint not in {"Kotimaa", "Uutiset"}:
        return hint

    if any(token in title_and_desc for token in _FOREIGN_TOPIC_TOKENS):
        return "Ulkomaat"

    if hint in _ALLOWED_CATEGORIES:
        return hint

    combined = " ".join(block.get("text", "") for block in selected_blocks).lower()
    if any(token in combined for token in _FOREIGN_TOPIC_TOKENS):
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
    selected_blocks = _select_best_sources(article, all_blocks)
    source_text = "\n\n".join(block["text"] for block in selected_blocks)

    inferred_category = _infer_category(article, selected_blocks)
    packet = {
        "packet_id": packet_id,
        "created_at": created_at,
        "headline_seed": title,
        "description_seed": description,
        "link": article.get("link", ""),
        "source": article.get("source", ""),
        "source_names": [block.get("source", "") for block in selected_blocks if block.get("source")],
        "source_urls": [article.get("link", "")] if article.get("link") else [],
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
