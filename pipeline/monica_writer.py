#!/usr/bin/env python3
"""
monica_writer.py — Final Finnish article writing through Monica via OpenClaw.

This replaces the legacy API-first public rewriter lane.
The host-side pipeline is expected to have `openclaw` installed and Monica
configured as an agent using GPT-5.4 monthly tokens.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from .category_guard import category_text, protect_business_category, protect_tiede_category
    from .quarantine import save_writer_quarantine
    from .source_attribution import (
        build_source_attributions,
        normalize_source_usage,
        normalize_source_url,
    )
    from .story_packet import build_story_packet, ensure_queue_dirs, save_packet, selected_source_provenance_error
except ImportError:  # pragma: no cover - direct script/test execution from pipeline cwd
    from category_guard import category_text, protect_business_category, protect_tiede_category
    from quarantine import save_writer_quarantine
    from source_attribution import (
        build_source_attributions,
        normalize_source_usage,
        normalize_source_url,
    )
    from story_packet import build_story_packet, ensure_queue_dirs, save_packet, selected_source_provenance_error

ALLOWED_CATEGORIES = {
    "Kotimaa",
    "Ulkomaat",
    "Talous",
    "Teknologia",
    "Urheilu",
    "Kulttuuri",
    "Tiede",
    "Uutiset",
}

DEFAULT_MONICA_AGENT = os.environ.get("MONICA_OPENCLAW_AGENT", "monica")
DEFAULT_OPENCLAW_CMD = os.environ.get("MONICA_OPENCLAW_CMD", "openclaw")
DEFAULT_TIMEOUT_SEC = int(os.environ.get("MONICA_WRITER_TIMEOUT_SEC", "360"))
MONICA_DISPATCH_TIMING_LOG = Path(os.environ.get(
    "MONICA_DISPATCH_TIMING_LOG",
    str(Path(__file__).resolve().parent / "logs" / "monica-dispatch-timing.jsonl"),
))
MIN_CONTENT_WORDS = 250
MIN_LEAD_WORDS = 30
SOURCE_BACKED_REPAIR_WORDS = 300
SOURCE_BACKED_REPAIR_BLOCKS = 3
SOURCE_BACKED_NEAR_MISS_REPAIR_WORDS = 250
SOURCE_BACKED_NEAR_MISS_REPAIR_BLOCKS = 3
SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE = 0.85
SOURCE_BACKED_NEAR_MISS_MIN_WORDS = 200
SOURCE_BACKED_REPAIR_MIN_TARGET_WORDS = 280
SOURCE_BACKED_REPAIR_MAX_TARGET_WORDS = 420
SOURCE_BACKED_REPAIR_MIN_SAFE_WORDS = 280
SOURCE_BACKED_TALOUS_MICRO_REPAIR_WORDS = 250
SOURCE_BACKED_TALOUS_MICRO_REPAIR_BLOCKS = 3
SOURCE_BACKED_TALOUS_MICRO_REPAIR_MIN_WORDS = 200

OPENCLAW_CANDIDATES = (
    "/home/pertt/.openclaw/bin/openclaw",
    "/home/pertt/.openclaw/tools/node-v22.22.0/bin/openclaw",
    "/usr/local/bin/openclaw",
    "/usr/bin/openclaw",
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

WRITER_SCHEMA = {
    "type": "object",
    "required": [
        "packet_id",
        "title",
        "summary",
        "content",
        "category",
        "tags",
        "summary_bullets",
        "content_type",
        "editorial_reviewed",
        "confidence",
        "journalist_note",
        "source_usage",
    ],
    "source_usage": {
        "one_row_per_distinct_clean_source_url": True,
        "row": {
            "source_url": "exact selected URL",
            "used": "boolean",
            "dependent_claims": "non-empty string list when used; [] when unused",
        },
        "same_article_aliases": "at most one alias may be used",
    },
    "optional_status": "INSUFFICIENT_CONFIDENCE",
}


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _balanced_json_candidates(text: str) -> list[str]:
    """Return balanced top-level JSON object candidates found in arbitrary text.

    OpenClaw/agent output can include progress lines or other brace-containing
    text before/after the actual model JSON. A simple first-"{" to last-"}"
    slice turns those responses into one invalid blob. This scanner keeps the
    fallback local and conservative: it only emits balanced object spans while
    respecting JSON string escaping.
    """
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for idx, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : idx + 1])
                start = None

    return candidates


def _extract_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty Monica response")

    candidates = [text]
    for fenced in _JSON_BLOCK_RE.finditer(text):
        candidates.insert(0, fenced.group(1).strip())

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.extend(_balanced_json_candidates(text))

    seen: set[str] = set()

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # Some provider/plugin warnings are appended before a valid JSON object,
        # while stdout capture can also truncate the final newline or closing brace.
        # Keep this fail-closed: only accept candidates with exactly one missing
        # final object brace and no non-whitespace tail after the inferred object.
        stripped = candidate.rstrip()
        if stripped.endswith('}'):
            continue
        repair_start = stripped.find("{")
        if repair_start == -1:
            continue
        repair_candidate = stripped[repair_start:]
        balance = 0
        in_string = False
        escape = False
        for ch in repair_candidate:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                balance += 1
            elif ch == "}":
                balance -= 1
                if balance < 0:
                    break
        if balance != 1 or in_string or escape:
            continue
        try:
            data = json.loads(repair_candidate + "}")
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise ValueError("Monica response did not contain valid JSON object")


def _normalize_tags(tags) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in tags:
        tag = _normalize_ws(str(item)).lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= 5:
            break
    return out


def _normalize_summary_bullets(value, fallback_summary: str = "") -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    items = value if isinstance(value, list) else []
    for item in items:
        text = _normalize_ws(str(item)).lstrip("-*• ")
        if len(text) < 8:
            continue
        if text in seen:
            continue
        seen.add(text)
        bullets.append(text)
        if len(bullets) >= 4:
            break

    if len(bullets) < 2 and fallback_summary:
        for part in re.split(r"[.!?]\s+", fallback_summary):
            text = _normalize_ws(part)
            if len(text) < 12 or text in seen:
                continue
            seen.add(text)
            bullets.append(text)
            if len(bullets) >= 3:
                break
    return bullets[:4]


MIN_PROSE_PARAGRAPHS = 4
MIN_H2_HEADINGS = 2
MIN_PROSE_PARAGRAPH_WORDS = 5
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}(?:\s+|$)")
_MARKDOWN_H2_CANDIDATE_RE = re.compile(r"^\s{0,3}##(?!#)(?:[ \t]|$)")
_MARKDOWN_H2_RE = re.compile(r"^\s{0,3}##(?!#)[ \t]+\S")
_STRUCTURE_ISSUE_PREFIX = "structure contract:"


def _content_structure_counts(content: str) -> dict[str, int]:
    """Count substantive blank-line prose blocks and non-empty H2 headings.

    A sequence of prose lines separated only by single newlines is one prose
    paragraph, not several. A block may begin with an H2 and continue with its
    prose on the next line; the heading itself is never counted as prose.
    Short non-heading blocks are reported as trivial instead of satisfying the
    prose floor, and a bare ``##`` is reported instead of counting as an H2.
    """
    normalized = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return {
            "prose_paragraphs": 0,
            "h2_headings": 0,
            "trivial_prose_paragraphs": 0,
            "empty_h2_headings": 0,
        }

    prose_paragraphs = 0
    h2_headings = 0
    trivial_prose_paragraphs = 0
    empty_h2_headings = 0
    for block in re.split(r"\n[ \t]*\n+", normalized):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        h2_candidates = [line for line in lines if _MARKDOWN_H2_CANDIDATE_RE.match(line)]
        h2_headings += sum(1 for line in h2_candidates if _MARKDOWN_H2_RE.match(line))
        empty_h2_headings += sum(1 for line in h2_candidates if not _MARKDOWN_H2_RE.match(line))
        prose_lines = [line for line in lines if not _MARKDOWN_HEADING_RE.match(line)]
        if prose_lines:
            prose_word_count = len(" ".join(prose_lines).split())
            if prose_word_count >= MIN_PROSE_PARAGRAPH_WORDS:
                prose_paragraphs += 1
            else:
                trivial_prose_paragraphs += 1
    return {
        "prose_paragraphs": prose_paragraphs,
        "h2_headings": h2_headings,
        "trivial_prose_paragraphs": trivial_prose_paragraphs,
        "empty_h2_headings": empty_h2_headings,
    }


def _has_structure_issue(issues: list[str]) -> bool:
    return any(str(issue).startswith(_STRUCTURE_ISSUE_PREFIX) for issue in issues)


def _basic_payload_issues(payload: dict, packet: dict | None = None) -> list[str]:
    issues: list[str] = []
    required = WRITER_SCHEMA["required"]
    missing = [key for key in required if key not in payload]
    if missing:
        issues.append("missing keys: " + ", ".join(missing))
        return issues

    title = _normalize_ws(str(payload.get("title", "")))
    summary = _normalize_ws(str(payload.get("summary", "")))
    content = str(payload.get("content", "") or "").strip()
    category = _normalize_ws(str(payload.get("category", "")))
    tags = _normalize_tags(payload.get("tags", []))
    bullets = _normalize_summary_bullets(payload.get("summary_bullets", []), summary)

    if not title:
        issues.append("empty title")
    if not summary:
        issues.append("empty summary")
    if not content:
        issues.append("empty content")
    if category not in ALLOWED_CATEGORIES:
        issues.append(f"invalid category: {category or 'empty'}")
    if len(content.split()) < MIN_CONTENT_WORDS:
        issues.append(f"content too short: {len(content.split())} words")
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if paragraphs and len(paragraphs[0].split()) < MIN_LEAD_WORDS:
        issues.append(f"lead paragraph too short: {len(paragraphs[0].split())} words")
    structure = _content_structure_counts(content)
    if structure["prose_paragraphs"] < MIN_PROSE_PARAGRAPHS:
        issues.append(
            f"{_STRUCTURE_ISSUE_PREFIX} prose paragraphs "
            f"{structure['prose_paragraphs']} < {MIN_PROSE_PARAGRAPHS}"
        )
    if structure["h2_headings"] < MIN_H2_HEADINGS:
        issues.append(
            f"{_STRUCTURE_ISSUE_PREFIX} H2 headings "
            f"{structure['h2_headings']} < {MIN_H2_HEADINGS}"
        )
    if structure["empty_h2_headings"]:
        issues.append(
            f"{_STRUCTURE_ISSUE_PREFIX} empty H2 headings "
            f"{structure['empty_h2_headings']}"
        )
    if structure["trivial_prose_paragraphs"]:
        issues.append(
            f"{_STRUCTURE_ISSUE_PREFIX} trivial prose paragraphs "
            f"{structure['trivial_prose_paragraphs']} below "
            f"{MIN_PROSE_PARAGRAPH_WORDS} words"
        )
    if len(tags) < 2:
        issues.append("not enough tags")
    if len(bullets) < 2:
        issues.append("not enough summary bullets")
    if packet is not None:
        _, usage_issues = normalize_source_usage(
            packet,
            payload.get("source_usage"),
            require_complete=True,
        )
        issues.extend(f"source_usage: {issue}" for issue in usage_issues)
    return issues


def _source_block_words(block: dict[str, Any]) -> int:
    text_word_count = len(str(block.get("text") or "").split())
    try:
        declared_word_count = int(block.get("word_count") or 0)
    except (TypeError, ValueError):
        declared_word_count = 0
    return max(declared_word_count, text_word_count)


def _packet_source_words(packet: dict) -> int:
    blocks = packet.get("clean_source_blocks") or []
    if isinstance(blocks, list) and blocks:
        total = sum(_source_block_words(block) for block in blocks if isinstance(block, dict))
        if total:
            return total
    text = str(packet.get("source_text") or "")
    if text.strip():
        return len(text.split())
    return 0


def _packet_source_blocks(packet: dict) -> int:
    blocks = packet.get("clean_source_blocks") or []
    if isinstance(blocks, list):
        count = sum(1 for block in blocks if isinstance(block, dict) and _normalize_ws(str(block.get("text") or "")))
        if count:
            return count
    text = str(packet.get("source_text") or "")
    if not text.strip():
        return 0
    return len([part for part in re.split(r"\n\s*\n|\n---\n", text) if _normalize_ws(part)])


def _content_word_count(payload: dict) -> int:
    return len(str(payload.get("content") or "").split())


def _content_lead_word_count(payload: dict) -> int:
    content = str(payload.get("content") or "").strip()
    if not content:
        return 0
    first_paragraph = next((p.strip() for p in content.split("\n\n") if p.strip()), "")
    return len(first_paragraph.split())


def _is_payload_under_final_length_floor(payload: dict) -> bool:
    return _content_word_count(payload) < MIN_CONTENT_WORDS or _content_lead_word_count(payload) < MIN_LEAD_WORDS


def _packet_story_confidence(packet: dict) -> float:
    for key in ("story_confidence", "confidence"):
        try:
            value = float(packet.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value:
            return value
    return 0.0


def _has_length_issue(issues: list[str]) -> bool:
    joined = "; ".join(issues).lower()
    return "content too short" in joined or "lead paragraph too short" in joined


def _packet_category(packet: dict) -> str:
    return str(packet.get("category") or packet.get("category_hint") or "")


def _is_source_backed_talous_micro_near_miss(packet: dict, payload: dict, issues: list[str]) -> bool:
    """Strict OPE-72 lane for thin-but-source-backed Talous near misses.

    This is intentionally narrower than the generic near-miss path: it only
    applies to Talous, requires three selected source blocks and high story
    confidence, and still preserves the 250-word/30-word final floors.
    """
    if _packet_category(packet) != "Talous":
        return False
    if not _has_length_issue(issues):
        return False
    if _packet_story_confidence(packet) < SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE:
        return False
    if _packet_source_words(packet) < SOURCE_BACKED_TALOUS_MICRO_REPAIR_WORDS:
        return False
    if _packet_source_blocks(packet) < SOURCE_BACKED_TALOUS_MICRO_REPAIR_BLOCKS:
        return False
    return _content_word_count(payload) >= SOURCE_BACKED_TALOUS_MICRO_REPAIR_MIN_WORDS and _is_payload_under_final_length_floor(payload)


def _is_source_backed_near_miss(packet: dict, payload: dict, issues: list[str]) -> bool:
    if _is_source_backed_talous_micro_near_miss(packet, payload, issues):
        return True
    if not _has_length_issue(issues):
        return False
    if _packet_story_confidence(packet) < SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE:
        return False
    if _packet_source_words(packet) < SOURCE_BACKED_NEAR_MISS_REPAIR_WORDS:
        return False
    if _packet_source_blocks(packet) < SOURCE_BACKED_NEAR_MISS_REPAIR_BLOCKS:
        return False
    word_count = _content_word_count(payload)
    return (
        word_count >= SOURCE_BACKED_NEAR_MISS_MIN_WORDS
        or (word_count >= MIN_CONTENT_WORDS - 50 and _content_lead_word_count(payload) < MIN_LEAD_WORDS)
    ) and _is_payload_under_final_length_floor(payload)


def _is_source_backed_repair_candidate(packet: dict, issues: list[str]) -> bool:
    if not _has_length_issue(issues):
        return False
    if _packet_source_blocks(packet) < SOURCE_BACKED_REPAIR_BLOCKS:
        return False
    return (
        _packet_source_words(packet) >= SOURCE_BACKED_REPAIR_WORDS
        or (
            _packet_source_words(packet) >= SOURCE_BACKED_NEAR_MISS_REPAIR_WORDS
            and _packet_story_confidence(packet) >= SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE
        )
        or (
            _packet_category(packet) == "Talous"
            and _packet_source_words(packet) >= SOURCE_BACKED_TALOUS_MICRO_REPAIR_WORDS
            and _packet_source_blocks(packet) >= SOURCE_BACKED_TALOUS_MICRO_REPAIR_BLOCKS
            and _packet_story_confidence(packet) >= SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE
        )
    )


def _source_block_ids_for_repair(packet: dict) -> list[str]:
    blocks = packet.get("clean_source_blocks")
    if not isinstance(blocks, list):
        return []
    ids: list[str] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        text = _normalize_ws(str(block.get("text") or ""))
        if not text:
            continue
        source = _normalize_ws(str(block.get("source") or block.get("name") or f"block-{index + 1}"))
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
        ids.append(f"{index + 1}:{source}:{digest}")
    return ids


def _near_miss_repair_metadata(packet: dict, initial_payload: dict, final_payload: dict, final_issues: list[str]) -> dict[str, Any]:
    pre_words = _content_word_count(initial_payload)
    post_words = _content_word_count(final_payload)
    source_words = _packet_source_words(packet)
    source_blocks = _packet_source_blocks(packet)
    recovered = not final_issues and post_words >= MIN_CONTENT_WORDS
    repair_result = "published" if recovered else "still_short" if post_words < MIN_CONTENT_WORDS else "quality_gate_rejected"
    metadata = {
        "repair_attempt": "source_backed_near_short",
        "repair_attempted_at": datetime.now(timezone.utc).isoformat(),
        "repair_trigger": f"pre_repair_word_count={pre_words}; selected_source_words={source_words}; selected_source_blocks={source_blocks}",
        "pre_repair_word_count": pre_words,
        "pre_repair_lead_word_count": len(str(initial_payload.get("content") or "").split("\n", 1)[0].split()),
        "post_repair_word_count": post_words,
        "post_repair_lead_word_count": len(str(final_payload.get("content") or "").split("\n", 1)[0].split()),
        "selected_source_words_at_repair": source_words,
        "selected_source_blocks_at_repair": source_blocks,
        # Backward-compatible aliases used by earlier OPE-42 comments/tests.
        "source_words": source_words,
        "source_blocks": source_blocks,
        "repair_added_word_count": max(0, post_words - pre_words),
        "repair_result": repair_result,
        "repair_rejection_reason": "; ".join(final_issues) if final_issues else "",
        "source_block_ids_used_for_repair": _source_block_ids_for_repair(packet),
        "final_issues": list(final_issues),
        "recovered": recovered,
    }
    return metadata


def _source_backed_near_short_hint(packet: dict) -> str:
    source_words = _packet_source_words(packet)
    source_blocks = _packet_source_blocks(packet)
    if (
        source_words >= SOURCE_BACKED_NEAR_MISS_REPAIR_WORDS
        and source_blocks >= SOURCE_BACKED_NEAR_MISS_REPAIR_BLOCKS
        and _packet_story_confidence(packet) >= SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE
    ):
        return (
            f"\nSource-backed near-short rule: this packet has {source_words} source words across "
            f"{source_blocks} source blocks. Do not fail closed only because a first draft lands "
            "just below 250 words; write or repair a compact 250-320 word article using only "
            "those sourced facts. Return INSUFFICIENT_CONFIDENCE only for contradiction or truly "
            "missing core facts."
        )
    return ""


def _build_prompt(packet: dict) -> str:
    schema_text = json.dumps(WRITER_SCHEMA, ensure_ascii=False, indent=2)
    packet_text = json.dumps(packet, ensure_ascii=False, indent=2)
    source_repair_hint = _source_backed_near_short_hint(packet)
    return f"""You are Monica, the final Finnish writer/editor for uutistenlukija.fi.

