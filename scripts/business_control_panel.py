#!/usr/bin/env python3
"""Build a safe machine-readable KPI/control panel from production truth.

Operator-facing pipeline values come from a bounded unauthenticated public
status response. Local files remain explicit diagnostics. No credentials are
read or printed. Intended for cron/manual use:

    python3 scripts/business_control_panel.py
    python3 scripts/business_control_panel.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONTENT_DIR = PROJECT_DIR / "content" / "posts"
PIPELINE_DIR = PROJECT_DIR / "pipeline"
LOG_DIR = PIPELINE_DIR / "logs"
QUEUE_DIR = PIPELINE_DIR / "queues"
DEFAULT_OUTPUTS = [
    PROJECT_DIR / "static" / "api" / "business-control-panel.json",
    PROJECT_DIR / "public" / "api" / "business-control-panel.json",
]

SECRETISH_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|bearer|client[_-]?secret)\s*[:=]\s*[^\s,;]+"
)
URL_QUERY_RE = re.compile(r"https?://[^\s]+")
PRODUCTION_PIPELINE_STATUS_URL = "https://uutistenlukija.fi/api/pipeline-status.json"
PRODUCTION_PIPELINE_STATUS_TIMEOUT_SECONDS = 5
PRODUCTION_PIPELINE_STATUS_MAX_BYTES = 256 * 1024
PRODUCTION_PIPELINE_STATUS_MAX_AGE_MINUTES = 90
PRODUCTION_PIPELINE_STATUS_FUTURE_TOLERANCE_MINUTES = 5


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (ValueError, OSError):
            return None
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return None
    # Common frontmatter/log variants.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_minutes(dt: datetime | None, now: datetime) -> float | None:
    if not dt:
        return None
    return round(max(0.0, (now - dt).total_seconds() / 60), 1)


def safe_read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def sanitize_reason(reason: Any) -> str:
    text = str(reason or "unknown").replace("\n", " ").replace("\r", " ").strip()
    text = SECRETISH_RE.sub(lambda m: m.group(1) + "=<redacted>", text)
    text = URL_QUERY_RE.sub(lambda m: m.group(0).split("?", 1)[0], text)
    text = re.sub(r"\s+", " ", text)
    return text[:180] or "unknown"


def _production_evidence_failure(
    now: datetime,
    evidence_status: str,
    reason: str,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "evidence_status": evidence_status,
        "fresh": False,
        "reason": sanitize_reason(reason),
        "source": PRODUCTION_PIPELINE_STATUS_URL,
        "checked_at": iso(now),
        "generated_at": iso(generated_at),
        "age_minutes": age_minutes(generated_at, now),
        "pipeline_status": None,
        "published_last_24h": None,
        "last_publish_at": None,
        "last_publish_age_minutes": None,
        "staged_queue_runway": None,
    }


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_production_pipeline_status(
    payload: Any,
    now: datetime,
    source_url: str,
) -> dict[str, Any]:
    """Validate and normalize the public pipeline status without trusting it blindly."""
    try:
        parsed_url = urlsplit(str(source_url or ""))
        response_port = parsed_url.port
    except (TypeError, ValueError):
        return _production_evidence_failure(now, "invalid", "production response URL is invalid")
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "uutistenlukija.fi"
        or response_port not in (None, 443)
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path != "/api/pipeline-status.json"
        or parsed_url.query
        or parsed_url.fragment
    ):
        return _production_evidence_failure(now, "invalid", "production response came from the wrong site or path")
    if not isinstance(payload, dict):
        return _production_evidence_failure(now, "invalid", "production response root is not an object")
    if payload.get("site") not in (None, "uutistenlukija.fi"):
        return _production_evidence_failure(now, "invalid", "production response declares the wrong site")
    if payload.get("hours") != 24:
        return _production_evidence_failure(now, "invalid", "production response is not a 24-hour status")

    generated_at = parse_dt(payload.get("generated_at"))
    if generated_at is None:
        return _production_evidence_failure(now, "invalid", "production generated_at is missing or invalid")

    def fail(evidence_status: str, reason: str) -> dict[str, Any]:
        return _production_evidence_failure(
            now,
            evidence_status,
            reason,
            generated_at=generated_at,
        )

    if generated_at > now + timedelta(minutes=PRODUCTION_PIPELINE_STATUS_FUTURE_TOLERANCE_MINUTES):
        return fail("invalid", "production generated_at is implausibly in the future")

    stale_threshold = payload.get("stale_threshold_minutes")
    if not _is_nonnegative_int(stale_threshold) or stale_threshold == 0:
        return fail("invalid", "production stale threshold is missing or invalid")
    response_age_minutes = (now - generated_at).total_seconds() / 60
    max_age_minutes = min(PRODUCTION_PIPELINE_STATUS_MAX_AGE_MINUTES, stale_threshold)
    if response_age_minutes > max_age_minutes:
        return fail("stale", f"production response is older than {max_age_minutes} minutes")

    pipeline_status = payload.get("status")
    is_stale = payload.get("is_stale")
    if pipeline_status not in {"ok", "degraded"} or not isinstance(is_stale, bool):
        return fail("invalid", "production status fields are missing or invalid")
    if (pipeline_status == "ok" and is_stale) or (pipeline_status == "degraded" and not is_stale):
        return fail("contradictory", "production status and stale flag contradict each other")
    if is_stale:
        return fail("stale", "production pipeline reports stale evidence")

    articles = payload.get("articles")
    if not isinstance(articles, dict) or not _is_nonnegative_int(articles.get("published")):
        return fail("invalid", "production article counts are missing or invalid")
    last_published = parse_dt(articles.get("last_published_ts"))
    if last_published is None:
        return fail("invalid", "production last-publish timestamp is missing or invalid")
    future_tolerance = timedelta(minutes=PRODUCTION_PIPELINE_STATUS_FUTURE_TOLERANCE_MINUTES)
    if last_published > now + future_tolerance or last_published > generated_at + future_tolerance:
        return fail("contradictory", "production last-publish timestamp is later than its status snapshot")
    publication_window = generated_at - timedelta(hours=24) - future_tolerance
    if articles["published"] > 0 and last_published < publication_window:
        return fail("contradictory", "production published count contradicts its last-publish timestamp")

    runway = payload.get("stagedQueueRunway")
    if not isinstance(runway, dict):
        return fail("invalid", "production staged runway is missing")
    count_keys = ("readyCount", "writingCount", "outboxCount", "worstCaseRemainingCycles")
    bool_keys = ("publisherEnabled", "scannerEnabled", "workerEnabled")
    if any(not _is_nonnegative_int(runway.get(key)) for key in count_keys):
        return fail("invalid", "production staged runway counts are invalid")
    if any(not isinstance(runway.get(key), bool) for key in bool_keys):
        return fail("invalid", "production staged runway markers are invalid")
    max_packets = runway.get("maxPacketsPerCycle")
    if not _is_nonnegative_int(max_packets) or max_packets == 0:
        return fail("invalid", "production staged cycle cap is invalid")
    replenishment = runway.get("replenishmentState")
    severity = runway.get("severity")
    reasons = runway.get("reasons")
    if not isinstance(replenishment, str) or not replenishment:
        return fail("invalid", "production replenishment state is invalid")
    if severity not in {"ok", "warning", "critical", "inactive"}:
        return fail("invalid", "production staged severity is invalid")
    if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
        return fail("invalid", "production staged reasons are invalid")

    expected_cycles = (runway["outboxCount"] + max_packets - 1) // max_packets
    publisher_enabled = runway["publisherEnabled"]
    scanner_enabled = runway["scannerEnabled"]
    worker_enabled = runway["workerEnabled"]
    all_enabled = publisher_enabled and scanner_enabled and worker_enabled
    if runway["worstCaseRemainingCycles"] != expected_cycles:
        return fail("contradictory", "production staged cycle count contradicts outbox depth")
    if all_enabled:
        expected_replenishment = "end_to_end_enabled"
    elif scanner_enabled and worker_enabled:
        expected_replenishment = "scanner_worker_enabled_publisher_disabled"
    elif scanner_enabled:
        expected_replenishment = "scanner_enabled_writer_unverified"
    elif worker_enabled:
        expected_replenishment = "worker_enabled_scanner_disabled"
    else:
        expected_replenishment = "disabled"
    if replenishment != expected_replenishment:
        return fail("contradictory", "production staged replenishment contradicts marker state")
    if runway["writingCount"] > 1:
        expected_severity = "critical"
    elif not publisher_enabled:
        expected_severity = "inactive"
    elif scanner_enabled and worker_enabled:
        expected_severity = "ok"
    elif runway["outboxCount"] <= 6:
        expected_severity = "critical"
    elif runway["outboxCount"] <= 12:
        expected_severity = "warning"
    else:
        expected_severity = "ok"
    if severity != expected_severity:
        return fail("contradictory", "production staged severity contradicts queue and marker state")

    normalized_runway = {
        **{key: runway[key] for key in count_keys},
        **{key: runway[key] for key in bool_keys},
        "maxPacketsPerCycle": max_packets,
        "replenishmentState": replenishment,
        "severity": severity,
        "reasons": [sanitize_reason(reason) for reason in reasons[:20]],
    }
    return {
        "evidence_status": "validated",
        "fresh": True,
        "reason": "validated fresh production pipeline status",
        "source": PRODUCTION_PIPELINE_STATUS_URL,
        "checked_at": iso(now),
        "generated_at": iso(generated_at),
        "age_minutes": age_minutes(generated_at, now),
        "pipeline_status": pipeline_status,
        "published_last_24h": articles["published"],
        "last_publish_at": iso(last_published),
        "last_publish_age_minutes": age_minutes(last_published, now),
        "staged_queue_runway": normalized_runway,
    }


def production_pipeline_status(now: datetime | None = None) -> dict[str, Any]:
    """Fetch one bounded unauthenticated production status response."""
    now = now or utcnow()
    request = Request(
        PRODUCTION_PIPELINE_STATUS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "uutistenlukija-business-control-panel/1.0",
        },
    )
    try:
        with urlopen(request, timeout=PRODUCTION_PIPELINE_STATUS_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            raw = response.read(PRODUCTION_PIPELINE_STATUS_MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return _production_evidence_failure(now, "unavailable", f"production status fetch failed: {exc}")
    if len(raw) > PRODUCTION_PIPELINE_STATUS_MAX_BYTES:
        return _production_evidence_failure(now, "invalid", "production response exceeds the byte limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _production_evidence_failure(now, "invalid", "production response is not valid JSON")
    return validate_production_pipeline_status(payload, now, final_url)


def _read_git(repo_dir: Path, *args: str) -> str | None:
    """Run one bounded local Git read without fetching or taking optional locks."""
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_upstream_freshness(repo_dir: Path) -> dict[str, Any]:
    """Assess HEAD against its configured upstream using local Git metadata only."""
    result: dict[str, Any] = {
        "status": "unknown",
        "fresh": None,
        "reason": "Git freshness could not be determined",
        "head": None,
        "upstream": None,
        "upstream_head": None,
        "behind_count": None,
        "ahead_count": None,
        "source": "read-only local Git metadata; no fetch or network access",
    }
    if not repo_dir.is_dir():
        result["reason"] = "project path is missing or not a directory"
        return result
    if _read_git(repo_dir, "rev-parse", "--is-inside-work-tree") != "true":
        result["reason"] = "project path is not a Git worktree"
        return result

    head = _read_git(repo_dir, "rev-parse", "--verify", "HEAD^{commit}")
    if not head:
        result["reason"] = "Git HEAD is missing or unresolvable"
        return result
    result["head"] = head

    upstream = _read_git(
        repo_dir,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    if not upstream:
        result["reason"] = "configured upstream is missing or unresolvable"
        return result
    result["upstream"] = upstream

    upstream_head = _read_git(
        repo_dir,
        "rev-parse",
        "--verify",
        "@{upstream}^{commit}",
    )
    if not upstream_head:
        result["reason"] = "configured upstream commit is missing or unresolvable"
        return result
    result["upstream_head"] = upstream_head

    if head == upstream_head:
        result.update({
            "status": "fresh",
            "fresh": True,
            "reason": f"HEAD matches configured upstream {upstream}",
            "behind_count": 0,
            "ahead_count": 0,
        })
        return result

    counts = _read_git(
        repo_dir,
        "rev-list",
        "--left-right",
        "--count",
        "HEAD...@{upstream}",
    )
    try:
        ahead_count, behind_count = (int(value) for value in (counts or "").split())
    except (TypeError, ValueError):
        result["reason"] = "HEAD relationship to configured upstream is unresolvable"
        return result
    result["ahead_count"] = ahead_count
    result["behind_count"] = behind_count
    if behind_count > 0:
        result.update({
            "status": "stale",
            "fresh": False,
            "reason": f"HEAD is {behind_count} commit(s) behind configured upstream {upstream}",
        })
        return result

    result["reason"] = "HEAD differs from configured upstream without a positive behind count"
    return result


def extract_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm: dict[str, str] = {}
    current_key = ""
    for raw in parts[1].splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_key:
            item = line[4:].strip().strip('"')
            if item and not fm.get(current_key):
                fm[current_key] = item
            continue
        if ":" in line and not line.startswith(" "):
            key, val = line.split(":", 1)
            current_key = key.strip()
            fm[current_key] = val.strip().strip('"').strip("'")
    return fm


def frontmatter_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "yes", "on", "1"}


def content_summary(now: datetime) -> dict[str, Any]:
    posts = sorted(CONTENT_DIR.glob("*.md")) if CONTENT_DIR.exists() else []
    latest: tuple[datetime, Path, dict[str, str]] | None = None
    draft_count = 0
    published_24h = 0
    cutoff = now - timedelta(hours=24)
    for path in posts:
        fm = extract_frontmatter(path)
        if frontmatter_truthy(fm.get("draft")):
            draft_count += 1
            continue
        dt = parse_dt(fm.get("date") or fm.get("published_at"))
        if dt and dt >= cutoff:
            published_24h += 1
        if dt and (latest is None or dt > latest[0]):
            latest = (dt, path, fm)
    latest_dt = latest[0] if latest else None
    return {
        "article_count_local": len(posts) - draft_count,
        "draft_count_local": draft_count,
        "published_last_24h_local": published_24h,
        "last_publish_at": iso(latest_dt),
        "last_publish_age_minutes": age_minutes(latest_dt, now),
        "latest_article": {
            "slug": latest[1].stem if latest else None,
            "title": (latest[2].get("title") or None) if latest else None,
            "category": (latest[2].get("categories") or latest[2].get("category") or None) if latest else None,
        },
        "source": "content/posts frontmatter",
    }


def load_pipeline_metrics() -> list[dict[str, Any]]:
    path = LOG_DIR / "metrics.json"
    data = safe_read_json(path)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def pipeline_summary(now: datetime) -> dict[str, Any]:
    rows = load_pipeline_metrics()
    cutoff = now - timedelta(hours=24)
    recent: list[dict[str, Any]] = []
    all_with_dt: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        dt = parse_dt(row.get("timestamp") or row.get("generated_at") or row.get("ts"))
        if not dt:
            continue
        all_with_dt.append((dt, row))
        if dt >= cutoff:
            recent.append(row)
    success_count = sum(1 for r in recent if bool(r.get("success")) is True)
    failure_count = sum(1 for r in recent if bool(r.get("success")) is False)
    skipped_count = sum(1 for r in recent if r.get("skipped") or r.get("status") == "skip")
    error_counter: Counter[str] = Counter()
    for row in recent:
        errors = row.get("errors") or row.get("error") or []
        if isinstance(errors, str):
            errors = [errors]
        if isinstance(errors, list):
            for err in errors:
                error_counter[sanitize_reason(err)] += 1
        if not errors and bool(row.get("success")) is False:
            # Use failed/zero-output step names as a compact actionable reason.
            steps = row.get("steps") if isinstance(row.get("steps"), dict) else {}
            reasons = []
            for name, details in steps.items():
                if isinstance(details, dict) and details.get("success") is False:
                    reasons.append(f"step failed: {name}")
                if name == "rewriter" and isinstance(details, dict) and details.get("output_count") == 0:
                    reasons.append("rewriter output_count=0")
            for reason in reasons or ["run failed without explicit error"]:
                error_counter[sanitize_reason(reason)] += 1
    latest_dt, latest_row = max(all_with_dt, default=(None, {}), key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))
    status = safe_read_json(PROJECT_DIR / "static" / "api" / "pipeline-status.json") or safe_read_json(PROJECT_DIR / "public" / "api" / "pipeline-status.json") or {}
    return {
        "source": "pipeline/logs/metrics.json plus static/public pipeline-status.json if present",
        "metrics_rows_total": len(rows),
        "last_run_at": iso(latest_dt),
        "last_run_age_minutes": age_minutes(latest_dt, now),
        "last_run_success": latest_row.get("success") if latest_row else None,
        "last_run_article_count": latest_row.get("article_count") if latest_row else None,
        "last_24h": {
            "runs_total": len(recent),
            "success": success_count,
            "failure": failure_count,
            "skipped": skipped_count,
            "article_count": sum(int(r.get("article_count") or 0) for r in recent),
            "top_error_reasons": [{"reason": k, "count": v} for k, v in error_counter.most_common(10)],
        },
        "published_status_snapshot": status if isinstance(status, dict) else {},
    }


def queue_summary(now: datetime) -> dict[str, Any]:
    queues: dict[str, Any] = {}
    if not QUEUE_DIR.exists():
        return {"source": "pipeline/queues", "queues": queues}
    for root, dirs, files in os.walk(QUEUE_DIR):
        # Queue retention moves old artifacts into reversible archive folders.
        # Those files are useful evidence, but they are no longer live backlog;
        # do not let archive manifests make the operator panel look backed up.
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and d != "__pycache__"
            and d not in {"archive", "archives", "manifests"}
            and not d.endswith("_archive")
        ]
        json_files = [Path(root) / f for f in files if f.endswith(".json")]
        if not json_files:
            continue
        rel = str(Path(root).relative_to(QUEUE_DIR))
        mtimes = []
        for p in json_files:
            try:
                mtimes.append(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
            except OSError:
                pass
        oldest = min(mtimes) if mtimes else None
        newest = max(mtimes) if mtimes else None
        queues[rel] = {
            "count": len(json_files),
            "oldest_item_age_minutes": age_minutes(oldest, now),
            "newest_item_age_minutes": age_minutes(newest, now),
        }
    return {"source": "pipeline/queues/*.json file counts only", "queues": dict(sorted(queues.items()))}


def newest_existing_json(paths: list[Path]) -> tuple[Path | None, dict[str, Any] | None]:
    existing = [p for p in paths if p.exists()]
    if not existing:
        return None, None
    newest = max(existing, key=lambda p: p.stat().st_mtime)
    data = safe_read_json(newest)
    return newest, data if isinstance(data, dict) else None


def category_drift() -> dict[str, Any]:
    path, data = newest_existing_json([
        PROJECT_DIR / "static" / "api" / "category-stats.json",
        PROJECT_DIR / "public" / "api" / "category-stats.json",
    ])
    if not data:
        return {"available": False, "source": None, "alerts": []}
    categories = data.get("categories") if isinstance(data.get("categories"), list) else []
    drift = []
    for c in categories:
        if not isinstance(c, dict):
            continue
        drift.append({
            "category": c.get("category"),
            "count": c.get("count"),
            "pct": c.get("pct"),
            "target_pct": c.get("target_pct"),
            "delta": c.get("delta"),
            "status": c.get("status"),
        })
    return {
        "available": True,
        "source": str(path.relative_to(PROJECT_DIR)) if path else None,
        "generated_at": data.get("generated_at"),
        "total_articles": data.get("total_articles"),
        "alerts": data.get("alerts", []),
        "categories": drift,
    }


def analytics_status(now: datetime) -> dict[str, Any]:
    """Report local analytics data freshness; never calls GA4/GSC or reads tokens."""
    ctr_path, ctr = newest_existing_json([
        PROJECT_DIR / "static" / "api" / "ctr-gap-report.json",
        PROJECT_DIR / "public" / "api" / "ctr-gap-report.json",
    ])
    freshness_path, freshness = newest_existing_json([
        PROJECT_DIR / "static" / "api" / "analytics-freshness-status.json",
        PROJECT_DIR / "analytics" / "post-reauth-freshness-evidence.json",
    ])
    traffic_log = LOG_DIR / "daily-traffic-card.log"
    weekly_log = LOG_DIR / "weekly-metrics-digest.log"
    gsc_log = LOG_DIR / "fetch-search-console.log"

    gsc_source = ctr.get("data_source") if ctr else None
    gsc_generated = parse_dt(ctr.get("generated_at") if ctr else None)
    gsc_blocked = gsc_source in (None, "frontmatter_synthetic", "frontmatter")
    gsc_reason = "no local GSC export; CTR gap report uses frontmatter fallback" if gsc_blocked else "local GSC-derived report present"

    def log_probe(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"exists": False, "age_minutes": None, "status": "missing"}
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            tail = path.read_text(encoding="utf-8", errors="replace")[-4000:].lower()
        except Exception:
            return {"exists": True, "age_minutes": None, "status": "unreadable"}
        has_error = any(term in tail for term in ["error", "failed", "not found", "no access_token", "cannot run"])
        return {"exists": True, "age_minutes": age_minutes(mtime, now), "status": "error_seen" if has_error else "log_present"}

    traffic_log_probe = log_probe(traffic_log)
    weekly_log_probe = log_probe(weekly_log)
    gsc_log_probe = log_probe(gsc_log)

    def artifact_summary(payload: Any, keys: list[str]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        return {key: payload.get(key) for key in keys if key in payload}

    freshness_payload: dict[str, Any] = freshness if isinstance(freshness, dict) else {}
    raw_artifacts = freshness_payload.get("artifacts")
    artifacts: dict[str, Any] = raw_artifacts if isinstance(raw_artifacts, dict) else {}
    raw_daily_artifact = artifacts.get("daily_report")
    raw_search_artifact = artifacts.get("search_console")
    raw_oauth_artifact = artifacts.get("oauth_blocker")
    daily_artifact: dict[str, Any] = raw_daily_artifact if isinstance(raw_daily_artifact, dict) else {}
    search_artifact: dict[str, Any] = raw_search_artifact if isinstance(raw_search_artifact, dict) else {}
    oauth_artifact: dict[str, Any] = raw_oauth_artifact if isinstance(raw_oauth_artifact, dict) else {}
    freshness_status = freshness_payload.get("status") if freshness_payload else None
    freshness_checked_at = freshness_payload.get("checked_at") if freshness_payload else None
    source_command = freshness_payload.get("source_command") if freshness_payload else None
    freshness_summary = {
        "source": str(freshness_path.relative_to(PROJECT_DIR)) if freshness_path and freshness_path.is_relative_to(PROJECT_DIR) else None,
        "status": freshness_status or "missing",
        "checked_at": freshness_checked_at,
        "age_minutes": age_minutes(parse_dt(freshness_checked_at), now),
        "source_command": sanitize_reason(source_command) if source_command else None,
        "blocked_by": freshness_payload.get("blocked_by") if freshness_payload else None,
        "daily_report": artifact_summary(daily_artifact, ["artifact", "fresh", "property_id", "site", "counts", "age_hours", "evidence_at"]),
        "search_console": artifact_summary(search_artifact, ["artifact", "fresh", "site", "days", "row_count", "age_hours", "evidence_at"]),
        "oauth_blocker": artifact_summary(oauth_artifact, ["blocked", "superseded_by_fresh_validation", "blocked_by", "services"]),
    }

    if freshness_status == "fresh" and daily_artifact.get("fresh") and search_artifact.get("fresh"):
        for probe in (traffic_log_probe, weekly_log_probe, gsc_log_probe):
            if probe.get("status") == "error_seen":
                probe["superseded_by_freshness_status"] = True
        return {
            "source": "redacted local analytics freshness artifact plus public/static reports; external analytics APIs not queried by this script",
            "freshness": freshness_summary,
            "ga4": {
                "status": "fresh",
                "reason": "fresh GA4 validation artifact present",
                "daily_report": freshness_summary["daily_report"],
                "daily_traffic_log": traffic_log_probe,
                "weekly_metrics_log": weekly_log_probe,
            },
            "gsc": {
                "status": "fresh",
                "reason": "fresh Search Console validation artifact present",
                "search_console_report": freshness_summary["search_console"],
                "ctr_gap_report": {
                    "source": str(ctr_path.relative_to(PROJECT_DIR)) if ctr_path else None,
                    "generated_at": iso(gsc_generated),
                    "age_minutes": age_minutes(gsc_generated, now),
                    "data_source": gsc_source,
                    "total_gaps_found": ctr.get("total_gaps_found") if ctr else None,
                },
                "fetch_log": gsc_log_probe,
            },
        }

    if freshness_status == "blocked_oauth_reauthorization_required" or bool(oauth_artifact.get("blocked")):
        blocked_reason = "OAuth reauthorization required by latest analytics freshness artifact"
        return {
            "source": "redacted local analytics freshness artifact plus public/static reports; external analytics APIs not queried by this script",
            "freshness": freshness_summary,
            "ga4": {
                "status": "blocked",
                "reason": blocked_reason,
                "daily_report": freshness_summary["daily_report"],
                "daily_traffic_log": traffic_log_probe,
                "weekly_metrics_log": weekly_log_probe,
            },
            "gsc": {
                "status": "blocked",
                "reason": blocked_reason,
                "search_console_report": freshness_summary["search_console"],
                "ctr_gap_report": {
                    "source": str(ctr_path.relative_to(PROJECT_DIR)) if ctr_path else None,
                    "generated_at": iso(gsc_generated),
                    "age_minutes": age_minutes(gsc_generated, now),
                    "data_source": gsc_source,
                    "total_gaps_found": ctr.get("total_gaps_found") if ctr else None,
                },
                "fetch_log": gsc_log_probe,
            },
        }

    return {
        "source": "local public/static reports and pipeline/logs only; external analytics APIs not queried",
        "freshness": freshness_summary,
        "ga4": {
            "status": "stale_or_incomplete" if freshness_status else "blocked_or_unknown",
            "reason": "no fresh GA4 validation artifact present; see local GA4 cron logs for last known state",
            "daily_report": freshness_summary["daily_report"],
            "daily_traffic_log": traffic_log_probe,
            "weekly_metrics_log": weekly_log_probe,
        },
        "gsc": {
            "status": "stale_or_incomplete" if freshness_status else ("blocked" if gsc_blocked else "local_report_present"),
            "reason": "no fresh Search Console validation artifact present" if freshness_status else gsc_reason,
            "search_console_report": freshness_summary["search_console"],
            "ctr_gap_report": {
                "source": str(ctr_path.relative_to(PROJECT_DIR)) if ctr_path else None,
                "generated_at": iso(gsc_generated),
                "age_minutes": age_minutes(gsc_generated, now),
                "data_source": gsc_source,
                "total_gaps_found": ctr.get("total_gaps_found") if ctr else None,
            },
            "fetch_log": gsc_log_probe,
        },
    }



def parse_hugo_params(path: Path) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if not path.exists():
        return params
    in_params = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return params
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            in_params = line == "[params]"
            continue
        if not in_params or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if value.lower() in {"true", "false"}:
            params[key] = value.lower() == "true"
        else:
            params[key] = value.strip('"').strip("'")
    return params


def effective_ad_config(params: dict[str, Any]) -> dict[str, Any]:
    """Mirror the Hugo ad-config gate from the same public config values."""
    immutable_activation_floor = 3
    feature_flag = params.get("ads_enabled") is True
    provider_configured = bool(str(params.get("adsense_id") or "").strip())
    try:
        configured_consent_revision = int(params.get("ads_consent_revision", 2))
    except (TypeError, ValueError):
        configured_consent_revision = 0
    try:
        activation_revision = int(
            params.get("ads_activation_revision", immutable_activation_floor)
        )
    except (TypeError, ValueError):
        activation_revision = 0

    activation_requested = feature_flag and provider_configured
    activation_floor_valid = activation_revision >= immutable_activation_floor
    consent_revision = (
        max(configured_consent_revision, immutable_activation_floor)
        if activation_requested
        else 2
    )
    revision_current = (
        configured_consent_revision >= immutable_activation_floor
        and configured_consent_revision >= activation_revision
    )
    effective = activation_requested and activation_floor_valid and revision_current
    if not feature_flag:
        reason = "ads feature flag disabled"
    elif not provider_configured:
        reason = "provider ID missing"
    elif not activation_floor_valid:
        reason = "activation revision is below immutable dormant-safe floor 3"
    elif not revision_current:
        reason = "consent revision is below the activation revision or immutable floor 3"
    else:
        reason = "server gate eligible; client still requires current explicit advertising consent"

    return {
        "effective_ads_enabled": effective,
        "feature_flag": feature_flag,
        "provider_configured": provider_configured,
        "consent_revision": consent_revision,
        "configured_consent_revision": configured_consent_revision,
        "activation_revision": activation_revision,
        "immutable_activation_floor": immutable_activation_floor,
        "activation_requested": activation_requested,
        "activation_floor_valid": activation_floor_valid,
        "revision_current": revision_current,
        "reason": reason,
    }


def monetization_status() -> dict[str, Any]:
    params = parse_hugo_params(PROJECT_DIR / "hugo.toml")
    mainosta = PROJECT_DIR / "layouts" / "_default" / "mainosta.html"
    advertiser_cta = PROJECT_DIR / "layouts" / "partials" / "advertiser-cta.html"
    tracking = PROJECT_DIR / "layouts" / "partials" / "event-tracking.html"
    files = [mainosta, advertiser_cta, tracking]

    tracked_files = []
    tracked_signal_count = 0
    for path in files:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        count = text.count("data-monetization-signal") + text.count("monetization_signal")
        if count:
            tracked_files.append(str(path.relative_to(PROJECT_DIR)))
            tracked_signal_count += count

    ad_config = effective_ad_config(params)
    return {
        "status": "lead_capture_tracking_active" if tracked_signal_count else "not_tracked",
        "safe_public": True,
        "monthly_euros": 0,
        "source": "hugo.toml centralized ad gate + monetization CTA markup; no ad network or personal data required",
        "ads_enabled": ad_config["effective_ads_enabled"],
        "ads_feature_flag": ad_config["feature_flag"],
        "adsense_configured": ad_config["provider_configured"],
        "ads_consent_revision": ad_config["consent_revision"],
        "ads_activation_revision": ad_config["activation_revision"],
        "ads_gate_reason": ad_config["reason"],
        "experiment": {
            "id": "advertiser-lead-cta-v1",
            "primary_metric": "monetization_signal events",
            "secondary_metrics": ["advertise_cta_click", "advertise_email_click"],
            "target": "first qualified advertiser inquiry",
            "tracking_storage": "anonymous localStorage counter plus GA4 event when analytics consent is granted",
            "tracked_signal_markers": tracked_signal_count,
            "tracked_files": tracked_files,
        },
    }

def inferred_workspace_dir() -> Path:
    """Return the OpenClaw workspace root for a project checkout."""
    if PROJECT_DIR.parent.name == "projects":
        return PROJECT_DIR.parent.parent
    return PROJECT_DIR


def display_path(path: Path) -> str:
    """Expose non-secret operator paths without absolute home details."""
    workspace_dir = inferred_workspace_dir()
    for label, root in (("project", PROJECT_DIR), ("workspace", workspace_dir)):
        try:
            return f"{label}:{path.relative_to(root)}"
        except ValueError:
            continue
    return path.name


def labels_from_issue(issue: dict[str, Any]) -> list[str]:
    raw_labels = issue.get("labels") or []
    labels: list[str] = []
    if isinstance(raw_labels, list):
        for label in raw_labels:
            if isinstance(label, str):
                labels.append(label)
            elif isinstance(label, dict):
                value = label.get("name") or label.get("label")
                if value:
                    labels.append(str(value))
    return labels


def summarize_agent_health(data: dict[str, Any]) -> dict[str, Any]:
    raw_issues = data.get("linearOpenIssues")
    issues = raw_issues if isinstance(raw_issues, list) else []
    issue_summaries: list[dict[str, Any]] = []
    owner_counts: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    blocked_ids: list[str] = []
    needs_approval_ids: list[str] = []
    active_issue_ids: list[str] = []

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        identifier = str(issue.get("identifier") or "").strip()
        if identifier:
            active_issue_ids.append(identifier)
        labels = labels_from_issue(issue)
        owners = sorted(label for label in labels if label.startswith("owner:"))
        lanes = sorted(label for label in labels if label.startswith("lane:"))
        blockers = sorted(label for label in labels if label == "blocked" or label.startswith("needs:"))
        for owner in owners:
            owner_counts[owner] += 1
        for lane in lanes:
            lane_counts[lane] += 1
        if "blocked" in labels and identifier:
            blocked_ids.append(identifier)
        if any(label in {"needs:approval", "needs:perttu"} for label in labels) and identifier:
            needs_approval_ids.append(identifier)
        issue_summaries.append({
            "identifier": identifier or None,
            "title": sanitize_reason(issue.get("title")),
            "state": issue.get("state"),
            "state_type": issue.get("stateType"),
            "owners": owners,
            "lanes": lanes,
            "blockers": blockers,
            "updated_at": issue.get("updatedAt"),
        })

    owner_lane_audit = {}
    raw_latest_evidence = data.get("latestEvidence")
    latest_evidence = raw_latest_evidence if isinstance(raw_latest_evidence, dict) else {}
    raw_owner_lane_audit = latest_evidence.get("ownerLaneLabelAudit")
    raw_audit = raw_owner_lane_audit if isinstance(raw_owner_lane_audit, dict) else {}
    if raw_audit:
        owner_lane_audit = {
            "ok": raw_audit.get("ok"),
            "checked_at": raw_audit.get("checkedAt"),
            "checked_count": raw_audit.get("checkedCount"),
            "missing_label_count": raw_audit.get("missingLabelCount"),
        }

    agents_summary: dict[str, Any] = {}
    raw_agents = data.get("agents")
    agents = raw_agents if isinstance(raw_agents, dict) else {}
    for agent_id, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        agents_summary[str(agent_id)] = {
            "status": agent.get("status"),
            "state": agent.get("state"),
            "linear_issue": agent.get("linearIssue"),
            "last_check": agent.get("lastCheck"),
            "current_task": sanitize_reason(agent.get("currentTask")) if agent.get("currentTask") else None,
        }

    return {
        "updated_at": data.get("updatedAt"),
        "open_issue_count": len(issue_summaries),
        "active_issue_ids": active_issue_ids,
        "blocked_issue_ids": blocked_ids,
        "needs_approval_issue_ids": needs_approval_ids,
        "owner_issue_counts": dict(sorted(owner_counts.items())),
        "lane_issue_counts": dict(sorted(lane_counts.items())),
        "owner_lane_label_audit": owner_lane_audit,
        "issue_summaries": issue_summaries[:12],
        "agents": agents_summary,
    }


def summarize_taskboard(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"readable": False}
    updated = None
    active_ids: list[str] = []
    in_active_section = False
    for line in text.splitlines():
        if line.startswith("Updated:"):
            updated = line.split(":", 1)[1].strip()
        if line.startswith("## Active Linear OPE issues"):
            in_active_section = True
            continue
        if line.startswith("## ") and in_active_section:
            in_active_section = False
        if not in_active_section:
            continue
        match = re.search(r"\*\*(OPE-\d+)\*\*", line)
        if match:
            active_ids.append(match.group(1))
    return {
        "readable": True,
        "updated_at": updated,
        "active_issue_ids": active_ids[:20],
        "linear_authoritative": "Linear OPE is authoritative" in text,
    }


def local_coordination_placeholders(now: datetime) -> dict[str, Any]:
    workspace_dir = inferred_workspace_dir()
    candidates = {
        "taskboard": [workspace_dir / "TASKBOARD.md", PROJECT_DIR / "TASKBOARD.md"],
        "agent_health": [workspace_dir / "agent-health.json", PROJECT_DIR / "agent-health.json"],
        "autonomy_state": [workspace_dir / "autonomy-state.json", PROJECT_DIR / "autonomy-state.json"],
        "linear_cache": [workspace_dir / ".linear" / "issues.json", PROJECT_DIR / ".linear" / "issues.json"],
    }
    out: dict[str, Any] = {}
    agent_health_summary: dict[str, Any] = {}
    for name, paths in candidates.items():
        path = next((candidate for candidate in paths if candidate.exists()), None)
        if path is None:
            out[name] = {"available": False}
            continue
        try:
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            size = stat.st_size
        except OSError:
            mtime, size = None, None
        item: dict[str, Any] = {
            "available": True,
            "path": display_path(path),
            "age_minutes": age_minutes(mtime, now),
            "size_bytes": size,
        }
        if name == "taskboard":
            item["summary"] = summarize_taskboard(path)
        elif name == "agent_health":
            data = safe_read_json(path)
            if isinstance(data, dict):
                agent_health_summary = summarize_agent_health(data)
                item["summary"] = agent_health_summary
            else:
                item["summary"] = {"readable": False}
        out[name] = item

    return {
        "source": "workspace Linear mirror/cache files; Linear API not queried by this public JSON generator",
        "safe_public": True,
        "workspace_path": display_path(workspace_dir),
        "linear_open_issue_count": agent_health_summary.get("open_issue_count"),
        "active_issue_ids": agent_health_summary.get("active_issue_ids", []),
        "blocked_issue_ids": agent_health_summary.get("blocked_issue_ids", []),
        "needs_approval_issue_ids": agent_health_summary.get("needs_approval_issue_ids", []),
        "assignment_coverage_ok": (agent_health_summary.get("owner_lane_label_audit") or {}).get("ok"),
        "owner_issue_counts": agent_health_summary.get("owner_issue_counts", {}),
        "lane_issue_counts": agent_health_summary.get("lane_issue_counts", {}),
        "items": out,
    }


def build_panel(now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    checkout_freshness = dict(git_upstream_freshness(PROJECT_DIR))
    checkout_freshness["checked_at"] = iso(now)
    production = production_pipeline_status(now)
    content = content_summary(now)
    content["last_publish_at_local"] = content.get("last_publish_at")
    content["last_publish_age_minutes_local"] = content.get("last_publish_age_minutes")
    pipeline = pipeline_summary(now)
    raw_last_24h = pipeline.get("last_24h")
    last_24h: dict[str, Any] = raw_last_24h if isinstance(raw_last_24h, dict) else {}
    generated_count = int(last_24h.get("article_count") or 0)
    published_count = int(content.get("published_last_24h_local") or 0)
    last_24h["generated_article_count"] = generated_count
    last_24h["published_article_count_local"] = published_count
    # Retain the best local observer count as a diagnostic. It is not allowed
    # to override validated production truth in operator-facing fields.
    if published_count > generated_count:
        last_24h["article_count_local"] = published_count
        last_24h["article_count_local_source"] = "content/posts frontmatter"
    else:
        last_24h["article_count_local"] = generated_count
        last_24h["article_count_local_source"] = "pipeline/logs/metrics.json"

    if production.get("evidence_status") == "validated":
        content["operator_source"] = production["source"]
        pipeline["operator_source"] = production["source"]
        content["published_last_24h"] = production["published_last_24h"]
        content["last_publish_at"] = production["last_publish_at"]
        content["last_publish_age_minutes"] = production["last_publish_age_minutes"]
        last_24h["article_count"] = production["published_last_24h"]
        last_24h["article_count_source"] = "validated production pipeline-status"
        pipeline["staged_queue_runway"] = production["staged_queue_runway"]
    else:
        content["operator_source"] = None
        pipeline["operator_source"] = None
        content["published_last_24h"] = None
        content["last_publish_at"] = None
        content["last_publish_age_minutes"] = None
        last_24h["article_count"] = None
        last_24h["article_count_source"] = "production pipeline-status unavailable or invalid"
        pipeline["staged_queue_runway"] = None
    pipeline["last_24h"] = last_24h
    queues = queue_summary(now)
    for local_section in (content, pipeline, queues):
        local_section["git_upstream_freshness"] = dict(checkout_freshness)
    categories = category_drift()
    analytics = analytics_status(now)
    if production.get("evidence_status") == "validated" and production.get("pipeline_status") == "ok":
        status = "ok"
    elif production.get("evidence_status") == "stale":
        status = "stale"
    else:
        status = "unknown"
    return {
        "schema_version": "1.3",
        "site": "uutistenlukija.fi",
        "generated_at": iso(now),
        "status": status,
        "safe_public": True,
        "notes": [
            "Operator-facing pipeline values use a bounded unauthenticated production status response.",
            "Local Git, content, queue, and log values remain diagnostics only.",
            "No credentials are read or printed.",
        ],
        "production_pipeline": production,
        "git_upstream_freshness": checkout_freshness,
        "content": content,
        "pipeline": pipeline,
        "queues": queues,
        "category_drift": categories,
        "analytics": analytics,
        "monetization": monetization_status(),
        "coordination": local_coordination_placeholders(now),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print JSON to stdout and do not write files")
    parser.add_argument("--output", action="append", type=Path, help="additional/alternate output path; may be repeated")
    args = parser.parse_args(argv)

    panel = build_panel()
    if args.dry_run:
        print(json.dumps(panel, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    outputs = args.output if args.output else DEFAULT_OUTPUTS
    for output in outputs:
        safe_write_json(output, panel)
    print(json.dumps({"wrote": [str(p.relative_to(PROJECT_DIR)) if p.is_relative_to(PROJECT_DIR) else str(p) for p in outputs], "status": panel["status"], "generated_at": panel["generated_at"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
