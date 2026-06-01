#!/usr/bin/env python3
"""Build a safe machine-readable KPI/control panel from local files only.

Outputs public JSON for uutistenlukija.fi without contacting external APIs or
reading/printing credentials. Intended for cron/manual use:

    python3 scripts/business_control_panel.py
    python3 scripts/business_control_panel.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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


def content_summary(now: datetime) -> dict[str, Any]:
    posts = sorted(CONTENT_DIR.glob("*.md")) if CONTENT_DIR.exists() else []
    latest: tuple[datetime, Path, dict[str, str]] | None = None
    published_24h = 0
    cutoff = now - timedelta(hours=24)
    for path in posts:
        fm = extract_frontmatter(path)
        dt = parse_dt(fm.get("date") or fm.get("published_at"))
        if dt and dt >= cutoff:
            published_24h += 1
        if dt and (latest is None or dt > latest[0]):
            latest = (dt, path, fm)
    latest_dt = latest[0] if latest else None
    return {
        "article_count_local": len(posts),
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
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
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

    adsense_id = str(params.get("adsense_id") or "")
    ads_enabled = bool(params.get("ads_enabled"))
    return {
        "status": "lead_capture_tracking_active" if tracked_signal_count else "not_tracked",
        "safe_public": True,
        "monthly_euros": 0,
        "source": "hugo.toml + monetization CTA markup; no ad network or personal data required",
        "ads_enabled": ads_enabled,
        "adsense_configured": bool(adsense_id),
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

def local_coordination_placeholders(now: datetime) -> dict[str, Any]:
    candidates = {
        "taskboard": PROJECT_DIR / "TASKBOARD.md",
        "agent_health": PROJECT_DIR / "agent-health.json",
        "autonomy_state": PROJECT_DIR / "autonomy-state.json",
        "linear_cache": PROJECT_DIR / ".linear" / "issues.json",
    }
    out: dict[str, Any] = {}
    for name, path in candidates.items():
        if path.exists():
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                size = path.stat().st_size
            except OSError:
                mtime, size = None, None
            out[name] = {"available": True, "path": str(path.relative_to(PROJECT_DIR)), "age_minutes": age_minutes(mtime, now), "size_bytes": size}
        else:
            out[name] = {"available": False}
    return {
        "source": "local placeholder files only; Linear API not queried",
        "items": out,
    }


def build_panel(now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    content = content_summary(now)
    pipeline = pipeline_summary(now)
    raw_last_24h = pipeline.get("last_24h")
    last_24h: dict[str, Any] = raw_last_24h if isinstance(raw_last_24h, dict) else {}
    generated_count = int(last_24h.get("article_count") or 0)
    published_count = int(content.get("published_last_24h_local") or 0)
    last_24h["generated_article_count"] = generated_count
    last_24h["published_article_count_local"] = published_count
    # For the public/operator-facing 24h article count, prefer what actually
    # exists on the site. The scanner metrics can legitimately be 0 when the
    # staged publisher/Monica path produced fresh articles, and reporting that
    # as "0 articles" creates a false yellow drift alert.
    if published_count > generated_count:
        last_24h["article_count"] = published_count
        last_24h["article_count_source"] = "content/posts frontmatter"
    else:
        last_24h["article_count_source"] = "pipeline/logs/metrics.json"
    pipeline["last_24h"] = last_24h
    queues = queue_summary(now)
    categories = category_drift()
    analytics = analytics_status(now)
    published_last = content.get("last_publish_age_minutes")
    failures = pipeline.get("last_24h", {}).get("failure", 0)
    status = "ok"
    if published_last is None or published_last > 180 or failures:
        status = "attention"
    if published_last is None and not pipeline.get("metrics_rows_total"):
        status = "unknown"
    return {
        "schema_version": "1.0",
        "site": "uutistenlukija.fi",
        "generated_at": iso(now),
        "status": status,
        "safe_public": True,
        "notes": [
            "Generated from local files/logs only.",
            "No external APIs queried; no credentials read or printed.",
        ],
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