Write exactly one publication-quality Finnish news article from the structured packet below.
Return ONLY one JSON object. No markdown fences, no commentary.

Hard rules:
- Language: neutral, natural standard Finnish
- No English title or English body paragraphs unless a very short direct quote absolutely requires it
- No source labels in public copy (never output 'Lähde:', 'Source:', 'Continue reading', 'Alkuperäinen artikkeli')
- No duplicated opener, no repeated paragraphs, no generic AI ending
- No invented facts
- `source_usage` must contain exactly one row for every distinct `clean_source_blocks[].source_url`
- Mark a row `used:true` only when the public article depends on at least one claim from it, and list those claims in `dependent_claims`
- Mark a row `used:false` only when no public claim depends on it; then `dependent_claims` must be exactly `[]`
- Same-article URL aliases represent one source: at most one alias may be `used:true`
- If the evidence is too weak or contradictory, return: {{"packet_id":"{packet['packet_id']}","status":"INSUFFICIENT_CONFIDENCE","reason":"short reason"}}
- Write at least 250 words and usually 280–420 words; if the packet cannot support that without filler or invention, return INSUFFICIENT_CONFIDENCE{source_repair_hint}
- The first paragraph must be at least 30 words and summarize the verified core of the story
- Build at least four substantive non-heading prose paragraphs separated by blank lines; every counted paragraph must contain at least {MIN_PROSE_PARAGRAPH_WORDS} words
- Include at least two Markdown H2 (`##`) subheadings with specific visible heading text inside `content`; a bare `##` is invalid

