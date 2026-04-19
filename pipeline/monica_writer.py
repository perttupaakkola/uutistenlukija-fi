#!/usr/bin/env python3
"""
monica_writer.py — Final Finnish article writing through Monica via OpenClaw.

This replaces the legacy API-first public rewriter lane.
The host-side pipeline is expected to have `openclaw` installed and Monica
configured as an agent using GPT-5.4 monthly tokens.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from quarantine import save_writer_quarantine
from story_packet import build_story_packet, ensure_queue_dirs, save_packet

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
DEFAULT_TIMEOUT_SEC = int(os.environ.get("MONICA_WRITER_TIMEOUT_SEC", "240"))
MIN_CONTENT_WORDS = 140

OPENCLAW_CANDIDATES = (
    "/home/pertt/.openclaw/tools/node-v22.22.0/bin/openclaw",
    "/usr/local/bin/openclaw",
    "/usr/bin/openclaw",
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
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
    ],
    "optional_status": "INSUFFICIENT_CONFIDENCE",
}


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _extract_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty Monica response")

    candidates = [text]
    fenced = _JSON_BLOCK_RE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise ValueError("Monica response did not contain valid JSON")


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


def _basic_payload_issues(payload: dict) -> list[str]:
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
    if len(tags) < 2:
        issues.append("not enough tags")
    if len(bullets) < 2:
        issues.append("not enough summary bullets")
    return issues


def _build_prompt(packet: dict) -> str:
    schema_text = json.dumps(WRITER_SCHEMA, ensure_ascii=False, indent=2)
    packet_text = json.dumps(packet, ensure_ascii=False, indent=2)
    return f"""You are Monica, the final Finnish writer/editor for uutistenlukija.fi.

Write exactly one publication-quality Finnish news article from the structured packet below.
Return ONLY one JSON object. No markdown fences, no commentary.

Hard rules:
- Language: neutral, natural standard Finnish
- No English title or English body paragraphs unless a very short direct quote absolutely requires it
- No source labels in public copy (never output 'Lähde:', 'Source:', 'Continue reading', 'Alkuperäinen artikkeli')
- No duplicated opener, no repeated paragraphs, no generic AI ending
- No invented facts
- If the evidence is too weak or contradictory, return: {{"packet_id":"{packet['packet_id']}","status":"INSUFFICIENT_CONFIDENCE","reason":"short reason"}}
- Target roughly 160 to 320 words when the evidence is limited, longer only when the packet clearly supports it
- If content is over 180 words, include at least two H2 subheadings inside `content`

Required JSON schema:
{schema_text}

Story packet:
{packet_text}
"""


def _build_repair_prompt(packet: dict, broken_payload: dict, issues: list[str]) -> str:
    return f"""Fix the article JSON below and return ONLY a corrected JSON object.
Do not add commentary.

Problems to fix:
- {'; '.join(issues)}

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


def _openclaw_command(prompt: str) -> list[str]:
    base = _resolve_openclaw_base_cmd()
    cmd = [*base, "agent", "--agent", os.environ.get("MONICA_OPENCLAW_AGENT", DEFAULT_MONICA_AGENT)]
    use_local = os.environ.get("MONICA_OPENCLAW_LOCAL", "1").lower() not in {"0", "false", "no"}
    if use_local:
        cmd.append("--local")
    cmd.extend(["--message", prompt])
    return cmd


def _run_monica(prompt: str) -> str:
    cmd = _openclaw_command(prompt)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("MONICA_WRITER_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC))),
            check=False,
        )
    except FileNotFoundError as e:
        searched = ", ".join(OPENCLAW_CANDIDATES)
        raise RuntimeError(
            f"Monica writer command failed: {e}. Checked PATH and candidates: {searched}"
        ) from e
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit {result.returncode}"
        raise RuntimeError(f"Monica writer command failed: {detail}")
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("Monica writer returned empty output")
    return text


def _merge_article(original: dict, packet: dict, payload: dict) -> dict:
    title = _normalize_ws(payload.get("title", ""))
    summary = _normalize_ws(payload.get("summary", ""))
    content = str(payload.get("content", "")).strip()
    category = _normalize_ws(payload.get("category", ""))
    if category not in ALLOWED_CATEGORIES:
        category = packet.get("category_hint", "Kotimaa")

    tags = _normalize_tags(payload.get("tags", []))
    bullets = _normalize_summary_bullets(payload.get("summary_bullets", []), summary)
    note = _normalize_ws(str(payload.get("journalist_note", ""))) or " "

    word_count = len(content.split())
    merged = dict(original)
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
            "degraded_mode": MIN_CONTENT_WORDS <= word_count < 250,
            "monica_packet_id": packet.get("packet_id", ""),
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

        try:
            raw = _run_monica(_build_prompt(packet))
            payload = _extract_json_object(raw)
            if payload.get("status") == "INSUFFICIENT_CONFIDENCE":
                save_writer_quarantine(packet, payload.get("reason", "insufficient_confidence"), raw_response=raw, extra={"status": payload.get("status")})
                print(f"[monica]   quarantine: insufficient confidence")
                continue

            issues = _basic_payload_issues(payload)
            if issues:
                print(f"[monica]   repair pass: {'; '.join(issues)}")
                repaired_raw = _run_monica(_build_repair_prompt(packet, payload, issues))
                payload = _extract_json_object(repaired_raw)
                raw = repaired_raw
                issues = _basic_payload_issues(payload)

            if issues:
                save_writer_quarantine(packet, "schema_invalid", raw_response=raw, extra={"issues": issues, "payload": payload})
                print(f"[monica]   quarantine: schema_invalid ({'; '.join(issues)})")
                continue

            written_article = _merge_article(article, packet, payload)
            save_packet({"packet_id": packet["packet_id"], "packet": packet, "response": payload, "raw_response": raw}, box="outbox")
            written.append(written_article)
            print(f"[monica]   ok: {written_article.get('title','')[:70]}")

        except Exception as e:
            save_writer_quarantine(packet, "dispatch_error", raw_response="", extra={"error": str(e)})
            print(f"[monica]   quarantine: dispatch_error ({e})")

    if written:
        print(f"[monica] completed: {len(written)}/{len(articles)} articles")
    else:
        print(f"[monica] completed: 0/{len(articles)} articles")
    return written
