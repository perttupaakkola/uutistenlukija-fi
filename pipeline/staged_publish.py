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
from monica_writer import (  # noqa: E402
    _build_prompt,
    _basic_payload_issues,
    _extract_json_object,
    _merge_article,
    _normalize_ws,
    _run_monica,
)
from quality_gate import run_gate as run_quality_gate  # noqa: E402


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


def source_strength(article: dict) -> tuple[int, int, int, int]:
    research = str(article.get("research") or article.get("research_text") or "")
    desc = str(article.get("description") or "")
    source_blocks = research.lower().count("[lähde:") + research.lower().count("[source:")
    tier_score = max(0, 4 - int(article.get("source_tier", 2) or 2))
    return (len(research.split()), source_blocks, len(desc.split()), tier_score)


def cmd_scan(args: argparse.Namespace) -> int:
    start = time.time()
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
    if not articles:
        return 0

    pre = len(articles)
    articles = filter_new_articles(articles)
    if articles:
        articles = check_published_duplicates(articles, window_hours=args.dedup_window)
    if articles:
        articles = dedup_within_batch(articles)
    log(f"scan: dedup {pre}->{len(articles)}")
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
    if not articles:
        return 0

    if args.max_research_candidates and len(articles) > args.max_research_candidates:
        articles = articles[: args.max_research_candidates]
    articles = enrich_with_research(articles)
    articles = [a for a in articles if total_source_words(a) >= args.min_source_words]
    articles = sorted(articles, key=source_strength, reverse=True)
    articles = articles[: args.max_packets]

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
        issues = _basic_payload_issues(payload)
        if issues:
            data.update({"failed_at": datetime.now(timezone.utc).isoformat(), "failure": "; ".join(issues), "payload": payload, "raw_response": raw})
            atomic_write_json(STAGED_ROOT / "failed" / writing.name, data)
            writing.unlink(missing_ok=True)
            return ("failed", "; ".join(issues))
        article = _merge_article(original, packet, payload)
        out = {
            **data,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "raw_response": raw,
            "article": article,
        }
        atomic_write_json(STAGED_ROOT / "outbox" / writing.name, out)
        writing.unlink(missing_ok=True)
        return ("ok", article.get("title", "")[:100])
    except Exception as e:
        data.update({"failed_at": datetime.now(timezone.utc).isoformat(), "failure": str(e), "raw_response": raw})
        atomic_write_json(STAGED_ROOT / "failed" / writing.name, data)
        writing.unlink(missing_ok=True)
        return ("failed", str(e)[:200])


def cmd_monica_worker(args: argparse.Namespace) -> int:
    ready = sorted((STAGED_ROOT / "ready").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not ready:
        log("monica-worker: no ready packets")
        return 0
    processed = 0
    for path in ready[: args.max_packets]:
        log(f"monica-worker: processing {path.name}")
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


def run_git_deploy(created_count: int) -> int:
    if created_count <= 0:
        return 0
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
    articles = gate.passed
    if not articles:
        log(f"publish: all articles rejected by quality gate rejected={len(gate.rejected)}")
        return 1
    articles = check_published_duplicates(articles, window_hours=args.dedup_window)
    articles = dedup_within_batch(articles)
    if not articles:
        log("publish: all articles dropped as duplicates")
        return 0
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


def cmd_status(args: argparse.Namespace) -> int:
    status: dict[str, Any] = {}
    for box in ["ready", "writing", "outbox", "published", "failed"]:
        files = list((STAGED_ROOT / box).glob("*.json"))
        status[box] = {"count": len(files), "size_bytes": sum(p.stat().st_size for p in files)}
    print(json.dumps(status, indent=2))
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
    scan.add_argument("--dry-run", action="store_true")
    scan.set_defaults(func=cmd_scan)

    worker = sub.add_parser("monica-worker")
    worker.add_argument("--max-packets", type=int, default=1)
    worker.set_defaults(func=cmd_monica_worker)

    pub = sub.add_parser("publish")
    pub.add_argument("--max-articles", type=int, default=2)
    pub.add_argument("--dedup-window", type=int, default=48)
    pub.add_argument("--git-push", action="store_true")
    pub.add_argument("--dry-run", action="store_true")
    pub.set_defaults(func=cmd_publish)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