Required JSON schema:
{schema_text}

Story packet:
{packet_text}
"""


def _build_repair_prompt(packet: dict, broken_payload: dict, issues: list[str]) -> str:
    source_words = _packet_source_words(packet)
    source_blocks = _packet_source_blocks(packet)
    near_short_repair = any("source_backed_writer_shortfall" in issue for issue in issues)
    source_backed = _is_source_backed_repair_candidate(packet, issues) or (
        near_short_repair
        and source_blocks >= SOURCE_BACKED_NEAR_MISS_REPAIR_BLOCKS
        and (
            source_words >= SOURCE_BACKED_NEAR_MISS_REPAIR_WORDS
            or (
                _packet_category(packet) == "Talous"
                and source_words >= SOURCE_BACKED_TALOUS_MICRO_REPAIR_WORDS
                and source_blocks >= SOURCE_BACKED_TALOUS_MICRO_REPAIR_BLOCKS
            )
        )
        and _packet_story_confidence(packet) >= SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE
    )
    source_backed_rules = ""
    if source_backed:
        source_backed_rules = f"""
Source-backed repair mode:
- The packet has {source_words} source words across {source_blocks} source blocks, so a short draft is a repair target, not an automatic failure.
- The repaired article MUST be at least 250 Finnish words and the first paragraph MUST be at least 30 words. Target {SOURCE_BACKED_REPAIR_MIN_TARGET_WORDS}–{SOURCE_BACKED_REPAIR_MAX_TARGET_WORDS} factual Finnish words using only details present in the packet.
- For high-confidence source-backed near-misses with at least {SOURCE_BACKED_NEAR_MISS_REPAIR_WORDS} source words, {SOURCE_BACKED_NEAR_MISS_REPAIR_BLOCKS} source blocks, confidence >= {SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE}, and {SOURCE_BACKED_NEAR_MISS_MIN_WORDS}–249 output words or a too-short lead paragraph with at least {MIN_CONTENT_WORDS - 50} total words, treat the short output as a writer shortfall: make one final expansion pass using concrete selected-source facts from every available block.
- For Talous only, the same final expansion requirement also applies to 200–249 word near-misses with at least {SOURCE_BACKED_TALOUS_MICRO_REPAIR_WORDS} selected source words, {SOURCE_BACKED_TALOUS_MICRO_REPAIR_BLOCKS} source blocks, and confidence >= {SOURCE_BACKED_NEAR_MISS_MIN_CONFIDENCE}. This exists for narrow Suomen Yrittäjät / Finanssiala packets that are source-backed but selected-source constrained.
- Before returning, count the words in `content` and in the first paragraph. If content is under 250 words or the lead is under 30 words, either add source-backed detail from the packet until it is at least {SOURCE_BACKED_REPAIR_MIN_SAFE_WORDS} words with a 30+ word lead, or return INSUFFICIENT_CONFIDENCE with reason `source_backed_writer_shortfall_unrepairable`.
- Treat 200–249 source-backed output words and 1–29 word lead paragraphs on otherwise near-complete drafts as failed repairs. Do not return a near-miss; continue revising until the article is safely above both floors or explicitly return `source_backed_writer_shortfall_unrepairable`.
- Build 4–6 substantive paragraphs of at least {MIN_PROSE_PARAGRAPH_WORDS} words each plus at least two non-empty, specific H2 subheadings.
- Use available source blocks to add concrete context: actors, figures/timing, cause, consequence, and what happens next when available.
- Reorganize or expand only claims present in the selected source blocks; do not introduce an actor, date, cause, consequence, reaction, or attribution absent from those blocks.
- Do not stop at 200–249 words. A 209-word, 211-word, or 244–248-word repair is still invalid and will be quarantined.
- Do not pad with generic economy commentary, advice, sentiment, or invented market context.
"""
    return f"""Fix the article JSON below and return ONLY a corrected JSON object.
