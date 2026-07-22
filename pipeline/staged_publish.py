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
PIPELINE_CACHE_DIR = PIPELINE_DIR / "cache"
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
from publisher import build_site, effective_category, publish_articles  # noqa: E402
from unsplash import fetch_images_for_articles as unsplash_fetch_images  # noqa: E402
from pexels import fetch_images_for_articles as pexels_fetch_images  # noqa: E402
from image_candidate_guard import category_fallback_fields  # noqa: E402
from image_gen import generate_images_for_articles  # noqa: E402
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
from publish_preflight import evaluate_publish_preflight  # noqa: E402


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}")


def _published_category_from_record(data: dict[str, Any]) -> str:
    """Read the actual committed front-matter category for a retained record."""
    for created in data.get("created_files") or []:
        path = PROJECT_DIR / "content" / "posts" / Path(str(created)).name
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            if line.strip() == "categories:" and index + 1 < len(lines):
                return lines[index + 1].strip().removeprefix("-").strip()
    return ""


def category_decision_trace(data: dict[str, Any], publisher_category: str = "") -> dict[str, Any]:
    """Join privacy-safe guard, writer, and publisher category decisions."""
    packet = data.get("packet") or {}
    payload = data.get("payload") or {}
    article = data.get("article") or {}
    decisions = {
        "guard": str(packet.get("category") or packet.get("category_hint") or "").strip(),
        "writer": str(payload.get("category") or "").strip(),
        "publisher": publisher_category or _published_category_from_record(data) or effective_category(article),
    }
    known = [value for value in decisions.values() if value]
    return {
        "packet_id": str(packet.get("packet_id") or data.get("digest") or "unknown"),
        "decisions": decisions,
        "disagreement": len(set(known)) > 1,
    }


def log_category_decision_trace(trace: dict[str, Any]) -> None:
    decisions = trace["decisions"]
    log(
        "category-trace "
        f"packet={trace['packet_id']} guard={decisions['guard'] or '-'} "
        f"writer={decisions['writer'] or '-'} publisher={decisions['publisher'] or '-'} "
        f"disagreement={str(trace['disagreement']).lower()}"
    )


def load_env_files() -> None:
    """Load project/pipeline env files for cron-safe provider credentials."""
    for path in [PROJECT_DIR / ".env", PIPELINE_DIR / ".env", Path("/workspace/.env"), Path("/home/pertt/.openclaw/.env")]:
        try:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))
        except Exception:
            continue


def sync_image_provider_keys() -> None:
    """Refresh imported image modules after env files are loaded."""
    if os.environ.get("UNSPLASH_ACCESS_KEY"):
        try:
            import unsplash as _unsplash_module
            _unsplash_module.UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
        except Exception:
            pass
    if os.environ.get("PEXELS_API_KEY"):
        try:
            import pexels as _pexels_module
            _pexels_module.PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
        except Exception:
            pass
    if os.environ.get("KIE_API_KEY"):
        try:
            import image_gen as _image_gen_module
            _image_gen_module.KIE_API_KEY = os.environ.get("KIE_API_KEY", "")
        except Exception:
            pass


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



TALOUS_RESEARCH_MIN_CANDIDATES = 2
TALOUS_SOURCE_FLOOR_COOLDOWN_SCHEMA = "uutistenlukija.talous_source_floor_cooldown.v1"


def talous_source_floor_cooldown_path() -> Path:
    return PIPELINE_CACHE_DIR / "talous_source_floor_cooldown.json"


def load_talous_source_floor_cooldown(hours: int, now_ts: float | None = None) -> dict[str, dict]:
    """Load active Talous source-floor rejects without changing quality gates."""
    if hours <= 0:
        return {}
    now_ts = time.time() if now_ts is None else now_ts
    cutoff = now_ts - hours * 3600
    path = talous_source_floor_cooldown_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    candidates = payload.get("candidates") or {}
    active: dict[str, dict] = {}
    for digest, record in candidates.items():
        try:
            rejected_at = float(record.get("rejected_at", 0))
        except (AttributeError, TypeError, ValueError):
            continue
        if rejected_at >= cutoff:
            active[str(digest)] = dict(record)
    return active


def filter_talous_source_floor_cooldown(
    articles: list[dict], hours: int, now_ts: float | None = None
) -> tuple[list[dict], list[dict]]:
    """Remove recent thin Talous repeats before they consume research capacity."""
    active = load_talous_source_floor_cooldown(hours=hours, now_ts=now_ts)
    if not active:
        return articles, []
    kept: list[dict] = []
    skipped: list[dict] = []
    for article in articles:
        if article_category(article) == "Talous" and stable_digest(article) in active:
            skipped.append(article)
        else:
            kept.append(article)
    return kept, skipped


