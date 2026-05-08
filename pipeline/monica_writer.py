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
import uuid
from pathlib import Path
from typing import Any

try:
    from .quarantine import save_writer_quarantine
    from .story_packet import build_story_packet, ensure_queue_dirs, save_packet
except ImportError:  # pragma: no cover - direct script/test execution from pipeline cwd
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
MIN_CONTENT_WORDS = 250
MIN_LEAD_WORDS = 30
SOURCE_BACKED_REPAIR_WORDS = 300
SOURCE_BACKED_REPAIR_BLOCKS = 2
SOURCE_BACKED_REPAIR_MIN_TARGET_WORDS = 280
SOURCE_BACKED_REPAIR_MAX_TARGET_WORDS = 420
SOURCE_BACKED_REPAIR_MIN_SAFE_WORDS = 260

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
    ],
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
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if paragraphs and len(paragraphs[0].split()) < MIN_LEAD_WORDS:
        issues.append(f"lead paragraph too short: {len(paragraphs[0].split())} words")
    if len(tags) < 2:
        issues.append("not enough tags")
    if len(bullets) < 2:
        issues.append("not enough summary bullets")
    return issues


def _source_block_words(block: dict[str, Any]) -> int:
    try:
        return int(block.get("word_count") or 0)
    except (TypeError, ValueError):
        return len(str(block.get("text") or "").split())


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


def _is_source_backed_repair_candidate(packet: dict, issues: list[str]) -> bool:
    joined = "; ".join(issues).lower()
    has_length_issue = "content too short" in joined or "lead paragraph too short" in joined
    if not has_length_issue:
        return False
    return _packet_source_words(packet) >= SOURCE_BACKED_REPAIR_WORDS and _packet_source_blocks(packet) >= SOURCE_BACKED_REPAIR_BLOCKS


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
- Write at least 250 words and usually 280–420 words; if the packet cannot support that without filler or invention, return INSUFFICIENT_CONFIDENCE
- The first paragraph must be at least 30 words and summarize the verified core of the story
- Include at least two H2 subheadings inside `content`

Required JSON schema:
{schema_text}

Story packet:
{packet_text}
"""


def _build_repair_prompt(packet: dict, broken_payload: dict, issues: list[str]) -> str:
    source_words = _packet_source_words(packet)
    source_blocks = _packet_source_blocks(packet)
    source_backed = _is_source_backed_repair_candidate(packet, issues)
    source_backed_rules = ""
    if source_backed:
        source_backed_rules = f"""
Source-backed repair mode:
- The packet has {source_words} source words across {source_blocks} source blocks, so a short draft is a repair target, not an automatic failure.
- The repaired article MUST be at least 250 Finnish words. Target {SOURCE_BACKED_REPAIR_MIN_TARGET_WORDS}–{SOURCE_BACKED_REPAIR_MAX_TARGET_WORDS} factual Finnish words using only details present in the packet.
- Before returning, count the words in `content`. If it is under 250 words, either add source-backed detail from the packet until it is at least {SOURCE_BACKED_REPAIR_MIN_SAFE_WORDS} words, or return INSUFFICIENT_CONFIDENCE.
- Build 4–6 concise paragraphs plus at least two H2 subheadings.
- Use each source block to add concrete context: actors, figures/timing, cause, consequence, and what happens next when available.
- Do not stop at 240–249 words. A 244–248 word repair is still invalid and will be quarantined.
- Do not pad with generic economy commentary, advice, sentiment, or invented market context.
"""
    return f"""Fix the article JSON below and return ONLY a corrected JSON object.
Do not add commentary.

Problems to fix:
- {'; '.join(issues)}

Repair rules:
- Return INSUFFICIENT_CONFIDENCE if the original packet cannot support at least 250 factual Finnish words without filler or invention.
- Otherwise expand the article to 280–420 words, make the first paragraph at least 30 words, and include at least two H2 subheadings.
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
        # Default to a fresh one-shot gateway dispatch. The old implicit gateway
        # path reused `agent:monica:main`, so unattended article prompts
        # accumulated in one durable transcript until every worker hit context
        # overflow. A unique explicit session keeps each packet isolated while
        # still using the normal OpenClaw gateway/provider setup.
        use_local = os.environ.get("MONICA_OPENCLAW_LOCAL", "0").lower() not in {"0", "false", "no"}
    else:
        use_local = force_local

    explicit_session = session_id or os.environ.get("MONICA_OPENCLAW_SESSION_ID")
    if not explicit_session:
        explicit_session = f"monica-pipeline-{uuid.uuid4()}"
    if use_local:
        cmd.append("--local")
    else:
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


def _run_openclaw_command(cmd: list[str]) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("MONICA_WRITER_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC))),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Monica writer command timed out after {e.timeout} seconds") from e
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


def _run_monica(prompt: str) -> str:
    # Use one explicit, unique Gateway session per attempt. Reusing a durable
    # Monica session (or resetting it through `/reset`) polluted the writer lane
    # until every retry overflowed. A second unique session is the safest small
    # recovery: it bypasses the bad transcript without sending extra reset turns.
    text = _run_openclaw_command(_openclaw_command(prompt))
    if _looks_like_context_overflow(text):
        print("[monica]   context overflow from Monica session; retrying once with fresh explicit session")
        text = _run_openclaw_command(_openclaw_command(prompt, force_local=False, session_id=f"monica-pipeline-retry-{uuid.uuid4()}"))
    if _looks_like_context_overflow(text):
        raise RuntimeError("Monica writer context overflow after fresh-session retry")
    return text


def _merge_article(original: dict, packet: dict, payload: dict) -> dict:
    title = _normalize_ws(payload.get("title", ""))
    summary = _normalize_ws(payload.get("summary", ""))
    content = str(payload.get("content", "")).strip()
    category = _normalize_ws(payload.get("category", ""))
    packet_category = _normalize_ws(str(packet.get("category") or packet.get("category_hint") or ""))
    if packet_category in ALLOWED_CATEGORIES:
        category = packet_category
    elif category not in ALLOWED_CATEGORIES:
        category = "Kotimaa"

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
            "degraded_mode": False,
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

            issues = _basic_payload_issues(payload)
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
            save_writer_quarantine(packet, "dispatch_error", raw_response=raw, extra={"reason_code": _dispatch_reason_code(e), "error": str(e)})
            print(f"[monica]   quarantine: dispatch_error ({e})")

    if written:
        print(f"[monica] completed: {len(written)}/{len(articles)} articles")
    else:
        print(f"[monica] completed: 0/{len(articles)} articles")
    return written