Do not add commentary.

Problems to fix:
- {'; '.join(issues)}

Repair rules:
- Return INSUFFICIENT_CONFIDENCE if the original packet cannot support at least 250 factual Finnish words without filler or invention.
- Otherwise expand the article to 280–420 words, make the first paragraph at least 30 words, and include at least two H2 subheadings.
- Build at least four substantive non-heading prose paragraphs of at least {MIN_PROSE_PARAGRAPH_WORDS} words each, separated by blank lines. Single-newline-only pseudo-structure and shorter padding blocks do not satisfy the contract.
- Every H2 must contain specific visible heading text after `##`; a bare `##` is invalid.
- Return one `source_usage` row for every distinct selected URL. `used:true` requires explicit dependent claims; `used:false` requires `dependent_claims=[]`.
- Collapse same-article aliases by marking at most one alias `used:true`.
{source_backed_rules}
Original packet source evidence:
- source_words: {source_words}
- source_blocks: {source_blocks}

Original packet:
{json.dumps(packet, ensure_ascii=False, indent=2)}

Broken article JSON:
{json.dumps(broken_payload, ensure_ascii=False, indent=2)}
"""


def _resolve_openclaw_base_cmd() -> list[str]:
    raw = os.environ.get("MONICA_OPENCLAW_CMD", DEFAULT_OPENCLAW_CMD)
    parts = shlex.split(raw)
    executable = parts[0]

    if os.path.isabs(executable) and Path(executable).exists():
        return parts

    resolved = shutil.which(executable)
    if resolved:
        return [resolved, *parts[1:]]

    for candidate in OPENCLAW_CANDIDATES:
        if Path(candidate).exists():
            return [candidate, *parts[1:]]

    return parts


def _openclaw_command(prompt: str, *, force_local: bool | None = None, session_id: str | None = None) -> list[str]:
    base = _resolve_openclaw_base_cmd()
    cmd = [*base, "agent", "--agent", os.environ.get("MONICA_OPENCLAW_AGENT", DEFAULT_MONICA_AGENT)]
    if force_local is None:
        # Default to embedded-local dispatch because gateway task admission can
        # stall before the first event. An explicit session id still keeps every
        # packet out of the durable `agent:monica:main` transcript. Operators can
        # set MONICA_OPENCLAW_LOCAL=0 to force the gateway path after it is healthy.
        use_local = os.environ.get("MONICA_OPENCLAW_LOCAL", "1").lower() not in {"0", "false", "no"}
    else:
        use_local = force_local

    # Never honor a process-wide fixed session id: unattended workers may
    # overlap, and sharing one transcript reintroduces both context pollution
    # and cross-packet collisions. Explicit ids are reserved for the caller's
    # bounded retry; otherwise every invocation gets a fresh session.
    explicit_session = session_id or f"monica-pipeline-{uuid.uuid4()}"
    if use_local:
        cmd.append("--local")
    # Keep every packet isolated in both gateway and embedded-local modes.
    # Local mode without an explicit id silently falls back to the durable
    # `agent:monica:main` transcript and eventually recreates the context
    # overflow problem this path was designed to avoid.
    cmd.extend(["--session-id", explicit_session])
    cmd.extend(["--message", prompt])
    return cmd


def _looks_like_context_overflow(text: str) -> bool:
    lowered = (text or "").lower()
    return "context overflow" in lowered or "prompt too large for the model" in lowered


def _dispatch_reason_code(error: BaseException | str) -> str:
    text = str(error or "").lower()
    if isinstance(error, FileNotFoundError) or "no such file or directory" in text or "checked path and candidates" in text:
        return "cli_missing"
    if isinstance(error, (subprocess.TimeoutExpired, TimeoutError)) or "timed out" in text or "timeout" in text:
        return "timeout"
    if _looks_like_context_overflow(text):
        return "context_overflow"
    return "dispatch_failed"


def _redacted_dispatch_metadata(cmd: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "mode": "gateway",
        "agent": os.environ.get("MONICA_OPENCLAW_AGENT", DEFAULT_MONICA_AGENT),
        "executable": Path(cmd[0]).name if cmd else "",
        "session_id_hash": "",
    }
    if "--local" in cmd:
        metadata["mode"] = "local"
    if "--session-id" in cmd:
        try:
            session_id = cmd[cmd.index("--session-id") + 1]
            metadata["session_id_hash"] = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
        except (IndexError, ValueError):
            metadata["session_id_hash"] = "unavailable"
    return metadata


def _safe_process_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    try:
        snapshot["load1"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    try:
        count = 0
        for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
            text = cmdline.read_text(encoding="utf-8", errors="ignore").replace("\x00", " ").lower()
            if "openclaw" in text or "hermes" in text or "codex" in text:
                count += 1
        snapshot["openclaw_related_processes"] = count
    except Exception:
        snapshot["openclaw_related_processes"] = None
    return snapshot


def _append_dispatch_timing(record: dict[str, Any]) -> None:
    try:
        MONICA_DISPATCH_TIMING_LOG.parent.mkdir(parents=True, exist_ok=True)
        with MONICA_DISPATCH_TIMING_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Dispatch logging must never block article handling.
        return


def _run_openclaw_command(cmd: list[str]) -> str:
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    metadata = _redacted_dispatch_metadata(cmd)
    timeout_sec = int(os.environ.get("MONICA_WRITER_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC)))
    outcome = "unknown"
    reason_code = ""
    timed_out = False
    returncode: int | None = None
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        timed_out = True
        reason_code = "timeout"
        stdout = e.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if stdout.strip():
            try:
                _extract_json_object(stdout)
                outcome = "success_timeout_stdout_salvaged"
                return stdout.strip()
            except ValueError:
                pass
        outcome = "timeout"
        raise RuntimeError(f"Monica writer command timed out after {e.timeout} seconds") from e
    except FileNotFoundError as e:
        outcome = "cli_missing"
        reason_code = "cli_missing"
        searched = ", ".join(OPENCLAW_CANDIDATES)
        raise RuntimeError(
            f"Monica writer command failed: {e}. Checked PATH and candidates: {searched}"
        ) from e
    except Exception:
        outcome = "dispatch_exception"
        reason_code = "dispatch_failed"
        raise
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        if outcome != "unknown":
            _append_dispatch_timing({
                "schema": "uutistenlukija.monica_dispatch_timing.v1",
                "started_at": started_at.isoformat(),
                "duration_ms": duration_ms,
                "timeout_sec": timeout_sec,
                "timed_out": timed_out,
                "outcome": outcome,
                "reason_code": reason_code,
                **metadata,
                **_safe_process_snapshot(),
            })
    returncode = result.returncode
    try:
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or f"exit {result.returncode}"
            outcome = "nonzero_exit"
            reason_code = "dispatch_failed"
            raise RuntimeError(f"Monica writer command failed: {detail}")
        text = (result.stdout or "").strip()
        if not text:
            outcome = "empty_output"
            reason_code = "dispatch_failed"
            raise RuntimeError("Monica writer returned empty output")
        outcome = "success"
        return text
    finally:
        _append_dispatch_timing({
            "schema": "uutistenlukija.monica_dispatch_timing.v1",
            "started_at": started_at.isoformat(),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "timeout_sec": timeout_sec,
            "timed_out": timed_out,
            "outcome": outcome,
            "reason_code": reason_code,
            "returncode": returncode,
            **metadata,
            **_safe_process_snapshot(),
        })


def _run_monica(prompt: str) -> str:
    # Use one explicit, unique session per attempt in both gateway and local
    # mode. Reusing a durable Monica session (or resetting it through `/reset`)
    # polluted the writer lane until every retry overflowed.
    text = _run_openclaw_command(_openclaw_command(prompt))
    if _looks_like_context_overflow(text):
        print("[monica]   context overflow from Monica session; retrying once with fresh explicit session")
        text = _run_openclaw_command(_openclaw_command(prompt, session_id=f"monica-pipeline-retry-{uuid.uuid4()}"))
    if _looks_like_context_overflow(text):
        raise RuntimeError("Monica writer context overflow after fresh-session retry")
    return text


def _persist_source_usage(packet: dict, payload: dict) -> list[dict[str, Any]]:
    """Persist the validated per-URL contract into the eventual outbox packet."""
    rows, issues = normalize_source_usage(
        packet,
        payload.get("source_usage"),
        require_complete=True,
    )
    if issues:
        raise ValueError("invalid source_usage: " + "; ".join(issues))
    packet["source_usage"] = rows
    packet["source_usage_contract"] = "v1"
    return rows


def _canonical_public_category(value: Any) -> str:
    raw = _normalize_ws(str(value or "")).casefold()
    return next(
        (
            category
            for category in ALLOWED_CATEGORIES
            if category != "Uutiset" and category.casefold() == raw
        ),
        "",
    )


def _synchronize_packet_category(
    packet: dict,
    original: dict,
    payload: dict,
    article: dict,
) -> str:
    """Synchronize stale packet guards only from four unanimous canonical signals."""
    categories = (
        _canonical_public_category(original.get("_guessed_category")),
        _canonical_public_category(article.get("_guessed_category")),
        _canonical_public_category(payload.get("category")),
        _canonical_public_category(article.get("category")),
    )
    if any(not category for category in categories) or len(set(categories)) != 1:
        return ""
    category = categories[0]
    packet["category"] = category
    packet["category_hint"] = category
    return category


def _merge_article(original: dict, packet: dict, payload: dict) -> dict:
    title = _normalize_ws(payload.get("title", ""))
    summary = _normalize_ws(payload.get("summary", ""))
    content = str(payload.get("content", "")).strip()
    category = _normalize_ws(payload.get("category", ""))
    packet_category = _normalize_ws(str(packet.get("category") or packet.get("category_hint") or ""))
    original_category = _normalize_ws(str(original.get("category_hint") or original.get("category") or ""))
    guessed_category = _normalize_ws(str(original.get("_guessed_category") or ""))
    if packet_category == "Ulkomaat" and (original_category == "Talous" or guessed_category == "Talous"):
        category = "Talous"
    elif packet_category == "Kotimaa" and category == "Ulkomaat" and guessed_category == "Ulkomaat":
        category = "Ulkomaat"
    elif packet_category in ALLOWED_CATEGORIES:
        category = packet_category
    elif original_category in ALLOWED_CATEGORIES:
        category = original_category
    elif guessed_category in ALLOWED_CATEGORIES:
        category = guessed_category
    elif category not in ALLOWED_CATEGORIES:
        category = "Kotimaa"
    category = protect_tiede_category(
        category,
        " ".join(
            [
                category_text(original),
                category_text(packet),
                category_text(payload),
            ]
        ),
    )
    category = protect_business_category(
        category,
        " ".join(
            [
                category_text(original),
                category_text(packet),
                category_text(payload),
            ]
        ),
    )

    tags = _normalize_tags(payload.get("tags", []))
    bullets = _normalize_summary_bullets(payload.get("summary_bullets", []), summary)
    note = _normalize_ws(str(payload.get("journalist_note", ""))) or " "

    word_count = len(content.split())
    merged = dict(original)
    selected_source = packet.get("selected_source") or {}
    source_attributions = build_source_attributions(
        packet,
        packet.get("source_usage") if isinstance(packet.get("source_usage"), list) else [],
    )
    merged.update(
        {
            "title": title,
            "description": summary,
            "summary": summary,
            "content": content,
            "category": category,
            "tags": tags,
            "summary_bullets": bullets,
            "key_points": bullets,
            "content_type": _normalize_ws(str(payload.get("content_type", "article"))) or "article",
            "editorial_reviewed": bool(payload.get("editorial_reviewed", True)),
            "journalist_note": note,
            "source_text": packet.get("source_text", ""),
            "writer_backend": "monica",
            "writer_confidence": float(payload.get("confidence", 0.0) or 0.0),
            "degraded_mode": False,
            "monica_packet_id": packet.get("packet_id", ""),
        }
    )
    if source_attributions:
        merged["source_attributions"] = source_attributions
        used_urls = {row["url"] for row in source_attributions}
        selected_url = normalize_source_url(selected_source.get("url"))
        if not selected_url or selected_url not in used_urls:
            primary = source_attributions[0]
            selected_source = {
                "name": primary["name"],
                "url": primary["url"],
                "domain": (urlsplit(primary["url"]).hostname or "").removeprefix("www."),
            }
    if selected_source:
        merged.update(
            {
                "source": selected_source["name"],
                "link": selected_source["url"],
                "source_url": selected_source["url"],
                "source_domain": selected_source["domain"],
            }
        )
    return merged


def rewrite_articles(articles: list[dict]) -> list[dict]:
    ensure_queue_dirs()
    written: list[dict] = []

    for idx, article in enumerate(articles):
        title = (article.get("title") or "?")[:80]
        print(f"[monica] ({idx + 1}/{len(articles)}) {title}")
        packet = build_story_packet(article)
        save_packet(packet, box="inbox")

        provenance_error = selected_source_provenance_error(packet)
        if provenance_error:
            save_writer_quarantine(
                packet,
                "selected_source_provenance_invalid",
                extra={"reason_code": "selected_source_provenance_invalid", "error": provenance_error},
            )
            print(f"[monica]   quarantine: selected_source_provenance_invalid ({provenance_error})")
            continue

        raw = ""
        try:
            raw = _run_monica(_build_prompt(packet))
            try:
                payload = _extract_json_object(raw)
            except ValueError as e:
                save_writer_quarantine(packet, "dispatch_error", raw_response=raw, extra={"reason_code": "json_parse_failed", "error": str(e), "stage": "initial_parse"})
                print(f"[monica]   quarantine: dispatch_error ({e})")
                continue

            if payload.get("status") == "INSUFFICIENT_CONFIDENCE":
                save_writer_quarantine(packet, payload.get("reason", "insufficient_confidence"), raw_response=raw, extra={"status": payload.get("status")})
                print(f"[monica]   quarantine: insufficient confidence")
                continue

            repair_metadata = None
            issues = _basic_payload_issues(payload, packet)
            if issues:
                print(f"[monica]   repair pass: {'; '.join(issues)}")
                repaired_raw = _run_monica(_build_repair_prompt(packet, payload, issues))
                try:
                    payload = _extract_json_object(repaired_raw)
                except ValueError as e:
                    save_writer_quarantine(packet, "dispatch_error", raw_response=repaired_raw, extra={"reason_code": "json_parse_failed", "error": str(e), "stage": "repair_parse", "initial_payload": payload, "initial_issues": issues})
                    print(f"[monica]   quarantine: dispatch_error ({e})")
                    continue
                raw = repaired_raw
                issues = _basic_payload_issues(payload, packet)

                if _is_source_backed_near_miss(packet, payload, issues):
                    near_miss_issues = list(issues) + ["source_backed_writer_shortfall: final expansion required"]
                    near_miss_payload = payload
                    print(f"[monica]   near-miss repair pass: {'; '.join(near_miss_issues)}")
                    repaired_raw = _run_monica(_build_repair_prompt(packet, near_miss_payload, near_miss_issues))
                    try:
                        payload = _extract_json_object(repaired_raw)
                    except ValueError as e:
                        save_writer_quarantine(packet, "dispatch_error", raw_response=repaired_raw, extra={"reason_code": "json_parse_failed", "error": str(e), "stage": "near_miss_repair_parse", "initial_payload": near_miss_payload, "initial_issues": near_miss_issues})
                        print(f"[monica]   quarantine: dispatch_error ({e})")
                        continue
                    raw = repaired_raw
                    issues = _basic_payload_issues(payload, packet)
                    repair_metadata = _near_miss_repair_metadata(packet, near_miss_payload, payload, issues)
                    if (
                        repair_metadata["repair_added_word_count"] == 0
                        and _is_source_backed_talous_micro_near_miss(packet, payload, issues)
                    ):
                        retry_issues = list(issues) + [
                            "source_backed_talous_zero_word_retry: previous repair added 0 words and article remains under final length floor"
                        ]
                        print(f"[monica]   Talous zero-word retry pass: {'; '.join(retry_issues)}")
                        retry_raw = _run_monica(_build_repair_prompt(packet, payload, retry_issues))
                        try:
                            payload = _extract_json_object(retry_raw)
                        except ValueError as e:
                            save_writer_quarantine(packet, "dispatch_error", raw_response=retry_raw, extra={"reason_code": "json_parse_failed", "error": str(e), "stage": "talous_zero_word_retry_parse", "initial_payload": payload, "initial_issues": retry_issues})
                            print(f"[monica]   quarantine: dispatch_error ({e})")
                            continue
                        raw = retry_raw
                        issues = _basic_payload_issues(payload, packet)
                        repair_metadata = _near_miss_repair_metadata(packet, near_miss_payload, payload, issues)
                        repair_metadata["repair_retry"] = "talous_zero_word_short_retry"
                        repair_metadata["repair_retry_reason"] = "previous repair added 0 words and remained under final length floor"

            if issues:
                reason = "schema_invalid"
                extra = {"issues": issues, "payload": payload}
                if repair_metadata:
                    extra.update(repair_metadata)
                if _is_source_backed_repair_candidate(packet, issues) and _is_payload_under_final_length_floor(payload):
                    reason = "source_backed_writer_shortfall_unrepairable"
                    extra.update({
                        "reason_code": "source_backed_writer_shortfall_unrepairable",
                        "source_words": _packet_source_words(packet),
                        "source_blocks": _packet_source_blocks(packet),
                        "final_word_count": _content_word_count(payload),
                        "final_lead_word_count": _content_lead_word_count(payload),
                    })
                elif _has_structure_issue(issues):
                    structure = _content_structure_counts(str(payload.get("content") or ""))
                    reason = "writer_structure_contract_unmet"
                    extra.update({
                        "reason_code": "writer_structure_contract_unmet",
                        "required_prose_paragraphs": MIN_PROSE_PARAGRAPHS,
                        "required_min_prose_words": MIN_PROSE_PARAGRAPH_WORDS,
                        "required_h2_headings": MIN_H2_HEADINGS,
                        "final_prose_paragraphs": structure["prose_paragraphs"],
                        "final_trivial_prose_paragraphs": structure["trivial_prose_paragraphs"],
                        "final_h2_headings": structure["h2_headings"],
                        "final_empty_h2_headings": structure["empty_h2_headings"],
                    })
                save_writer_quarantine(packet, reason, raw_response=raw, extra=extra)
                print(f"[monica]   quarantine: {reason} ({'; '.join(issues)})")
                continue

            _persist_source_usage(packet, payload)
            written_article = _merge_article(article, packet, payload)
            _synchronize_packet_category(packet, article, payload, written_article)
            outbox_packet = {"packet_id": packet["packet_id"], "packet": packet, "response": payload, "raw_response": raw}
            if repair_metadata:
                outbox_packet["repair"] = repair_metadata
                written_article["monica_repair"] = repair_metadata
            save_packet(outbox_packet, box="outbox")
            written.append(written_article)
            print(f"[monica]   ok: {written_article.get('title','')[:70]}")

        except Exception as e:
            save_writer_quarantine(packet, "dispatch_error", raw_response=raw, extra={"reason_code": _dispatch_reason_code(e), "error": str(e)})
            print(f"[monica]   quarantine: dispatch_error ({e})")

    if written:
        print(f"[monica] completed: {len(written)}/{len(articles)} articles")
    else:
        print(f"[monica] completed: 0/{len(articles)} articles")
    return written