def record_talous_source_floor_rejections(
    before: list[dict],
    after: list[dict],
    hours: int,
    now_ts: float | None = None,
) -> list[dict]:
    """Persist only Talous candidates rejected by the existing source floor."""
    if hours <= 0:
        return []
    selected_digests = {stable_digest(article) for article in after}
    rejected: list[dict] = []
    for article in before:
        digest = stable_digest(article)
        drop_reason = talous_enqueue_drop_reason(article)
        if digest in selected_digests or drop_reason not in {
            "source_floor_not_met",
            "source_floor_one_block_too_short",
        }:
            continue
        rejected.append(article)
    if not rejected:
        return []

    now_ts = time.time() if now_ts is None else now_ts
    active = load_talous_source_floor_cooldown(hours=hours, now_ts=now_ts)
    for article in rejected:
        digest = stable_digest(article)
        active[digest] = {
            "rejected_at": now_ts,
            "reason": talous_enqueue_drop_reason(article),
            "title": str(article.get("title") or "")[:100],
            "source": str(article.get("source") or article.get("source_name") or "")[:60],
        }
    path = talous_source_floor_cooldown_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "schema": TALOUS_SOURCE_FLOOR_COOLDOWN_SCHEMA,
            "updated_at": datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
            "candidates": active,
        },
    )
    return rejected


def select_research_candidates(articles: list[dict], max_candidates: int | None) -> list[dict]:
    if not max_candidates or max_candidates <= 0 or len(articles) <= max_candidates:
        return articles
    selected = list(articles[:max_candidates])
    selected_ids = {id(article) for article in selected}
    for category in CATEGORY_SCAN_ENQUEUE_PRIORITY:
        priority_candidates = [article for article in articles if article_category(article) == category]
        if not priority_candidates:
            continue
        selected_priority = [article for article in selected if article_category(article) == category]
        target_count = min(len(priority_candidates), TALOUS_RESEARCH_MIN_CANDIDATES)
        for candidate in priority_candidates:
            if len(selected_priority) >= target_count:
                break
            if id(candidate) in selected_ids:
                continue
            # Preserve still-eligible under-target category items that survived
            # cooldown before source acquisition. Research/source/editorial
            # gates still decide later; this only prevents Talous from starving
            # before enrichment when the candidate cap is tight.
            replace_index = None
            for index in range(len(selected) - 1, -1, -1):
                if article_category(selected[index]) != category:
                    replace_index = index
                    break
            if replace_index is None:
                break
            selected[replace_index] = candidate
            selected_ids = {id(article) for article in selected}
            selected_priority.append(candidate)
    return selected

def staged_digest_statuses(digest: str, hours: int = 48) -> list[tuple[str, Path]]:
    cutoff = time.time() - hours * 3600
    matches: list[tuple[str, Path]] = []
    for box in ["ready", "writing", "outbox", "published", "failed"]:
        for path in (STAGED_ROOT / box).glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                path_digest = data.get("digest") or data.get("packet", {}).get("packet_id", "").rsplit("_", 1)[-1]
                if str(path_digest) == digest:
                    matches.append((box, path))
            except Exception:
                continue
    matches.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
    return matches


def staged_digest_status(digest: str, hours: int = 48) -> tuple[str, Path | None]:
    statuses = staged_digest_statuses(digest, hours=hours)
    if statuses:
        return statuses[0]
    return "", None


def staged_failed_retry_classification(data: dict) -> str:
    if data.get("duplicate_rejected"):
        return "duplicate"
    normalized_failure = normalize_failure_reason(data.get("failure") or "")
    if normalized_failure == "writer_runtime":
        return normalized_failure
    if data.get("quality_gate_feedback", {}).get("retry_classification"):
        return str(data["quality_gate_feedback"]["retry_classification"])
    if data.get("writer_failure_feedback", {}).get("retry_classification"):
        return str(data["writer_failure_feedback"]["retry_classification"])
    return normalized_failure


RECOVERABLE_TALOUS_FAILED_CLASSES = {
    "repair_near_miss_short",
    "writer_short_after_repair",
}
TALOUS_NEAR_SHORT_RETRY_MIN_SOURCE_WORDS = 300
TALOUS_NEAR_SHORT_RETRY_MIN_SOURCE_BLOCKS = 3
TALOUS_NEAR_SHORT_RETRY_MIN_CONFIDENCE = 0.85
TALOUS_NEAR_SHORT_RETRY_MIN_WORDS = 220
TALOUS_NEAR_SHORT_RETRY_MAX_WORDS = 249
TALOUS_NEAR_SHORT_RETRY_MAX_RECENT_FAILURES = 3


