#!/usr/bin/env python3
"""Report Talous acquisition losses by scan stage and staged queue state."""
from __future__ import annotations

import argparse, hashlib, json, re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_DIR / "pipeline" / "logs" / "staged-scan.log"
STAGED_ROOT = PROJECT_DIR / "pipeline" / "queues" / "staged"
STAGE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\] scan-stage: (?P<stage>[a-z_]+) total=(?P<total>\d+) (?P<kind>categories|buckets)=(?P<data>\{.*\})$")
DROP_RE = re.compile(r"^\[(?P<ts>[^\]]+)\] scan-stage-drop: talous_enqueue_drop (?P<data>\[.*\])$")
RESEARCH_ITEM_RE = re.compile(r"^\[research\] \(\d+/\d+\) (?P<title>.*)$")
RESEARCH_ORIGINAL_RE = re.compile(r"^\[research\]\s+Original: (?P<original>.*)$")
RESEARCH_RESULT_RE = re.compile(r"^\[research\]\s+→ (?P<result>.*)$")


def parse_ts(raw: str) -> datetime:
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def cutoff_for(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def load_scan_runs(log_path: Path, hours: int) -> list[dict]:
    if not log_path.exists():
        return []
    cutoff = cutoff_for(hours)
    runs, current, current_research = [], None, None
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = STAGE_RE.match(line)
        if m:
            ts = parse_ts(m.group("ts"))
            if ts < cutoff:
                current = None
                continue
            stage = m.group("stage")
            if stage == "discovered" or current is None:
                current = {"ts": ts, "stages": {}, "research_items": [], "talous_enqueue_drops": []}
                runs.append(current)
            current["stages"][stage] = {"total": int(m.group("total")), m.group("kind"): json.loads(m.group("data"))}
            current_research = None
            continue
        drop = DROP_RE.match(line)
        if drop:
            ts = parse_ts(drop.group("ts"))
            if ts < cutoff:
                continue
            if current is None:
                current = {"ts": ts, "stages": {}, "research_items": [], "talous_enqueue_drops": []}
                runs.append(current)
            current.setdefault("talous_enqueue_drops", []).extend(json.loads(drop.group("data")))
            continue
        if current is None:
            continue
        item = RESEARCH_ITEM_RE.match(line)
        if item:
            current_research = {"title": item.group("title").strip(), "original": "", "result": ""}
            current["research_items"].append(current_research)
            continue
        if current_research is not None:
            original = RESEARCH_ORIGINAL_RE.match(line)
            if original:
                current_research["original"] = original.group("original").strip(); continue
            result = RESEARCH_RESULT_RE.match(line)
            if result:
                current_research["result"] = result.group("result").strip(); current_research = None
    return runs


def nested_get(data: dict, *path: str):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def article_category(data: dict) -> str:
    packet, original, article, payload = data.get("packet") or {}, data.get("original_article") or {}, data.get("article") or {}, data.get("payload") or {}
    for value in [packet.get("category"), packet.get("category_hint"), original.get("category_hint"), original.get("category"), original.get("_guessed_category"), article.get("category"), payload.get("category")]:
        if value:
            return str(value)
    return "?"


def source_domain(data: dict) -> str:
    packet, original = data.get("packet") or {}, data.get("original_article") or {}
    candidates = (packet.get("source_urls") or []) + [packet.get("link"), original.get("link"), original.get("url")]
    for url in candidates:
        if not url:
            continue
        host = urlparse(str(url)).netloc.lower().removeprefix("www.")
        if host:
            return host
    return str(packet.get("source") or original.get("source") or original.get("source_name") or "unknown").lower()


def source_words(data: dict) -> int:
    diag = nested_get(data, "packet", "source_diagnostics") or {}
    for key in ["selected_source_words", "source_words"]:
        if isinstance(diag.get(key), int):
            return int(diag[key])
    packet = data.get("packet") or {}
    text = packet.get("source_text") or "\n\n".join(str(b.get("text", "")) for b in packet.get("clean_source_blocks") or [])
    return len(str(text).split())


def source_blocks(data: dict) -> int:
    diag = nested_get(data, "packet", "source_diagnostics") or {}
    if isinstance(diag.get("selected_blocks"), int):
        return int(diag["selected_blocks"])
    return len((data.get("packet") or {}).get("clean_source_blocks") or [])


def failure_class(data: dict) -> str:
    failure = data.get("failure") or {}
    if isinstance(failure, dict):
        return str(failure.get("reason") or failure.get("reason_code") or failure.get("message") or "unknown")[:80]
    return str(failure or "unknown")[:80]


def median(values: list[int]) -> int:
    if not values:
        return 0
    values = sorted(values)
    return values[len(values) // 2]


def diagnostic_candidate_id(drop: dict) -> str:
    saved = str(drop.get("candidate_id") or "").strip()
    if saved:
        return saved
    seed = f"{drop.get('title','')}|{drop.get('source','')}"
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:10]


def diagnostic_drop_reason(drop: dict) -> str:
    saved = str(drop.get("drop_reason") or "").strip()
    if saved:
        return saved
    if drop.get("guardrail") == "down_rank_promotional_org_source":
        return "org_source_guardrail_penalty"
    source_words = int(drop.get("source_words") or 0)
    source_blocks = int(drop.get("source_blocks") or 0)
    if source_blocks < 1:
        return "source_floor_no_labeled_source"
    if source_blocks < 2 and source_words < 250:
        return "source_floor_one_block_too_short"
    if not drop.get("reserve_pass"):
        return "reserve_floor_not_met"
    return "queue_cap_displaced_by_stronger_candidates"


def queue_summary(hours: int) -> dict:
    cutoff = cutoff_for(hours)
    summary = {"ready": Counter(), "failed": Counter(), "published": Counter()}
    domains = {"ready": Counter(), "failed": Counter(), "published": Counter()}
    failures, examples, word_stats = Counter(), {"ready": [], "failed": [], "published": []}, defaultdict(list)
    for state in ["ready", "failed", "published"]:
        for path in sorted((STAGED_ROOT / state).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            created_raw = data.get("created_at") or nested_get(data, "packet", "created_at")
            try:
                created = parse_ts(str(created_raw)) if created_raw else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            except Exception:
                created = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if created < cutoff:
                continue
            cat = article_category(data)
            summary[state][cat] += 1
            if cat == "Talous":
                domains[state][source_domain(data)] += 1
                word_stats[state].append(source_words(data))
                if state == "failed":
                    failures[failure_class(data)] += 1
                if len(examples[state]) < 5:
                    pkt = nested_get(data, "packet", "packet_id") or path.stem
                    title = nested_get(data, "packet", "headline_seed") or nested_get(data, "article", "title") or ""
                    examples[state].append(f"{pkt} {source_words(data)}w/{source_blocks(data)}b {source_domain(data)} — {title[:80]}")
    return {"summary": summary, "domains": domains, "failures": failures, "examples": examples, "word_stats": word_stats}


def print_report(runs: list[dict], hours: int, log_path: Path) -> None:
    print(f"Talous acquisition diagnostics: last {hours}h")
    print(f"scan_runs={len(runs)} log={log_path}")
    stage_names = ["discovered", "dedup", "cooldown", "research_candidates", "research_result", "min_source_words_pass", "queued_candidates"]
    totals = {stage: Counter() for stage in stage_names}
    research_buckets, original_buckets, result_buckets, drop_reasons = Counter(), Counter(), Counter(), Counter()
    drop_examples: list[dict] = []
    for run in runs:
        for stage in stage_names:
            info = run["stages"].get(stage) or {}
            if "categories" in info:
                totals[stage]["Talous"] += int(info["categories"].get("Talous", 0)); totals[stage]["total"] += int(info.get("total", 0))
            elif "buckets" in info:
                bucket = info["buckets"].get("Talous", {})
                for k, v in bucket.items(): research_buckets[k] += int(v)
                totals[stage]["Talous"] += sum(int(v) for v in bucket.values()); totals[stage]["total"] += int(info.get("total", 0))
        for item in run.get("research_items", []):
            title = item.get("title", "").lower()
            if any(token in title for token in ["osinko", "salk", "pörss", "tokmanni", "talous", "yrittäj", "sähköauto"]):
                original_buckets[item.get("original") or "unknown"] += 1; result_buckets[item.get("result") or "unknown"] += 1
        for drop in run.get("talous_enqueue_drops", []):
            drop_reasons[diagnostic_drop_reason(drop)] += 1
            if len(drop_examples) < 5:
                drop_examples.append(drop)
    print("\nby_stage_talous:")
    for stage in stage_names:
        c = totals[stage]
        extra = f" buckets={dict(sorted(research_buckets.items()))}" if stage == "research_result" else ""
        print(f"  {stage}: talous={c['Talous']} all={c['total']}{extra}")
    print("\nlikely_talous_research_log_clues:")
    print(f"  original={dict(original_buckets.most_common(6))}")
    print(f"  result={dict(result_buckets.most_common(6))}")
    q = queue_summary(hours)
    print("\nstaged_queue_talous:")
    for state in ["ready", "failed", "published"]:
        count = q["summary"][state].get("Talous", 0); words = q["word_stats"][state]
        print(f"  {state}: talous={count} median_source_words={median(words)} top_domains={dict(q['domains'][state].most_common(6))}")
    print(f"  failed_classes={dict(q['failures'].most_common(8))}")
    passed = totals["min_source_words_pass"]["Talous"]
    queued = totals["queued_candidates"]["Talous"]
    conversion = (queued / passed * 100.0) if passed else 0.0
    print(f"  source_pass_to_queue_conversion={queued}/{passed} ({conversion:.1f}%)")
    if passed and queued < passed:
        print(f"  conversion_gap_note=scan enqueue is capped by --max-packets per run; excess source-passing Talous candidates are expected to wait behind queue caps/dedup/cooldown, not disappear at research acquisition")
    print("\ntalous_enqueue_drops:")
    print(f"  drop_reasons={dict(drop_reasons.most_common(8))}")
    for drop in drop_examples:
        print(
            "  - "
            f"candidate_id={diagnostic_candidate_id(drop)} "
            f"title={str(drop.get('title',''))[:80]} "
            f"source={drop.get('source','')} "
            f"source_words={drop.get('source_words',0)} "
            f"source_blocks={drop.get('source_blocks',0)} "
            f"guardrail={drop.get('guardrail','')} "
            f"reserve_pass={drop.get('reserve_pass')} "
            f"drop_reason={diagnostic_drop_reason(drop)}"
        )
    print("\nexamples:")
    for state in ["ready", "failed", "published"]:
        print(f"  {state}:")
        for ex in q["examples"][state]: print(f"    - {ex}")
    print("\nrecommendation: next OPE-70 fix should target Talous research acquisition/search enrichment before queue reserve/worker priority. Recent scans repeatedly lose Talous at research_result/min_source_words_pass, usually as research_fallback/empty from blocked or thin originals.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--log", type=Path, default=LOG_PATH)
    args = ap.parse_args()
    print_report(load_scan_runs(args.log, args.hours), args.hours, args.log)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
