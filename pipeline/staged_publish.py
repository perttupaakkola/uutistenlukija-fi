#!/usr/bin/env python3
"""Staged uutistenlukija publishing pipeline.

Stages:
  scan          Cheap RSS/firehose/research stage; writes prepared story packets.
  monica-worker Low-priority single-packet Monica writer worker.
  publish       Publishes completed Monica outbox packets, then optional git push.

This avoids the old pattern where every cron run did scan -> Monica -> publish
inside one long OpenClaw/gateway-mediated process.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import shutil
from statistics import median
from typing import Any

PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PIPELINE_DIR.parent
LOG_DIR = PIPELINE_DIR / "logs"
STAGED_ROOT = PIPELINE_DIR / "queues" / "staged"
for sub in ["ready", "writing", "outbox", "published", "failed"]:
    (STAGED_ROOT / sub).mkdir(parents=True, exist_ok=True)

# Make local pipeline imports work when run from cron.
sys.path.insert(0, str(PIPELINE_DIR))

from scanner import scan_all_feeds  # noqa: E402
from firehose import poll_firehose  # noqa: E402
from research import enrich_with_research  # noqa: E402
from dedup import filter_new_articles, check_published_duplicates, dedup_within_batch, mark_published  # noqa: E402
from story_packet import build_story_packet  # noqa: E402
from publisher import publish_articles, build_site  # noqa: E402
from unsplash import fetch_images_for_articles as unsplash_fetch_images  # noqa: E402
from pexels import fetch_images_for_articles as pexels_fetch_images  # noqa: E402
from service_health import should_skip, record_success, record_failure  # noqa: E402
from monica_writer import (  # noqa: E402
    _build_prompt,
    _build_repair_prompt,
    _basic_payload_issues,
    _extract_json_object,
    _is_source_backed_near_miss,
    _merge_article,
    _near_miss_repair_metadata,
    _normalize_ws,
    _packet_source_blocks as monica_packet_source_blocks,
    _packet_source_words as monica_packet_source_words,
    _run_monica,
)
from quality_gate import score_article, run_gate as run_quality_gate  # noqa: E402


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}")


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def stable_digest(article: dict) -> str:
    import hashlib
    title = str(article.get("title") or "")
    desc = str(article.get("description") or "")
    seed = article.get("link") or f"{title}|{desc}"
    return hashlib.sha1(str(seed).encode("utf-8", errors="ignore")).hexdigest()[:10]


def existing_digests(hours: int = 48) -> set[str]:
    cutoff = time.time() - hours * 3600
    out: set[str] = set()
    for box in ["ready", "writing", "outbox", "published", "failed"]:
        for p in (STAGED_ROOT / box).glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    continue
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                digest = data.get("digest") or data.get("packet", {}).get("packet_id", "").rsplit("_", 1)[-1]
                if re.fullmatch(r"[0-9a-f]{10}", str(digest)):
                    out.add(str(digest))
            except Exception:
                continue
    return out


def total_source_words(article: dict) -> int:
    return sum(len(str(article.get(k, "") or "").split()) for k in ["title", "description", "research", "research_text"])


def source_strength(article: dict) -> tuple[int, int, int, int, int, int]:
    research = str(article.get("research") or article.get("research_text") or "")
    desc = str(article.get("description") or "")
    category = article_category(article)
    source_blocks = research.lower().count("[lähde:") + research.lower().count("[source:")
    source_words = len(research.split())
    tier_score = max(0, 4 - int(article.get("source_tier", 2) or 2))
    return (
        source_words,
        source_blocks,
        len(desc.split()),
        tier_score,
        1 if category == "Talous" else 0,
        total_source_words(article),
    )


def category_enqueue_bonus(article: dict) -> int:
    """Return bounded under-target category queue nudge after a real source floor."""
    if article_category(article) == "Talous":
        research_words = len(str(article.get("research") or article.get("research_text") or "").split())
        if research_words >= 180:
            return 40
    return 0


def passes_priority_source_floor(article: dict) -> bool:
    if article_category(article) != "Talous":
        return True
    research_words = len(str(article.get("research") or article.get("research_text") or "").split())
    return research_words >= 180


def enqueue_strength(article: dict) -> tuple[int, int, int, int, int, int]:
    strength = source_strength(article)
    return (strength[0] + category_enqueue_bonus(article), *strength[1:])


def select_scan_enqueue_candidates(articles: list[dict], max_packets: int) -> list[dict]:
    if max_packets <= 0:
        return []
    eligible_priority = [article for article in articles if article_category(article) not in CATEGORY_SCAN_ENQUEUE_PRIORITY or passes_priority_source_floor(article)]
    fallback_priority = [article for article in articles if article not in eligible_priority]
    ordered = sorted(eligible_priority, key=enqueue_strength, reverse=True) + sorted(fallback_priority, key=source_strength, reverse=True)
    if len(ordered) <= max_packets:
        return ordered

    selected = ordered[:max_packets]
    selected_categories = {article_category(article) for article in selected}
    for category in CATEGORY_SCAN_ENQUEUE_PRIORITY:
        if category in selected_categories:
            continue
        priority_candidates = [
            article
            for article in ordered[max_packets:]
            if article_category(article) == category and passes_priority_source_floor(article)
        ]
        if not priority_candidates:
            continue
        weakest_index, weakest = min(enumerate(selected), key=lambda item: source_strength(item[1]))
        best_priority = priority_candidates[0]
        priority_strength = source_strength(best_priority)
        weakest_strength = source_strength(weakest)
        # Allow the under-target Talous lane to displace only genuinely thin
        # queued candidates. Do not replace rich/high-source packets.
        if priority_strength >= weakest_strength or total_source_words(weakest) < 180:
            selected[weakest_index] = best_priority
            selected_categories = {article_category(article) for article in selected}
    return sorted(selected, key=source_strength, reverse=True)




def article_category(article: dict) -> str:
    raw = str(
        article.get("category_hint")
        or article.get("category")
        or article.get("_guessed_category")
        or "?"
    ).strip()
    return raw or "?"


def article_research_bucket(article: dict) -> str:
    source = str(article.get("research_source") or "").strip().lower()
    research = str(article.get("research") or article.get("research_text") or "").strip()
    if source in {"multi", "research"}:
        return "research_enriched"
    if source == "rss":
        return "research_fallback"
    if research:
        return "research_fallback"
    return "research_empty"


def category_counts(articles: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for article in articles:
        category = article_category(article)
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def log_scan_stage(stage: str, articles: list[dict]) -> None:
    log(f"scan-stage: {stage} total={len(articles)} categories={json.dumps(category_counts(articles), ensure_ascii=False, sort_keys=True)}")


def log_scan_research_buckets(stage: str, articles: list[dict]) -> None:
    by_category: dict[str, dict[str, int]] = {}
    for article in articles:
        category = article_category(article)
        bucket = article_research_bucket(article)
        by_category.setdefault(category, {})[bucket] = by_category.setdefault(category, {}).get(bucket, 0) + 1
    log(f"scan-stage: {stage} total={len(articles)} buckets={json.dumps(by_category, ensure_ascii=False, sort_keys=True)}")


def packet_original_article(data: dict) -> dict:
    packet = data.get("packet") or data
    return data.get("original_article") or reconstruct_original(packet)


def packet_source_words(data: dict) -> int:
    packet = data.get("packet") or data
    return monica_packet_source_words(packet)


def packet_source_blocks(data: dict) -> int:
    packet = data.get("packet") or data
    return monica_packet_source_blocks(packet)


def parse_record_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def file_record_time(path: Path, data: dict) -> datetime:
    parsed = parse_record_time(
        data.get("created_at") or data.get("completed_at") or data.get("failed_at") or data.get("published_at")
    )
    if parsed:
        return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def failure_reason_text(data: dict) -> str:
    reason = data.get("failure")
    if isinstance(reason, dict):
        reason = reason.get("reason") or reason.get("code") or reason.get("message") or json.dumps(reason, ensure_ascii=False)
    if not reason and data.get("quality_gate_rejected"):
        reason = "quality_gate_rejected"
    if not reason and data.get("duplicate_rejected"):
        reason = "duplicate_rejected"
    return str(reason or data.get("read_error") or "")


def normalize_failure_reason(reason: str | None) -> str:
    text = _normalize_ws(str(reason or "")).lower()
    if not text:
        return "unknown"
    if "insufficient_confidence" in text or "insufficient confidence" in text or "riitä" in text or "riittäv" in text or "liian niukka" in text:
        return "insufficient_confidence"
    if "source" in text and ("thin" in text or "too short" in text):
        return "thin_source"
    if "lähde" in text and ("niukka" in text or "lyhyt" in text or "ei tue" in text or "eri aihe" in text):
        return "thin_source"
    if "content too short" in text or "lead paragraph too short" in text or "sanan" in text or "words" in text:
        return "content_too_short"
    if "context overflow" in text or "timed out" in text or "timeout" in text or "openclaw" in text or "json" in text or "dispatch" in text:
        return "writer_runtime"
    if "quality" in text or "gate" in text or "unsourced" in text or "quality_gate_rejected" in text:
        return "quality_gate"
    if "duplicate" in text or "duplika" in text:
        return "duplicate"
    if "stale_low_confidence_expired" in text:
        return "stale_low_confidence_expired"
    if "stale_low_confidence_demoted" in text:
        return "stale_low_confidence_demoted"
    if "stale_ready_expired" in text or "stale" in text:
        return "stale_ready_expired"
    return "unknown"


def read_queue_record(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        return {"read_error": str(e)}


LOW_CONFIDENCE_MAX_WORDS = 120
LOW_CONFIDENCE_MAX_BLOCKS = 1
DEFAULT_DEMOTE_AFTER_HOURS = 48.0
DEFAULT_EXPIRE_AFTER_HOURS = 96.0

FAILED_HYGIENE_DEFAULT_KEEP_DAYS = 7.0
FAILED_HYGIENE_DEFAULT_KEEP_RECENT = 500
INTENTIONAL_FAILURE_BUCKETS = {"stale_ready_expired", "stale_low_confidence_expired", "stale_low_confidence_demoted", "duplicate"}


def failed_runtime_alert_summary(failure_buckets: dict[str, int]) -> dict[str, Any]:
    intentional = {k: v for k, v in failure_buckets.items() if k in INTENTIONAL_FAILURE_BUCKETS}
    runtime = {k: v for k, v in failure_buckets.items() if k not in INTENTIONAL_FAILURE_BUCKETS}
    return {
        "intentional_cleanup_total": sum(intentional.values()),
        "runtime_failure_total": sum(runtime.values()),
        "intentional_cleanup_buckets": dict(sorted(intentional.items())),
        "runtime_failure_buckets": dict(sorted(runtime.items())),
    }


def prune_failed_backlog(*, keep_days: float = FAILED_HYGIENE_DEFAULT_KEEP_DAYS, keep_recent: int = FAILED_HYGIENE_DEFAULT_KEEP_RECENT, dry_run: bool = True, bucket: str = "stale_ready_expired") -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    files = sorted((STAGED_ROOT / "failed").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = now.timestamp() - keep_days * 86400
    kept_bucket = 0
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "bucket": bucket,
        "keep_days": keep_days,
        "keep_recent": keep_recent,
        "scanned": 0,
        "kept": 0,
        "pruned": 0,
        "actions": [],
    }
    for path in files:
        summary["scanned"] += 1
        data = read_queue_record(path)
        reason = data.get("failure")
        if data.get("quality_gate_rejected"):
            reason = "quality_gate_rejected"
        reason_bucket = normalize_failure_reason(str(reason or data.get("read_error") or ""))
        should_keep = True
        if reason_bucket == bucket:
            kept_bucket += 1
            should_keep = kept_bucket <= keep_recent or path.stat().st_mtime >= cutoff
        if should_keep:
            summary["kept"] += 1
            continue
        summary["actions"].append({"file": path.name, "bucket": reason_bucket, "age_hours": round((now.timestamp() - path.stat().st_mtime) / 3600, 2)})
        summary["pruned"] += 1
        if not dry_run:
            path.unlink(missing_ok=True)
    return summary


def packet_confidence(data: dict) -> float:
    packet = data.get("packet") or data
    try:
        return float(packet.get("story_confidence") or packet.get("confidence") or 0.0)
    except Exception:
        return 0.0


def packet_audit(data: dict, path: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    source_words = packet_source_words(data)
    source_blocks = packet_source_blocks(data)
    confidence = packet_confidence(data)
    created = file_record_time(path, data) if path else parse_record_time(data.get("created_at")) or now
    age_hours = max(0.0, (now - created).total_seconds() / 3600)
    low_confidence = confidence and confidence < 0.55
    thin = source_words < LOW_CONFIDENCE_MAX_WORDS or source_blocks < LOW_CONFIDENCE_MAX_BLOCKS
    return {
        "age_hours": age_hours,
        "source_words": source_words,
        "source_blocks": source_blocks,
        "story_confidence": round(confidence, 3),
        "low_confidence": bool(low_confidence),
        "thin_source": bool(thin),
        "stale_low_confidence": bool(age_hours >= DEFAULT_DEMOTE_AFTER_HOURS and (low_confidence or thin)),
    }


def ready_packet_action(data: dict, path: Path, now: datetime, demote_after_hours: float, expire_after_hours: float) -> tuple[str, str]:
    audit = packet_audit(data, path, now)
    age = audit["age_hours"]
    stale_low = audit["stale_low_confidence"] or (age >= demote_after_hours and audit["source_words"] < 180 and audit["source_blocks"] <= 1)
    if age >= expire_after_hours and stale_low:
        return "expire", f"stale_low_confidence_expired age_h={age:.1f} source_words={audit['source_words']} source_blocks={audit['source_blocks']} confidence={audit['story_confidence']}"
    if age >= demote_after_hours and stale_low:
        return "demote", f"stale_low_confidence_demoted age_h={age:.1f} source_words={audit['source_words']} source_blocks={audit['source_blocks']} confidence={audit['story_confidence']}"
    return "keep", ""


CATEGORY_PRIORITY_BONUS = {
    # Business-control panel target: Talous is materially under target, while
    # Ulkomaat/Tiede have been over target. Give strong, already-qualified
    # Talous packets a modest queue bump without bypassing quality gates.
    "Talous": 4.0,
}

CATEGORY_WORKER_PRIORITY_BONUS = {
    # OPE-28: give already-qualified Talous packets a bounded Monica-worker
    # nudge so they are not buried behind generic ready backlog. This is
    # intentionally smaller than source-quality components and requires a
    # minimum evidence floor; it does not change Monica/source/publish gates.
    "Talous": 3.0,
}
CATEGORY_WORKER_PRIORITY_MIN_WORDS = 250
CATEGORY_WORKER_PRIORITY_MIN_BLOCKS = 1

CATEGORY_SCAN_ENQUEUE_PRIORITY = ("Talous",)


def packet_category(packet: dict, original_article: dict | None = None) -> str:
    saved = _normalize_ws(str(packet.get("category") or packet.get("category_hint") or ""))
    if saved == "Ulkomaat" and original_article:
        original_hint = _normalize_ws(str(original_article.get("category_hint") or original_article.get("category") or ""))
        guessed = _normalize_ws(str(original_article.get("_guessed_category") or ""))
        if original_hint == "Talous" or guessed == "Talous":
            return "Talous"
    return saved


def priority_score(path: Path) -> tuple[float, float, int, int, float, str]:
    data = read_queue_record(path)
    audit = packet_audit(data, path)
    age_hours = float(audit["age_hours"])
    source_words = int(audit["source_words"])
    source_blocks = int(audit["source_blocks"])
    confidence = float(audit["story_confidence"])
    packet = data.get("packet") or data
    category = packet_category(packet, data.get("original_article") or {})
    # Age still matters, but source strength prevents the worker from burning
    # the oldest thin packets forever. This is deterministic for stable mtimes.
    score = age_hours + min(source_words, 800) / 80 + source_blocks * 3 + confidence * 4
    score += CATEGORY_PRIORITY_BONUS.get(category, 0.0)
    if source_words >= CATEGORY_WORKER_PRIORITY_MIN_WORDS and source_blocks >= CATEGORY_WORKER_PRIORITY_MIN_BLOCKS:
        score += CATEGORY_WORKER_PRIORITY_BONUS.get(category, 0.0)
    if source_words < 120:
        score -= 8
    if source_words < 80:
        score -= 8
    if audit["stale_low_confidence"]:
        score -= 20
    return (score, age_hours, source_words, source_blocks, -path.stat().st_mtime, path.name)


def prioritized_ready_packets(max_packets: int | None = None) -> list[Path]:
    ready = list((STAGED_ROOT / "ready").glob("*.json"))
    ordered = sorted(ready, key=priority_score, reverse=True)
    if max_packets is None:
        return ordered
    return ordered[:max_packets]


def audit_ready_backlog(*, demote_after_hours: float = DEFAULT_DEMOTE_AFTER_HOURS, expire_after_hours: float = DEFAULT_EXPIRE_AFTER_HOURS, dry_run: bool = True, limit: int = 0) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    files = sorted((STAGED_ROOT / "ready").glob("*.json"), key=lambda p: p.stat().st_mtime)
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "scanned": 0,
        "kept": 0,
        "demoted": 0,
        "expired": 0,
        "demote_after_hours": demote_after_hours,
        "expire_after_hours": expire_after_hours,
        "actions": [],
    }
    for path in files:
        if limit and summary["scanned"] >= limit:
            break
        summary["scanned"] += 1
        data = read_queue_record(path)
        action, reason = ready_packet_action(data, path, now, demote_after_hours, expire_after_hours)
        if action == "keep":
            summary["kept"] += 1
            continue
        summary["actions"].append({"file": path.name, "action": action, "reason": reason})
        if dry_run:
            summary["demoted" if action == "demote" else "expired"] += 1
            continue
        data.update({"failed_at": now.isoformat(), "failure": reason, "backlog_audit_action": action})
        target = STAGED_ROOT / "failed" / path.name
        if target.exists():
            target = STAGED_ROOT / "failed" / f"{path.stem}_{int(time.time())}{path.suffix}"
        atomic_write_json(target, data)
        path.unlink(missing_ok=True)
        summary["demoted" if action == "demote" else "expired"] += 1
    return summary


def expire_ready_packets(max_age_hours: float) -> int:
    """Fail closed stale ready packets so Monica does not publish old news."""
    if max_age_hours <= 0:
        return 0
    now = datetime.now(timezone.utc)
    moved = 0
    for path in list((STAGED_ROOT / "ready").glob("*.json")):
        data = read_queue_record(path)
        age_hours = max(0.0, (now - file_record_time(path, data)).total_seconds() / 3600)
        if age_hours <= max_age_hours:
            continue
        data["failed_at"] = now.isoformat()
        data["failure"] = f"stale_ready_expired age_h={age_hours:.1f} max_age_h={max_age_hours:.1f}"
        target = STAGED_ROOT / "failed" / path.name
        if target.exists():
            target = STAGED_ROOT / "failed" / f"{path.stem}_{int(time.time())}{path.suffix}"
        atomic_write_json(target, data)
        path.unlink(missing_ok=True)
        moved += 1
    if moved:
        log(f"ready-expire: moved stale packets={moved} max_age_h={max_age_hours:.1f}")
    return moved


def cmd_scan(args: argparse.Namespace) -> int:
    start = time.time()
    if not args.dry_run:
        expire_ready_packets(args.max_ready_age_hours)
    ready_backlog = len(list((STAGED_ROOT / "ready").glob("*.json")))
    if args.max_ready_backlog and ready_backlog >= args.max_ready_backlog:
        log(f"scan: skipping because ready backlog={ready_backlog} >= max_ready_backlog={args.max_ready_backlog}")
        return 0
    log("scan: start")
    rss_articles = []
    fh_articles = []
    try:
        rss_articles = scan_all_feeds()
    except Exception as e:
        log(f"scan: rss failed: {e}")
    try:
        fh_articles = poll_firehose()
    except Exception as e:
        log(f"scan: firehose skipped: {e}")
    seen_url_hashes = {a.get("_url_hash") for a in rss_articles if a.get("_url_hash")}
    fh_new = [a for a in fh_articles if a.get("_url_hash") not in seen_url_hashes]
    articles = rss_articles + fh_new
    log(f"scan: discovered rss={len(rss_articles)} firehose_new={len(fh_new)} total={len(articles)}")
    log_scan_stage("discovered", articles)
    if not articles:
        return 0

    pre = len(articles)
    articles = filter_new_articles(articles)
    if articles:
        articles = check_published_duplicates(articles, window_hours=args.dedup_window)
    if articles:
        articles = dedup_within_batch(articles)
    log(f"scan: dedup {pre}->{len(articles)}")
    log_scan_stage("dedup", articles)
    if not articles:
        return 0

    already = existing_digests(hours=args.cooldown_hours)
    filtered = []
    for a in articles:
        if stable_digest(a) in already:
            continue
        filtered.append(a)
    articles = filtered
    log(f"scan: after staged cooldown {len(articles)}")
    log_scan_stage("cooldown", articles)
    if not articles:
        return 0

    if args.max_research_candidates and len(articles) > args.max_research_candidates:
        articles = articles[: args.max_research_candidates]
    log_scan_stage("research_candidates", articles)
    articles = enrich_with_research(articles)
    log_scan_research_buckets("research_result", articles)
    articles = [a for a in articles if total_source_words(a) >= args.min_source_words]
    log_scan_stage("min_source_words_pass", articles)
    articles = select_scan_enqueue_candidates(articles, args.max_packets)
    log_scan_stage("queued_candidates", articles)

    queued = 0
    for article in articles:
        digest = stable_digest(article)
        packet = build_story_packet(article)
        record = {
            "schema": "uutistenlukija.staged_packet.v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "digest": digest,
            "packet": packet,
            "original_article": article,
        }
        path = STAGED_ROOT / "ready" / f"{packet['packet_id']}.json"
        if not args.dry_run:
            atomic_write_json(path, record)
        queued += 1
        log(f"scan: queued {packet['packet_id']} {article.get('title','')[:80]}")
    log(f"scan: done queued={queued} dry_run={args.dry_run} duration_s={time.time()-start:.1f}")
    return 0



def failed_writer_feedback(data: dict, payload: dict | None = None, issues: list[str] | None = None, raw_response: str = "") -> dict[str, Any]:
    """Structured Monica-worker failure diagnostics for failed packet artifacts."""
    packet = data.get("packet") or {}
    original = data.get("original_article") or {}
    payload = payload or data.get("payload") or {}
    issues = issues or _basic_payload_issues(payload) if payload else []
    source_words = packet_source_words(data)
    source_blocks = packet_source_blocks(data)
    content = str(payload.get("content") or "")
    word_count = len(content.split())
    source_backed = source_words >= 300 and source_blocks >= 2
    near_miss = 240 <= word_count < 250 and any("content too short" in issue for issue in issues)
    invalid_json = not payload and ("json" in str(data.get("failure") or raw_response).lower() or bool(raw_response))
    if invalid_json:
        classification = "writer_invalid_json"
    elif near_miss:
        classification = "repair_near_miss_short"
    elif any("content too short" in issue or "lead paragraph too short" in issue for issue in issues):
        classification = "writer_short_after_repair"
    else:
        classification = "writer_schema_invalid"
    return {
        "packet_id": packet.get("packet_id") or payload.get("packet_id") or data.get("digest") or "",
        "category": packet.get("category") or packet.get("category_hint") or original.get("category_hint") or "?",
        "selected_source_words": source_words,
        "selected_source_blocks": source_blocks,
        "story_confidence": packet.get("story_confidence"),
        "final_word_count": word_count,
        "issues": list(issues),
        "source_backed": source_backed,
        "near_miss_short": near_miss,
        "retry_classification": classification,
        "fail_closed": True,
        "title": payload.get("title") or packet.get("headline_seed") or original.get("title") or "",
    }


def reconstruct_original(packet: dict) -> dict:
    snap = packet.get("article_snapshot") or {}
    return {
        "title": snap.get("title") or packet.get("headline_seed") or "",
        "description": snap.get("description") or packet.get("description_seed") or "",
        "link": packet.get("link") or "",
        "source": packet.get("source") or "",
        "category": packet.get("category") or packet.get("category_hint") or "Kotimaa",
        "category_hint": packet.get("category_hint") or packet.get("category") or "Kotimaa",
        "research": packet.get("source_text") or "",
    }


def process_one_packet(path: Path, args: argparse.Namespace) -> tuple[str, str]:
    writing = STAGED_ROOT / "writing" / path.name
    try:
        path.rename(writing)
    except FileNotFoundError:
        return ("skipped", "missing")
    data = json.loads(writing.read_text(encoding="utf-8", errors="replace"))
    packet = data.get("packet") or data
    original = data.get("original_article") or reconstruct_original(packet)
    raw = ""
    try:
        raw = _run_monica(_build_prompt(packet))
        payload = _extract_json_object(raw)
        if payload.get("status") == "INSUFFICIENT_CONFIDENCE":
            reason = _normalize_ws(str(payload.get("reason") or "insufficient_confidence"))
            data.update({"failed_at": datetime.now(timezone.utc).isoformat(), "failure": reason, "raw_response": raw})
            atomic_write_json(STAGED_ROOT / "failed" / writing.name, data)
            writing.unlink(missing_ok=True)
            return ("failed", reason)
        repair_metadata = None
        issues = _basic_payload_issues(payload)
        if issues:
            log(f"monica-worker: repair pass {'; '.join(issues)}")
            repaired_raw = _run_monica(_build_repair_prompt(packet, payload, issues))
            repaired_payload = _extract_json_object(repaired_raw)
            raw = repaired_raw
            payload = repaired_payload
            if payload.get("status") == "INSUFFICIENT_CONFIDENCE":
                reason = _normalize_ws(str(payload.get("reason") or "insufficient_confidence_after_repair"))
                data.update({"failed_at": datetime.now(timezone.utc).isoformat(), "failure": reason, "raw_response": raw, "writer_failure_feedback": failed_writer_feedback(data, payload, [], raw)})
                atomic_write_json(STAGED_ROOT / "failed" / writing.name, data)
                writing.unlink(missing_ok=True)
                return ("failed", reason)
            issues = _basic_payload_issues(payload)
            if _is_source_backed_near_miss(packet, payload, issues):
                near_miss_payload = payload
                near_miss_issues = list(issues) + ["source_backed_writer_shortfall: final expansion required"]
                log(f"monica-worker: near-miss repair pass {'; '.join(near_miss_issues)}")
                repaired_raw = _run_monica(_build_repair_prompt(packet, near_miss_payload, near_miss_issues))
                repaired_payload = _extract_json_object(repaired_raw)
                raw = repaired_raw
                payload = repaired_payload
                issues = _basic_payload_issues(payload)
                repair_metadata = _near_miss_repair_metadata(packet, near_miss_payload, payload, issues)
        if issues:
            feedback = failed_writer_feedback(data, payload, issues, raw)
            if repair_metadata:
                feedback.update(repair_metadata)
            data.update({"failed_at": datetime.now(timezone.utc).isoformat(), "failure": "; ".join(issues), "payload": payload, "raw_response": raw, "writer_failure_feedback": feedback})
            atomic_write_json(STAGED_ROOT / "failed" / writing.name, data)
            writing.unlink(missing_ok=True)
            return ("failed", "; ".join(issues))
        article = _merge_article(original, packet, payload)
        if repair_metadata:
            article["monica_repair"] = repair_metadata
        out = {
            **data,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "raw_response": raw,
            "article": article,
        }
        if repair_metadata:
            out["repair"] = repair_metadata
        atomic_write_json(STAGED_ROOT / "outbox" / writing.name, out)
        writing.unlink(missing_ok=True)
        return ("ok", article.get("title", "")[:100])
    except Exception as e:
        data.update({"failed_at": datetime.now(timezone.utc).isoformat(), "failure": str(e), "raw_response": raw, "writer_failure_feedback": failed_writer_feedback(data, None, [], raw_response=raw or str(e))})
        atomic_write_json(STAGED_ROOT / "failed" / writing.name, data)
        writing.unlink(missing_ok=True)
        return ("failed", str(e)[:200])


def cmd_monica_worker(args: argparse.Namespace) -> int:
    expire_ready_packets(args.max_ready_age_hours)
    ready = prioritized_ready_packets(args.max_packets)
    if not ready:
        log("monica-worker: no ready packets")
        return 0
    processed = 0
    for path in ready:
        score, age_hours, source_words, source_blocks, *_ = priority_score(path)
        log(
            f"monica-worker: processing {path.name} "
            f"priority={score:.1f} age_h={age_hours:.1f} source_words={source_words} source_blocks={source_blocks}"
        )
        status, detail = process_one_packet(path, args)
        log(f"monica-worker: {status} {detail}")
        processed += 1
    log(f"monica-worker: done processed={processed}")
    return 0


def load_outbox(max_items: int) -> list[tuple[Path, dict]]:
    out = []
    for p in sorted((STAGED_ROOT / "outbox").glob("*.json"), key=lambda p: p.stat().st_mtime)[:max_items]:
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data.get("article"), dict):
                out.append((p, data))
        except Exception as e:
            log(f"publish: skip bad outbox {p.name}: {e}")
    return out


def article_needs_image(article: dict) -> bool:
    return not article.get("image") or bool(article.get("image_category_fallback"))


def clear_image_fallback(article: dict) -> None:
    if article.get("image_category_fallback"):
        for key in ["image", "image_thumb", "image_alt", "image_credit", "image_source_url", "image_caption", "image_placeholder"]:
            article.pop(key, None)
        article["image_category_fallback"] = False


def enrich_images_for_articles(articles: list[dict], *, unsplash_delay: float = 1.2, pexels_delay: float = 0.5) -> dict[str, Any]:
    """Add hero image fields to staged articles before markdown publish.

    The staged flow bypasses run_pipeline.py step 2b, so do the same bounded
    Unsplash → Pexels lookup here. This does not relax editorial gates; if image
    providers are unavailable, articles continue to publish with existing
    category fallback behavior and the missing-image state is reported.
    """
    total = len(articles)
    if not total:
        return {"total": 0, "images": 0, "unsplash": 0, "pexels": 0, "missing": 0}

    unsplash_count = 0
    pexels_count = 0

    missing = [a for a in articles if article_needs_image(a)]
    if missing and os.environ.get("UNSPLASH_ACCESS_KEY", ""):
        skip, reason = should_skip("unsplash")
        if skip:
            log(f"images: unsplash skipped — {reason}")
        else:
            before = sum(1 for a in articles if a.get("image") and not a.get("image_category_fallback"))
            for article in missing:
                clear_image_fallback(article)
            unsplash_fetch_images(missing, delay=unsplash_delay)
            after = sum(1 for a in articles if a.get("image") and not a.get("image_category_fallback"))
            unsplash_count = max(0, after - before)
            if unsplash_count:
                record_success("unsplash")
            else:
                record_failure("unsplash")

    missing = [a for a in articles if article_needs_image(a)]
    if missing and os.environ.get("PEXELS_API_KEY", ""):
        skip, reason = should_skip("pexels")
        if skip:
            log(f"images: pexels skipped — {reason}")
        else:
            before = sum(1 for a in articles if a.get("image") and not a.get("image_category_fallback"))
            for article in missing:
                clear_image_fallback(article)
            pexels_fetch_images(missing, delay=pexels_delay)
            after = sum(1 for a in articles if a.get("image") and not a.get("image_category_fallback"))
            pexels_count = max(0, after - before)
            if pexels_count:
                record_success("pexels")
            else:
                record_failure("pexels")

    image_count = sum(1 for a in articles if a.get("image") and not a.get("image_category_fallback"))
    missing_count = sum(1 for a in articles if article_needs_image(a))
    return {
        "total": total,
        "images": image_count,
        "unsplash": unsplash_count,
        "pexels": pexels_count,
        "missing": missing_count,
    }


def quality_gate_retry_classification(data: dict, article: dict, breakdown: Any | None = None) -> dict[str, Any]:
    """Return structured fail-closed diagnostics for a post-Monica quality reject.

    This is intentionally classification-only. It makes quality-gate failures
    actionable for a later bounded writer retry, but never bypasses the publish
    gate or republishes weak/unsupported copy.
    """
    packet = data.get("packet") or {}
    original = data.get("original_article") or {}
    payload = data.get("payload") or {}
    breakdown = breakdown or score_article(article)
    source_words = packet_source_words(data)
    source_blocks = packet_source_blocks(data)
    category = packet.get("category") or packet.get("category_hint") or article.get("category") or original.get("category_hint") or "?"
    reasons = list(dict.fromkeys([*breakdown.reasons, *breakdown.hard_fails, *breakdown.soft_warnings]))
    blocking = [reason for reason in reasons if any(token in reason.lower() for token in [
        "central unsourced number",
        "unsourced_numbers",
        "language weak",
        "missing: image",
        "duplication",
        "duplicate",
        "repeated paragraph",
        "source leakage",
        "substantial english",
        "thin_source",
        "truncated",
    ])]
    length_only_reasons = [reason for reason in reasons if not reason.startswith("missing: key_points")]
    length_only = bool(length_only_reasons) and all(
        reason.startswith("length") or "too_short" in reason or "paragraph" in reason or "lead" in reason
        for reason in length_only_reasons
    )
    source_backed = source_words >= 300 and source_blocks >= 2
    repair_eligible = bool(source_backed and length_only and not blocking)
    if repair_eligible:
        classification = "repairable_length_only"
    elif source_backed:
        classification = "fail_closed_quality_gate"
    else:
        classification = "fail_closed_thin_source"
    return {
        "packet_id": packet.get("packet_id") or payload.get("packet_id") or data.get("digest") or "",
        "category": category,
        "selected_source_words": source_words,
        "selected_source_blocks": source_blocks,
        "story_confidence": packet.get("story_confidence"),
        "quality_total": breakdown.total,
        "quality_normalized": breakdown.normalized_score,
        "quality_reasons": reasons,
        "hard_fails": list(breakdown.hard_fails),
        "soft_warnings": list(breakdown.soft_warnings),
        "repair_eligible": repair_eligible,
        "retry_classification": classification,
        "fail_closed": not repair_eligible,
        "source_backed": source_backed,
        "article_words": len((article.get("content") or "").split()),
        "title": article.get("title") or payload.get("title") or original.get("title") or "",
    }


def quarantine_rejected_outbox(items: list[tuple[Path, dict]], rejected_articles: list[dict]) -> int:
    """Move quality-gate rejects out of outbox so one bad draft cannot block publishing."""
    rejected_ids = {id(article) for article in rejected_articles}
    moved = 0
    for path, data in items:
        article = data.get("article")
        if id(article) not in rejected_ids:
            continue
        breakdown = score_article(article)
        data["quality_gate_rejected_at"] = datetime.now(timezone.utc).isoformat()
        data["quality_gate_rejected"] = True
        data["quality_gate_feedback"] = quality_gate_retry_classification(data, article, breakdown)
        data["failure"] = "quality_gate_rejected: " + "; ".join(data["quality_gate_feedback"].get("quality_reasons") or ["unknown"])
        target = STAGED_ROOT / "failed" / path.name
        # Preserve any existing failed artifact rather than overwriting evidence.
        if target.exists():
            target = STAGED_ROOT / "failed" / f"{path.stem}_{int(time.time())}{path.suffix}"
        atomic_write_json(target, data)
        path.unlink(missing_ok=True)
        moved += 1
    if moved:
        log(f"publish: quarantined quality-gate rejects moved={moved}")
    return moved


def quarantine_duplicate_outbox(items: list[tuple[Path, dict]], kept_articles: list[dict]) -> int:
    """Move drafts dropped by published/batch dedup out of outbox.

    Quality-gate rejects were already fail-closed, but duplicate drafts could stay
    in outbox forever. Because publish only loads the oldest N outbox files, one
    duplicate at the front repeatedly blocked later valid Monica output.
    """
    kept_ids = {id(article) for article in kept_articles}
    moved = 0
    for path, data in items:
        article = data.get("article")
        if id(article) in kept_ids:
            continue
        data["duplicate_rejected_at"] = datetime.now(timezone.utc).isoformat()
        data["duplicate_rejected"] = True
        target = STAGED_ROOT / "failed" / path.name
        if target.exists():
            target = STAGED_ROOT / "failed" / f"{path.stem}_{int(time.time())}{path.suffix}"
        atomic_write_json(target, data)
        path.unlink(missing_ok=True)
        moved += 1
    if moved:
        log(f"publish: quarantined duplicate drops moved={moved}")
    return moved


def refresh_static_status() -> None:
    """Regenerate public status artifacts after staged publish changes.

    The staged pipeline replaced the old monolithic auto_publish path, but the
    site health JSONs are still the public control-plane truth. Keep them in the
    deploy commit whenever a staged publish creates articles.
    """
    commands = [
        [sys.executable, "pipeline/generate_health.py"],
        [sys.executable, "pipeline/generate_pipeline_status.py"],
        [sys.executable, "pipeline/generate_search_index.py"],
        [sys.executable, "scripts/category_distribution.py", "--dry-run"],
        ["bash", "scripts/daily-snapshot.sh"],
    ]
    for cmd in commands:
        res = subprocess.run(cmd, cwd=PROJECT_DIR, timeout=180, text=True, capture_output=True)
        if res.returncode != 0:
            combined = (res.stdout + "\n" + res.stderr).strip()
            raise RuntimeError(f"status refresh failed rc={res.returncode}: {' '.join(cmd)}\n{combined[-1000:]}")
        if res.stdout.strip():
            log(res.stdout.strip()[-1000:])


def run_git_deploy(created_count: int) -> int:
    if created_count <= 0:
        return 0
    try:
        refresh_static_status()
    except Exception as e:
        log(f"deploy: status refresh failed: {e}")
        return 3
    cmds = [
        [
            "git",
            "add",
            "-A",
            "content/",
            "static/api/",
            "static/metrics/",
            "static/search-index.json",
            "pipeline/published_url_hashes.json",
            "pipeline/queues/staged/",
        ],
        ["git", "commit", "-m", f"Auto-publish staged: {created_count} new articles ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})"],
        ["git", "push", "origin", "main"],
    ]
    # Fetch first. Do not hard reset after publishing; use rebase/autostash before add if clean enough.
    subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=PROJECT_DIR, timeout=120, check=False)
    for cmd in cmds:
        res = subprocess.run(cmd, cwd=PROJECT_DIR, timeout=180, text=True, capture_output=True)
        if res.returncode != 0:
            combined = (res.stdout + "\n" + res.stderr).strip()
            if cmd[1] == "commit" and "nothing to commit" in combined.lower():
                log("deploy: nothing to commit")
                return 0
            log(f"deploy: command failed rc={res.returncode}: {' '.join(cmd)}\n{combined[-1000:]}")
            return res.returncode
        if res.stdout.strip():
            log(res.stdout.strip()[-1000:])
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    items = load_outbox(args.max_articles)
    if not items:
        log("publish: no outbox articles")
        return 0
    articles = [data["article"] for _, data in items]
    gate = run_quality_gate(articles)
    if not args.dry_run:
        quarantine_rejected_outbox(items, gate.rejected)
    articles = gate.passed
    if not articles:
        log(f"publish: all articles rejected by quality gate rejected={len(gate.rejected)}")
        return 0
    articles = check_published_duplicates(articles, window_hours=args.dedup_window)
    articles = dedup_within_batch(articles)
    if not args.dry_run:
        quarantine_duplicate_outbox(items, articles)
    if not articles:
        log("publish: all articles dropped as duplicates")
        return 0
    image_summary = enrich_images_for_articles(articles)
    log(
        "publish: images "
        f"{image_summary['images']}/{image_summary['total']} "
        f"unsplash={image_summary['unsplash']} pexels={image_summary['pexels']} "
        f"missing={image_summary['missing']}"
    )
    if args.dry_run:
        log(f"publish: dry-run would publish {len(articles)} article(s)")
        for a in articles:
            log(f"publish: dry-run article {a.get('title','')[:100]}")
        return 0
    created = publish_articles(articles)
    if created:
        mark_published(articles)
        ok, err = build_site()
        if not ok:
            log(f"publish: build failed: {err}")
            return 2
        keep = {a.get("monica_packet_id") for a in articles if a.get("monica_packet_id")}
        for p, data in items:
            pid = (data.get("packet") or {}).get("packet_id")
            if pid in keep:
                target = STAGED_ROOT / "published" / p.name
                data["published_at"] = datetime.now(timezone.utc).isoformat()
                data["created_files"] = created
                atomic_write_json(target, data)
                p.unlink(missing_ok=True)
        if args.git_push:
            return run_git_deploy(len(created))
    log(f"publish: done created={len(created)}")
    return 0


def queue_box_status(box: str, files: list[Path], now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {"count": len(files), "size_bytes": sum(p.stat().st_size for p in files)}
    if not files:
        return result

    records = [(p, read_queue_record(p)) for p in files]
    times = [file_record_time(p, data) for p, data in records]
    ages = sorted(max(0.0, (now - t).total_seconds() / 3600) for t in times)
    source_words = sorted(packet_source_words(data) for _, data in records)
    result.update(
        {
            "oldest_at": min(times).isoformat(),
            "newest_at": max(times).isoformat(),
            "oldest_age_hours": round(max(ages), 2),
            "median_age_hours": round(float(median(ages)), 2),
            "newest_age_hours": round(min(ages), 2),
            "source_words_min": source_words[0] if source_words else 0,
            "source_words_median": int(median(source_words)) if source_words else 0,
            "source_words_p90": source_words[min(len(source_words) - 1, int(len(source_words) * 0.9))] if source_words else 0,
        }
    )
    if box == "ready":
        audits = [packet_audit(data, p, now) for p, data in records]
        result["audit"] = {
            "low_confidence": sum(1 for a in audits if a["low_confidence"]),
            "thin_source": sum(1 for a in audits if a["thin_source"]),
            "stale_low_confidence": sum(1 for a in audits if a["stale_low_confidence"]),
            "demote_candidates_48h": sum(1 for p, data in records if ready_packet_action(data, p, now, DEFAULT_DEMOTE_AFTER_HOURS, DEFAULT_EXPIRE_AFTER_HOURS)[0] == "demote"),
            "expire_candidates_96h": sum(1 for p, data in records if ready_packet_action(data, p, now, DEFAULT_DEMOTE_AFTER_HOURS, DEFAULT_EXPIRE_AFTER_HOURS)[0] == "expire"),
        }
    if box == "failed":
        buckets: dict[str, int] = {}
        alert_buckets: dict[str, int] = {"expected_cleanup": 0, "quality": 0, "writer_runtime": 0, "unknown": 0}
        for _, data in records:
            bucket = normalize_failure_reason(failure_reason_text(data))
            buckets[bucket] = buckets.get(bucket, 0) + 1
            if bucket in {"stale_ready_expired", "stale_low_confidence_expired", "stale_low_confidence_demoted", "duplicate"}:
                alert_buckets["expected_cleanup"] += 1
            elif bucket == "writer_runtime":
                alert_buckets["writer_runtime"] += 1
            elif bucket == "unknown":
                alert_buckets["unknown"] += 1
            else:
                alert_buckets["quality"] += 1
        result["failure_reason_buckets"] = dict(sorted(buckets.items()))
        result["alert_summary"] = failed_runtime_alert_summary(result["failure_reason_buckets"])
        result["failure_alert_buckets"] = alert_buckets
    return result


def ready_sample(path: Path) -> dict[str, Any]:
    data = read_queue_record(path)
    score, age_hours, source_words, source_blocks, *_ = priority_score(path)
    packet = data.get("packet") or data
    article = packet_original_article(data)
    return {
        "file": path.name,
        "packet_id": packet.get("packet_id") or path.stem,
        "title": article.get("title") or packet.get("headline_seed") or "",
        "priority_score": round(score, 2),
        "age_hours": round(age_hours, 2),
        "source_words": source_words,
        "source_blocks": source_blocks,
        "story_confidence": packet_confidence(data),
        "category": packet_category(packet, data.get("original_article") or {}),
        "category_priority_bonus": CATEGORY_PRIORITY_BONUS.get(packet_category(packet, data.get("original_article") or {}), 0.0),
        "category_worker_priority_bonus": (
            CATEGORY_WORKER_PRIORITY_BONUS.get(packet_category(packet, data.get("original_article") or {}), 0.0)
            if source_words >= CATEGORY_WORKER_PRIORITY_MIN_WORDS and source_blocks >= CATEGORY_WORKER_PRIORITY_MIN_BLOCKS
            else 0.0
        ),
        "audit": packet_audit(data, path),
    }


def cleanup_failed_queue(max_age_hours: float, archive: bool = False, dry_run: bool = True) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    failed_dir = STAGED_ROOT / "failed"
    archive_dir = STAGED_ROOT / "failed_archive"
    summary: dict[str, Any] = {"scanned": 0, "matched": 0, "deleted": 0, "archived": 0, "dry_run": dry_run, "max_age_hours": max_age_hours, "buckets": {}}
    if max_age_hours <= 0 or not failed_dir.exists():
        return summary
    for path in sorted(failed_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        data = read_queue_record(path)
        summary["scanned"] += 1
        age_hours = max(0.0, (now - file_record_time(path, data)).total_seconds() / 3600)
        bucket = normalize_failure_reason(failure_reason_text(data))
        summary["buckets"][bucket] = summary["buckets"].get(bucket, 0) + 1
        if bucket != "stale_ready_expired" or age_hours < max_age_hours:
            continue
        summary["matched"] += 1
        if dry_run:
            continue
        if archive:
            archive_dir.mkdir(parents=True, exist_ok=True)
            target = archive_dir / path.name
            if target.exists():
                target = archive_dir / f"{path.stem}_{int(now.timestamp())}{path.suffix}"
            shutil.move(str(path), str(target))
            summary["archived"] += 1
        else:
            path.unlink(missing_ok=True)
            summary["deleted"] += 1
    return summary


def cmd_audit_ready(args: argparse.Namespace) -> int:
    summary = audit_ready_backlog(
        demote_after_hours=args.demote_after_hours,
        expire_after_hours=args.expire_after_hours,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_prune_failed(args: argparse.Namespace) -> int:
    summary = prune_failed_backlog(
        keep_days=args.keep_days,
        keep_recent=args.keep_recent,
        dry_run=args.dry_run,
        bucket=args.bucket,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_cleanup_failed(args: argparse.Namespace) -> int:
    summary = cleanup_failed_queue(max_age_hours=args.max_age_hours, archive=args.archive, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    status: dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    for box in ["ready", "writing", "outbox", "published", "failed"]:
        files = list((STAGED_ROOT / box).glob("*.json"))
        status[box] = queue_box_status(box, files, now) if args.verbose else {
            "count": len(files),
            "size_bytes": sum(p.stat().st_size for p in files),
        }
    if args.sample_ready:
        status["ready_priority_sample"] = [ready_sample(p) for p in prioritized_ready_packets(args.sample_ready)]
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--max-packets", type=int, default=3)
    scan.add_argument("--max-research-candidates", type=int, default=12)
    scan.add_argument("--min-source-words", type=int, default=50)
    scan.add_argument("--dedup-window", type=int, default=48)
    scan.add_argument("--cooldown-hours", type=int, default=24)
    scan.add_argument("--max-ready-backlog", type=int, default=120, help="skip scan when ready queue is already this large; 0 disables")
    scan.add_argument("--max-ready-age-hours", type=float, default=36.0, help="expire ready packets older than this; 0 disables")
    scan.add_argument("--dry-run", action="store_true")
    scan.set_defaults(func=cmd_scan)

    worker = sub.add_parser("monica-worker")
    worker.add_argument("--max-packets", type=int, default=1)
    worker.add_argument("--max-ready-age-hours", type=float, default=36.0, help="expire ready packets older than this before selecting work; 0 disables")
    worker.set_defaults(func=cmd_monica_worker)

    pub = sub.add_parser("publish")
    pub.add_argument("--max-articles", type=int, default=2)
    pub.add_argument("--dedup-window", type=int, default=48)
    pub.add_argument("--git-push", action="store_true")
    pub.add_argument("--dry-run", action="store_true")
    pub.set_defaults(func=cmd_publish)

    audit = sub.add_parser("audit-ready")
    audit.add_argument("--demote-after-hours", type=float, default=DEFAULT_DEMOTE_AFTER_HOURS)
    audit.add_argument("--expire-after-hours", type=float, default=DEFAULT_EXPIRE_AFTER_HOURS)
    audit.add_argument("--limit", type=int, default=0, help="scan only first N oldest ready packets")
    audit.add_argument("--dry-run", action="store_true", default=False, help="report actions without moving packets")
    audit.set_defaults(func=cmd_audit_ready)

    prune = sub.add_parser("prune-failed")
    prune.add_argument("--bucket", default="stale_ready_expired", help="normalized failed bucket to rotate")
    prune.add_argument("--keep-days", type=float, default=FAILED_HYGIENE_DEFAULT_KEEP_DAYS)
    prune.add_argument("--keep-recent", type=int, default=FAILED_HYGIENE_DEFAULT_KEEP_RECENT)
    prune.add_argument("--dry-run", action="store_true", default=False, help="report files without deleting them")
    prune.set_defaults(func=cmd_prune_failed)

    cleanup = sub.add_parser("cleanup-failed")
    cleanup.add_argument("--max-age-hours", type=float, default=168.0, help="remove/archive stale_ready_expired failed records older than this")
    cleanup.add_argument("--archive", action="store_true", help="move records to failed_archive instead of deleting")
    cleanup.add_argument("--dry-run", action="store_true", default=False, help="report matches without changing files")
    cleanup.set_defaults(func=cmd_cleanup_failed)

    status = sub.add_parser("status")
    status.add_argument("--verbose", action="store_true", help="include queue age/source metrics and failed reason buckets")
    status.add_argument("--sample-ready", type=int, default=0, help="include top N ready packets by worker priority without moving files")
    status.set_defaults(func=cmd_status)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