def talous_near_short_retry_eligible(data: dict) -> bool:
    """Return True for Monica-approved clean Talous near-short retries only.

    This keeps the under-target Talous lane alive for source-backed writer
    shortfalls without turning every failed org-source packet into an infinite
    retry loop. Duplicate and quality failures stay closed elsewhere.
    """
    if data.get("duplicate_rejected"):
        return False
    packet = data.get("packet") or {}
    original = data.get("original_article") or {}
    feedback = data.get("writer_failure_feedback") or {}
    category = packet_category(packet, original)
    if category != "Talous":
        return False
    if staged_failed_retry_classification(data) not in RECOVERABLE_TALOUS_FAILED_CLASSES:
        return False

    try:
        source_words = int(feedback.get("selected_source_words") or packet_source_words(data))
    except (TypeError, ValueError):
        source_words = packet_source_words(data)
    try:
        source_blocks = int(feedback.get("selected_source_blocks") or packet_source_blocks(data))
    except (TypeError, ValueError):
        source_blocks = packet_source_blocks(data)
    try:
        confidence = float(feedback.get("story_confidence") or packet.get("story_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        final_words = int(feedback.get("final_word_count") or 0)
    except (TypeError, ValueError):
        final_words = 0

    if source_words < TALOUS_NEAR_SHORT_RETRY_MIN_SOURCE_WORDS:
        return False
    if source_blocks < TALOUS_NEAR_SHORT_RETRY_MIN_SOURCE_BLOCKS:
        return False
    if confidence < TALOUS_NEAR_SHORT_RETRY_MIN_CONFIDENCE:
        return False
    if not (TALOUS_NEAR_SHORT_RETRY_MIN_WORDS <= final_words <= TALOUS_NEAR_SHORT_RETRY_MAX_WORDS):
        return False

    issues = feedback.get("issues") or []
    if not issues:
        issues = [str(data.get("failure") or "")]
    issue_text = "; ".join(str(issue) for issue in issues).lower()
    if "content too short" not in issue_text:
        return False
    # Keep the retry lane to the exact Monica class: content length shortfall
    # only. Lead/schema/quality failures need to stay fail-closed.
    allowed_issue = re.compile(r"^\s*content too short:\s*\d+\s+words\s*$", re.IGNORECASE)
    if any(not allowed_issue.match(str(issue)) for issue in issues):
        return False

    diagnostics = packet.get("source_diagnostics") or {}
    selected_sources = diagnostics.get("selected_sources") or packet.get("source_names") or []
    if isinstance(selected_sources, str):
        selected_sources = [selected_sources]
    selected_sources = [str(source).strip().lower() for source in selected_sources if str(source).strip()]
    # Strict cleanliness check: the retry exception is only for one coherent
    # selected-source cluster. Mixed-source packets can still publish normally
    # if Monica produces valid copy, but they should not bypass cooldown.
    if selected_sources and len(set(selected_sources)) != 1:
        return False
    return True


def should_skip_staged_cooldown(article: dict, hours: int = 48) -> bool:
    digest = stable_digest(article)
    statuses = staged_digest_statuses(digest, hours=hours)
    if not statuses:
        return False
    if article_category(article) == "Talous":
        saw_failed = False
        eligible_retry_failures = 0
        for box, path in statuses:
            if box != "failed":
                return True
            saw_failed = True
            # Keep source acquisition alive only for Monica's narrow
            # source-backed near-short class. Do not bypass cooldown for
            # duplicate, contaminated-source, lead/schema, quality-gate, or
            # repeated unresolved writer shortfalls.
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                data = {}
            if not talous_near_short_retry_eligible(data):
                return True
            eligible_retry_failures += 1
            if eligible_retry_failures >= TALOUS_NEAR_SHORT_RETRY_MAX_RECENT_FAILURES:
                return True
        return not saw_failed
    return True

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


def raw_research_source_evidence(article: dict) -> tuple[int, int]:
    research = str(article.get("research") or article.get("research_text") or "")
    return (
        len(research.split()),
        research.lower().count("[lähde:") + research.lower().count("[source:"),
    )


def selected_source_evidence(article: dict) -> tuple[int, int]:
    """Return post-selection source words/blocks for Talous enqueue decisions."""
    if isinstance(article.get("_selected_source_evidence"), dict):
        evidence = article["_selected_source_evidence"]
        return int(evidence.get("source_words", 0) or 0), int(evidence.get("source_blocks", 0) or 0)

    raw_words, raw_blocks = raw_research_source_evidence(article)
    evidence = {
        "source_words": raw_words,
        "source_blocks": raw_blocks,
        "basis": "raw_research",
    }
    if article_category(article) == "Talous":
        try:
            packet = build_story_packet(article)
            diagnostics = packet.get("source_diagnostics") or {}
            selected_blocks = packet.get("clean_source_blocks") or []
            selected_words = int(diagnostics.get("selected_source_words", 0) or 0)
            selected_count = len(selected_blocks)
            basis = "selected_sources" if selected_blocks else "raw_research_no_selected_sources"
            if selected_words < 80 and raw_words > selected_words:
                selected_words = raw_words
                selected_count = raw_blocks
                basis = "raw_research_selected_under_floor"
            elif selected_words < 180 and raw_words >= 180 and raw_blocks >= 2:
                selected_words = raw_words
                selected_count = raw_blocks
                basis = "raw_research_selected_under_floor"
            evidence = {
                "source_words": selected_words,
                "source_blocks": selected_count,
                "basis": basis,
                "candidate_source_words": int(diagnostics.get("candidate_source_words", 0) or 0),
                "candidate_blocks": int(diagnostics.get("candidate_blocks", 0) or 0),
            }
        except Exception as exc:
            evidence["basis"] = f"raw_research_fallback:{exc.__class__.__name__}"
    article["_selected_source_evidence"] = evidence
    return int(evidence["source_words"]), int(evidence["source_blocks"])


def annotate_selected_source_evidence(articles: list[dict]) -> list[dict]:
    for article in articles:
        if article_category(article) == "Talous":
            selected_source_evidence(article)
    return articles


def source_strength(article: dict) -> tuple[int, int, int, int, int, int]:
    desc = str(article.get("description") or "")
    category = article_category(article)
    source_words, source_blocks = selected_source_evidence(article) if category == "Talous" else raw_research_source_evidence(article)
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
    if article_category(article) == "Talous" and passes_priority_source_floor(article):
        return 40
    return 0


def passes_priority_source_floor(article: dict) -> bool:
    if article_category(article) != "Talous":
        return True
    source_words, source_blocks = selected_source_evidence(article)
    confidence = float(article.get("story_confidence") or article.get("confidence") or 0.85)
    if str(article.get("research_source") or "") == "rss_talous_source_backed":
        return source_words >= 120 and source_blocks >= 1
    if source_blocks >= 2:
        return source_words >= CATEGORY_SCAN_ENQUEUE_MIN_RESEARCH_WORDS
    guard = org_source_talous_guardrail(article)
    if source_blocks >= 1 and source_words >= 180 and confidence >= 0.90 and guard.get("classification") in {"ok_company_profile", "ok_org_source_talous", "ok_attributed_policy_claim"}:
        return True
    if source_blocks >= 1 and source_words >= 250 and guard.get("classification") in {"ok_company_profile", "ok_org_source_talous", "ok_attributed_policy_claim"}:
        return True
    return False


def enqueue_strength(article: dict) -> tuple[int, int, int, int, int, int]:
    strength = source_strength(article)
    return (strength[0] + category_enqueue_bonus(article) - org_source_talous_penalty(article), *strength[1:])


def candidate_raw_strength(article: dict) -> int:
    return source_strength(article)[0]


def scan_candidate_passes_talous_reserve(article: dict) -> bool:
    """Return true for source-backed Talous candidates safe to reserve-queue.

    This is a queue fairness rule, not a quality gate relaxation. It only
    applies after source-word filtering and preserves org/promotional penalties
    by requiring the existing enqueue penalty path to be clean.
    """
    if article_category(article) != "Talous":
        return False
    if not passes_priority_source_floor(article):
        return False
    if org_source_talous_penalty(article) > 0:
        return False
    source_words, source_blocks = selected_source_evidence(article)
    confidence = float(article.get("story_confidence") or article.get("confidence") or 0.85)
    if confidence < 0.82:
        return False
    if source_words >= 180 and source_blocks >= 2:
        return True
    guard = org_source_talous_guardrail(article)
    if source_words >= 180 and source_blocks >= 1 and confidence >= 0.90 and guard.get("classification") in {"ok_company_profile", "ok_org_source_talous", "ok_attributed_policy_claim"}:
        return True
    return source_words >= 250 and source_blocks >= 1 and guard.get("classification") in {"ok_company_profile", "ok_org_source_talous", "ok_attributed_policy_claim"}


def select_scan_enqueue_candidates(articles: list[dict], max_packets: int) -> list[dict]:
    if max_packets <= 0:
        return []

    eligible_priority = [article for article in articles if article_category(article) not in CATEGORY_SCAN_ENQUEUE_PRIORITY or passes_priority_source_floor(article)]
    fallback_priority = [article for article in articles if article not in eligible_priority]
    ordered = sorted(eligible_priority, key=enqueue_strength, reverse=True) + sorted(fallback_priority, key=source_strength, reverse=True)
    if len(ordered) <= max_packets:
        return ordered

    selected = ordered[:max_packets]
    selected_ids = {id(article) for article in selected}
    for category in CATEGORY_SCAN_ENQUEUE_PRIORITY:
        qualified_priority = [
            article
            for article in ordered
            if article_category(article) == category and passes_priority_source_floor(article)
        ]
        reserve_priority = [article for article in qualified_priority if scan_candidate_passes_talous_reserve(article)]
        reserve_pool = reserve_priority
        if not reserve_pool or any(id(article) in selected_ids for article in reserve_pool):
            continue

        weakest_index, weakest = min(enumerate(selected), key=lambda item: source_strength(item[1]))
        best_priority = reserve_pool[0]
        priority_strength = enqueue_strength(best_priority)
        weakest_strength = enqueue_strength(weakest)
        # Keep at least one source-backed under-target Talous candidate when
        # scan enqueue is capped. Do not reserve weak 1-block / low-confidence
        # Talous packets; those should wait for better sourcing or fail closed.
        if scan_candidate_passes_talous_reserve(best_priority) or priority_strength >= weakest_strength or total_source_words(weakest) < 250:
            selected[weakest_index] = best_priority
            selected_ids = {id(article) for article in selected}
    return sorted(selected, key=enqueue_strength, reverse=True)




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
    if source in {"multi", "research", "rss_talous_source_backed"}:
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


def talous_enqueue_drop_reason(article: dict) -> str:
    if article_category(article) != "Talous":
        return "not_talous"
    source_words, source_blocks = selected_source_evidence(article)
    if org_source_talous_penalty(article) > 0:
        return "org_source_guardrail_penalty"
    if not passes_priority_source_floor(article):
        if source_blocks < 1:
            return "source_floor_no_labeled_source"
        if source_blocks < 2 and source_words < 250:
            return "source_floor_one_block_too_short"
        return "source_floor_not_met"
    if not scan_candidate_passes_talous_reserve(article):
        try:
            confidence = float(article.get("story_confidence") or article.get("confidence") or 0.85)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.82:
            return "reserve_confidence_floor"
        return "reserve_floor_not_met"
    return "queue_cap_displaced_by_stronger_candidates"


def talous_drop_candidates(articles: list[dict], max_examples: int = 5) -> list[dict]:
    examples: list[dict] = []
    for article in articles:
        if article_category(article) != "Talous":
            continue
        title = str(article.get("title") or "")
        examples.append({
            "candidate_id": stable_digest(article),
            "title": title[:100],
            "source": str(article.get("source") or article.get("source_name") or "")[:60],
            "source_words": selected_source_evidence(article)[0],
            "source_blocks": selected_source_evidence(article)[1],
            "source_evidence_basis": article.get("_selected_source_evidence", {}).get("basis"),
            "research_bucket": article_research_bucket(article),
            "reserve_pass": scan_candidate_passes_talous_reserve(article),
            "guardrail": org_source_talous_guardrail(article).get("classification"),
            "drop_reason": talous_enqueue_drop_reason(article),
        })
        if len(examples) >= max_examples:
            break
    return examples


def log_talous_enqueue_drop(before: list[dict], after: list[dict]) -> None:
    before_count = category_counts(before).get("Talous", 0)
    after_count = category_counts(after).get("Talous", 0)
    if before_count and not after_count:
        log("scan-stage-drop: talous_enqueue_drop " + json.dumps(talous_drop_candidates(before), ensure_ascii=False, sort_keys=True))


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
CATEGORY_SCAN_ENQUEUE_MIN_RESEARCH_WORDS = 180



ORG_SOURCE_TALOUS_SOURCES = (
    "finanssiala",
    "suomen yrittäjät",
    "yrittajat.fi",
    "insurance europe",
)

ORG_SOURCE_SELF_PROMO_TERMS = (
    "uudisti verkkosivunsa",
    "verkkosivunsa",
    "sivuston ulkoasu",
    "tavoitteemme-osio",
    "edunvalvontatavoitteet",
    "lobbaustavoitteet",
    "liity",
    "jäsen",
    "jäseneksi",
    "tule mukaan",
)

ORG_SOURCE_VENDOR_OUTLOOK_TERMS = (
    "markkinakatsaus",
    "luottokumppani",
    "kumppani",
    "auttaa navigoimaan",
    "tekemään oikeita päätöksiä",
)

ORG_SOURCE_POLICY_TERMS = (
    "varoittaa",
    "haluaa",
    "vaatii",
    "esittää",
    "katsoo",
    "arvioi",
    "uudistus",
    "selventäisi",
    "pääomamarkkinoilla",
    "terveystietoja",
    "osakesäästötilin",
    "vauvabonus",
    "perheohjelma",
    "kannustin",
)

ORG_SOURCE_ATTRIBUTION_TERMS = (
    "mukaan",
    "katsoo",
    "arvioi",
    "varoittaa",
    "haluaa",
    "esittää",
    "sanoo",
)


def _text_blob(article: dict) -> str:
    return " ".join(
        str(article.get(key) or "")
        for key in ["title", "description", "research", "research_text", "source", "source_name", "link", "url"]
    ).lower()


def org_source_talous_guardrail(article: dict) -> dict[str, Any]:
    """Classify org-source Talous promotional drift without blanket blocking.

    The guardrail is intentionally a scoring hint for scan enqueueing, not a
    source/editorial gate. It down-ranks low-public-interest association PR or
    vendor outlooks, flags unattributed policy/evaluative claims, and leaves
    concrete human-interest/company profiles alone.
    """
    if article_category(article) != "Talous":
        return {"applies": False, "classification": "not_org_source_talous", "penalty": 0}

    text = _text_blob(article)
    if not any(source in text for source in ORG_SOURCE_TALOUS_SOURCES):
        return {"applies": False, "classification": "not_org_source_talous", "penalty": 0}

    title_desc = " ".join(str(article.get(key) or "") for key in ["title", "description"]).lower()
    source_markers = re.findall(r"\[(?:lähde|source):\s*([^\]]+)\]", text, flags=re.IGNORECASE)
    org_marker_count = sum(1 for marker in source_markers if any(source in marker.lower() for source in ORG_SOURCE_TALOUS_SOURCES))
    has_independent_source = bool(source_markers) and org_marker_count < len(source_markers)
    self_promo_hits = [term for term in ORG_SOURCE_SELF_PROMO_TERMS if term in text]
    generic_cta_terms = {"liity", "jäsen", "jäseneksi", "tule mukaan"}
    title_desc_self_promo_hits = [term for term in ORG_SOURCE_SELF_PROMO_TERMS if term in title_desc and term not in generic_cta_terms]
    # Yrittajat.fi pages often append generic membership CTA/footer text to the
    # extracted research body. Treat that boilerplate differently from a story
    # whose headline/description is itself a self-promotional org item.
    has_self_promo = bool(title_desc_self_promo_hits) or any(term not in generic_cta_terms for term in self_promo_hits)
    has_vendor_outlook = any(term in text for term in ORG_SOURCE_VENDOR_OUTLOOK_TERMS)
    has_policy_claim = any(term in title_desc or term in text for term in ORG_SOURCE_POLICY_TERMS)
    has_attribution = any(term in title_desc for term in ORG_SOURCE_ATTRIBUTION_TERMS) or any(source in title_desc for source in ("finanssiala", "yrittäjät", "vakuutusala", "insurance europe"))
    human_interest = bool(re.search(r"\b(yrittäjä|perustaja|yritys|kasvoi|tähtää|harrastus|shakki|rakennusalan|viljelij\w*|maatil\w*)\b", title_desc)) and not has_vendor_outlook and not has_self_promo

    if human_interest:
        return {"applies": True, "classification": "ok_company_profile", "penalty": 0, "requires_attribution": False}
    if (has_self_promo or has_vendor_outlook) and not has_independent_source:
        return {"applies": True, "classification": "down_rank_promotional_org_source", "penalty": 160, "requires_attribution": True}
    if has_policy_claim and not has_attribution:
        return {"applies": True, "classification": "attribution_needed_org_source", "penalty": 80, "requires_attribution": True}
    if has_policy_claim:
        return {"applies": True, "classification": "ok_attributed_policy_claim", "penalty": 0, "requires_attribution": False}
    return {"applies": True, "classification": "ok_org_source_talous", "penalty": 0, "requires_attribution": False}


def org_source_talous_penalty(article: dict) -> int:
    return int(org_source_talous_guardrail(article).get("penalty", 0) or 0)

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

    filtered = []
    for a in articles:
        if should_skip_staged_cooldown(a, hours=args.cooldown_hours):
            continue
        filtered.append(a)
    articles = filtered
    log(f"scan: after staged cooldown {len(articles)}")
    log_scan_stage("cooldown", articles)
    if not articles:
        return 0

    articles, source_floor_skips = filter_talous_source_floor_cooldown(
        articles, hours=args.cooldown_hours
    )
    if source_floor_skips:
        talous_remaining = category_counts(articles).get("Talous", 0)
        outcome = "different_candidate_available" if talous_remaining else "no_eligible_backfill"
        log(
            "scan-stage-skip: talous_source_floor_cooldown "
            f"skipped={len(source_floor_skips)} outcome={outcome}"
        )
    log_scan_stage("talous_source_floor_cooldown", articles)
    if not articles:
        return 0

    articles = select_research_candidates(articles, args.max_research_candidates)
    log_scan_stage("research_candidates", articles)
    articles = enrich_with_research(articles)
    log_scan_research_buckets("research_result", articles)
    articles = [a for a in articles if total_source_words(a) >= args.min_source_words]
    log_scan_stage("min_source_words_pass", articles)
    articles = annotate_selected_source_evidence(articles)
    pre_enqueue_articles = list(articles)
    articles = select_scan_enqueue_candidates(articles, args.max_packets)
    log_scan_stage("queued_candidates", articles)
    log_talous_enqueue_drop(pre_enqueue_articles, articles)
    if not args.dry_run:
        source_floor_rejections = record_talous_source_floor_rejections(
            pre_enqueue_articles,
            articles,
            hours=args.cooldown_hours,
        )
        if source_floor_rejections:
            log(
                "scan-stage-cooldown: talous_source_floor_recorded "
                f"candidates={len(source_floor_rejections)} hours={args.cooldown_hours}"
            )

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
    category = packet.get("category") or packet.get("category_hint") or original.get("category_hint") or "?"
    try:
        story_confidence = float(packet.get("story_confidence") or 0.0)
    except (TypeError, ValueError):
        story_confidence = 0.0
    source_backed = (
        source_words >= 300
        or (source_words >= 180 and source_blocks >= 2 and story_confidence >= 0.85)
        or (category == "Talous" and source_words >= 190 and source_blocks >= 3 and story_confidence >= 0.85)
    ) and source_blocks >= 2
    near_miss = 200 <= word_count < 250 and source_backed and any("content too short" in issue for issue in issues)
    failure_text = str(data.get("failure") or raw_response or "").lower()
    runtime_failure = any(token in failure_text for token in ("timed out", "timeout", "context overflow", "gatewayclientrequesterror", "failovererror", "oauth token"))
    invalid_json = not payload and "json" in failure_text
    if runtime_failure:
        classification = "writer_runtime"
    elif invalid_json:
        classification = "writer_invalid_json"
    elif near_miss:
        classification = "repair_near_miss_short"
    elif any("content too short" in issue or "lead paragraph too short" in issue for issue in issues):
        classification = "writer_short_after_repair"
    else:
        classification = "writer_schema_invalid"
    return {
        "packet_id": packet.get("packet_id") or payload.get("packet_id") or data.get("digest") or "",
        "category": category,
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




def talous_packet_quality_guardrail(data: dict) -> dict[str, Any]:
    """Fail weak Talous ready packets before Monica burns writer cycles.

    This is a deterministic ready-supply quality filter, not a publish gate. It
    only applies to Talous packets that already reached ready; strong source
    packets proceed unchanged, weak org/promotional packets are failed closed so
    better Talous candidates can occupy the ready lane.
    """
    packet = data.get("packet") or data
    original = data.get("original_article") or reconstruct_original(packet)
    category = packet_category(packet, original)
    if category != "Talous":
        return {"action": "keep", "reason": "not_talous"}

    source_words = packet_source_words(data)
    source_blocks = packet_source_blocks(data)
    confidence = packet_confidence(data)
    guard = org_source_talous_guardrail(original)
    title = str(packet.get("headline_seed") or original.get("title") or "").lower()
    text = _text_blob(original)
    weak_source = source_words < 180 or source_blocks < 2 or confidence < 0.82
    org_weak = bool(guard.get("applies")) and source_words < 220 and source_blocks <= 2
    promotional = guard.get("classification") == "down_rank_promotional_org_source"
    social_promo = any(term in text for term in ("instagram", "seurantaan", "vinkkaa", "kohokohtiin"))
    category_borderline = ("eduskuntaan" in title or "kansanedustaja" in text) and source_words < 220

    if promotional or social_promo:
        return {
            "action": "fail",
            "reason": "weak_talous_ready_promotional",
            "source_words": source_words,
            "source_blocks": source_blocks,
            "story_confidence": confidence,
            "org_guardrail": guard,
        }
    if category_borderline:
        return {
            "action": "fail",
            "reason": "weak_talous_ready_category_borderline",
            "source_words": source_words,
            "source_blocks": source_blocks,
            "story_confidence": confidence,
            "org_guardrail": guard,
        }
    if org_weak or weak_source:
        return {
            "action": "fail",
            "reason": "weak_talous_ready_source_floor",
            "source_words": source_words,
            "source_blocks": source_blocks,
            "story_confidence": confidence,
            "org_guardrail": guard,
        }
    return {
        "action": "keep",
        "reason": "source_quality_ok",
        "source_words": source_words,
        "source_blocks": source_blocks,
        "story_confidence": confidence,
        "org_guardrail": guard,
    }


def quarantine_weak_talous_ready(path: Path, data: dict, guard: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    data.update({
        "failed_at": now,
        "failure": guard["reason"],
        "ready_quality_feedback": {**guard, "fail_closed": True},
    })
    target = STAGED_ROOT / "failed" / path.name
    if target.exists():
        target = STAGED_ROOT / "failed" / f"{path.stem}_{int(time.time())}{path.suffix}"
    atomic_write_json(target, data)
    path.unlink(missing_ok=True)


def process_one_packet(path: Path, args: argparse.Namespace) -> tuple[str, str]:
    writing = STAGED_ROOT / "writing" / path.name
    try:
        path.rename(writing)
    except FileNotFoundError:
        return ("skipped", "missing")
    data = json.loads(writing.read_text(encoding="utf-8", errors="replace"))
    guard = talous_packet_quality_guardrail(data)
    if guard.get("action") == "fail":
        quarantine_weak_talous_ready(writing, data, guard)
        return ("failed", guard["reason"])
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


def apply_publish_preflight(items: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
    """Keep only records safe for existing publish gates; leave held files untouched."""
    eligible: list[tuple[Path, dict]] = []
    for path, data in items:
        result = evaluate_publish_preflight(data)
        if result.action == "publish":
            eligible.append((path, data))
            continue
        packet_value = data.get("packet")
        packet = packet_value if isinstance(packet_value, dict) else {}
        packet_id = packet.get("packet_id") or data.get("digest") or path.name
        ratio = "inf" if result.article_source_ratio == float("inf") else f"{result.article_source_ratio:.3f}"
        log(
            "publish: preflight hold "
            f"packet={packet_id} action={result.action} reasons={','.join(result.reasons)} "
            f"categories={'/'.join(category or '-' for category in result.categories)} "
            f"source_words={result.distinct_source_words} article_words={result.article_words} "
            f"ratio={ratio} sensitive={str(result.sensitive).lower()} "
            f"monica_review={str(result.requires_monica_review).lower()}"
        )
    return eligible


def article_needs_image(article: dict) -> bool:
    return not article.get("image") or bool(article.get("image_category_fallback"))


def article_has_provider_image(article: dict) -> bool:
    return bool(article.get("image")) and not bool(article.get("image_category_fallback"))


def clear_image_fallback(article: dict) -> None:
    if article.get("image_category_fallback"):
        for key in [
            "image", "image_thumb", "image_alt", "image_credit", "image_source_url",
            "image_caption", "image_placeholder", "image_source", "image_decision",
            "image_source_type", "image_decision_reason", "image_visual_intent",
            "image_visual_brief", "image_quality_score", "image_generated_fallback",
            "image_concept", "image_query", "image_candidate_id", "image_candidate_url",
            "image_visual_judge_score", "image_accepted_reasons", "image_rejected_reasons",
            "image_provider", "image_model", "image_prompt_version", "image_generation_prompt",
        ]:
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
        return {"total": 0, "images": 0, "unsplash": 0, "pexels": 0, "generated": 0, "category_fallback": 0, "missing": 0}

    load_env_files()
    sync_image_provider_keys()

    unsplash_count = 0
    pexels_count = 0
    generated_count = 0

    missing = [a for a in articles if article_needs_image(a)]
    if missing and os.environ.get("UNSPLASH_ACCESS_KEY", ""):
        skip, reason = should_skip("unsplash")
        if skip:
            log(f"images: unsplash skipped — {reason}")
        else:
            try:
                before = sum(1 for a in articles if article_has_provider_image(a))
                for article in missing:
                    clear_image_fallback(article)
                unsplash_fetch_images(missing, delay=unsplash_delay)
                after = sum(1 for a in articles if article_has_provider_image(a))
                unsplash_count = max(0, after - before)
            except Exception as exc:  # noqa: BLE001 - keep publisher alive on provider faults
                log(f"images: unsplash failed — {exc.__class__.__name__}: {exc}")
                record_failure("unsplash")
            else:
                if unsplash_count:
                    record_success("unsplash")

    missing = [a for a in articles if article_needs_image(a)]
    if missing and os.environ.get("PEXELS_API_KEY", ""):
        skip, reason = should_skip("pexels")
        if skip:
            log(f"images: pexels skipped — {reason}")
        else:
            try:
                before = sum(1 for a in articles if article_has_provider_image(a))
                for article in missing:
                    clear_image_fallback(article)
                pexels_fetch_images(missing, delay=pexels_delay)
                after = sum(1 for a in articles if article_has_provider_image(a))
                pexels_count = max(0, after - before)
            except Exception as exc:  # noqa: BLE001 - keep publisher alive on provider faults
                log(f"images: pexels failed — {exc.__class__.__name__}: {exc}")
                record_failure("pexels")
            else:
                if pexels_count:
                    record_success("pexels")

    missing = [a for a in articles if article_needs_image(a)]
    if missing and os.environ.get("KIE_API_KEY", ""):
        skip, reason = should_skip("kie_api")
        if skip:
            log(f"images: generated fallback skipped — Kie.ai {reason}")
        else:
            try:
                before = sum(1 for a in articles if a.get("image_source") == "generated" and article_has_provider_image(a))
                for article in missing:
                    clear_image_fallback(article)
                generate_images_for_articles(missing, max_total_sec=180)
                after = sum(1 for a in articles if a.get("image_source") == "generated" and article_has_provider_image(a))
                generated_count = max(0, after - before)
            except Exception as exc:  # noqa: BLE001 - keep publisher alive on provider faults
                log(f"images: generated fallback failed — {exc.__class__.__name__}: {exc}")
                record_failure("kie_api")
            else:
                if generated_count:
                    record_success("kie_api")
    elif missing:
        log("images: generated fallback unavailable — KIE_API_KEY missing")

    for article in [a for a in articles if article_needs_image(a)]:
        clear_image_fallback(article)
        article.update(category_fallback_fields(
            article.get("category", "Kotimaa"),
            reason="generated fallback unavailable, unsafe, or failed after stock rejection",
        ))

    image_count = sum(1 for a in articles if a.get("image") and not a.get("image_category_fallback"))
    missing_count = sum(1 for a in articles if article_needs_image(a))
    category_fallback_count = sum(1 for a in articles if a.get("image_category_fallback"))
    return {
        "total": total,
        "images": image_count,
        "unsplash": unsplash_count,
        "pexels": pexels_count,
        "generated": generated_count,
        "category_fallback": category_fallback_count,
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
            "static/images/articles/",
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
    selected_count = len(items)
    items = apply_publish_preflight(items)
    if not items:
        log(f"publish: all selected outbox records held by preflight selected={selected_count}")
        return 0
    articles = [data["article"] for _, data in items]
    gate = run_quality_gate(articles)
    if not args.dry_run:
        quarantine_rejected_outbox(items, gate.rejected)
    articles = gate.passed
    if not articles:
        log(f"publish: all articles rejected by quality gate rejected={len(gate.rejected)}")
        return 0
    articles = filter_new_articles(articles)
    articles = check_published_duplicates(articles, window_hours=args.dedup_window)
    articles = dedup_within_batch(articles)
    if not args.dry_run:
        quarantine_duplicate_outbox(items, articles)
    if not articles:
        log("publish: all articles dropped as duplicates")
        return 0
    image_summary = enrich_images_for_articles(articles)
    article_by_id = {id(article): article for article in articles}
    for _, data in items:
        article = data.get("article")
        enriched = article_by_id.get(id(article))
        if enriched is not None:
            data["article"] = enriched
            if enriched.get("image"):
                data["image_enriched_at"] = datetime.now(timezone.utc).isoformat()
                data["image_enrichment"] = {
                    "image": enriched.get("image"),
                    "image_thumb": enriched.get("image_thumb"),
                    "image_category_fallback": bool(enriched.get("image_category_fallback")),
                    "image_source": enriched.get("image_source"),
                    "image_source_type": enriched.get("image_source_type"),
                    "image_decision_reason": enriched.get("image_decision_reason"),
                    "image_concept": enriched.get("image_concept"),
                    "image_query": enriched.get("image_query"),
                    "image_candidate_id": enriched.get("image_candidate_id"),
                    "image_candidate_url": enriched.get("image_candidate_url"),
                    "image_visual_judge_score": enriched.get("image_visual_judge_score"),
                    "image_accepted_reasons": enriched.get("image_accepted_reasons"),
                    "image_rejected_reasons": enriched.get("image_rejected_reasons"),
                    "image_provider": enriched.get("image_provider"),
                    "image_model": enriched.get("image_model"),
                    "image_prompt_version": enriched.get("image_prompt_version"),
                }
    log(
        "publish: images "
        f"{image_summary['images']}/{image_summary['total']} "
        f"unsplash={image_summary.get('unsplash', 0)} pexels={image_summary.get('pexels', 0)} "
        f"generated={image_summary.get('generated', 0)} category_fallback={image_summary.get('category_fallback', 0)} "
        f"missing={image_summary.get('missing', 0)}"
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
                trace = category_decision_trace(
                    data,
                    publisher_category=effective_category(data.get("article") or {}),
                )
                data["category_trace"] = trace
                log_category_decision_trace(trace)
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


def cmd_category_trace(args: argparse.Namespace) -> int:
    traces = [category_decision_trace(read_queue_record(Path(path))) for path in args.packet]
    print(json.dumps(traces, indent=2, ensure_ascii=False))
    return 1 if args.fail_on_disagreement and any(trace["disagreement"] for trace in traces) else 0


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

    trace = sub.add_parser("category-trace")
    trace.add_argument("packet", nargs="+", help="retained staged packet JSON path")
    trace.add_argument("--fail-on-disagreement", action="store_true")
    trace.set_defaults(func=cmd_category_trace)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
