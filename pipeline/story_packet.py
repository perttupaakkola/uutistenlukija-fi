#!/usr/bin/env python3
"""
story_packet.py — Build structured Monica writer packets from scanned articles.

The goal is to keep raw source soup out of the final writing prompt.
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
_BOILERPLATE_PATTERNS = [
    re.compile(r"(?im)^\s*(?:lähde|source):\s*.+$"),
    re.compile(r"(?im)^\s*continue reading.*$"),
    re.compile(r"(?im)^\s*read more.*$"),
    re.compile(r"(?im)^\s*liity yrittäjiin.*$"),
    re.compile(r"(?im)^\s*mainos.*$"),
    re.compile(r"(?im)^\s*advertisement.*$"),
    re.compile(r"(?im)^\s*newsletter.*$"),
    re.compile(r"(?im)^\s*sign up.*$"),
]
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def queue_root() -> Path:
    configured = os.environ.get("MONICA_QUEUE_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "queues" / "monica"


def ensure_queue_dirs() -> dict[str, Path]:
    root = queue_root()
    paths = {
        "root": root,
        "inbox": root / "inbox",
        "outbox": root / "outbox",
        "quarantine": root / "quarantine",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _strip_html(text: str) -> str:
    return _normalize_ws(_HTML_RE.sub(" ", html.unescape(text or "")))


def _sanitize_source_block(text: str) -> str:
    cleaned = text or ""
    cleaned = _SOURCE_LABEL_RE.sub("", cleaned)
    cleaned = _strip_html(cleaned)
    for pattern in _BOILERPLATE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:Reuters|AP|AFP|BBC)\s+reported\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:This article was originally published .*?)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" -\n\t")


def _extract_source_label(block: str) -> str:
    m = re.match(r"\s*\[(?:Lähde|Source):\s*([^\]]+?)\]\s*", block, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _split_research_blocks(research_text: str) -> list[dict]:
    blocks: list[dict] = []
    raw = (research_text or "").strip()
    if not raw:
        return blocks

    for idx, part in enumerate(re.split(r"\n\n---\n\n", raw)):
        part = part.strip()
        if not part:
            continue
        label = _extract_source_label(part) or f"source-{idx + 1}"
        text = _sanitize_source_block(part)
        if not text:
            continue
        blocks.append(
            {
                "source": label,
                "url": "",
                "text": text,
                "word_count": len(text.split()),
            }
        )
    return blocks


def _fallback_source_blocks(article: dict) -> list[dict]:
    blocks: list[dict] = []
    description = _sanitize_source_block(article.get("description", ""))
    if description:
        blocks.append(
            {
                "source": article.get("source", "rss"),
                "url": article.get("link", ""),
                "text": description,
                "word_count": len(description.split()),
            }
        )
    return blocks


def _select_best_sources(blocks: Iterable[dict], max_sources: int = 4) -> list[dict]:
    ranked = sorted(blocks, key=lambda b: b.get("word_count", 0), reverse=True)
    selected: list[dict] = []
    seen_text: set[str] = set()
    for block in ranked:
        text = _normalize_ws(block.get("text", "")).lower()
        if not text or len(text.split()) < 25:
            continue
        if text in seen_text:
            continue
        seen_text.add(text)
        selected.append(block)
        if len(selected) >= max_sources:
            break
    return selected


def _infer_category(article: dict) -> str:
    hint = (article.get("category") or article.get("category_hint") or "").strip()
    if hint in _ALLOWED_CATEGORIES:
        return hint
    title = (article.get("title") or "").lower()
    if any(token in title for token in ("trump", "iran", "ukraina", "venäjä", "usa", "china", "yhdysvallat")):
        return "Ulkomaat"
    return "Kotimaa"


def _story_confidence(blocks: list[dict], article: dict) -> float:
    source_score = min(0.35, len(blocks) * 0.10)
    word_count = sum(b.get("word_count", 0) for b in blocks)
    word_score = min(0.35, word_count / 1200)
    desc_score = 0.10 if article.get("description") else 0.0
    link_score = 0.10 if article.get("link") else 0.0
    score = 0.25 + source_score + word_score + desc_score + link_score
    return round(max(0.0, min(0.95, score)), 2)


def build_story_packet(article: dict, max_sources: int = 4) -> dict:
    title = _normalize_ws(article.get("title", ""))
    description = _sanitize_source_block(article.get("description", ""))
    research = article.get("research", "") or ""
    blocks = _split_research_blocks(research)
    if not blocks:
        blocks = _fallback_source_blocks(article)
    blocks = _select_best_sources(blocks, max_sources=max_sources)

    source_text = "\n\n".join(block["text"] for block in blocks).strip()
    category = _infer_category(article)
    seed = f"{article.get('link','')}|{title}|{category}"
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:10]
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    packet_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{digest}"

    packet = {
        "packet_id": packet_id,
        "created_at": created_at,
        "headline_seed": title,
        "description_seed": description,
        "link": article.get("link", ""),
        "source": article.get("source", ""),
        "source_urls": [u for u in [article.get("link", "")] if u],
        "source_names": [b.get("source", "") for b in blocks if b.get("source")],
        "category_hint": category,
        "story_confidence": _story_confidence(blocks, article),
        "language_mix": [article.get("lang", "fi") or "fi"],
        "facts": {
            "who": [],
            "what": [title] if title else [],
            "where": [],
            "when": [],
            "why": [],
            "consequences": [],
        },
        "clean_source_blocks": blocks,
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


def save_packet(packet: dict, box: str = "inbox") -> Path:
    paths = ensure_queue_dirs()
    target_dir = paths.get(box, paths["inbox"])
    packet_id = packet.get("packet_id") or packet.get("packet", {}).get("packet_id") or "unknown"
    path = target_dir / f"{packet_id}.json"
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
