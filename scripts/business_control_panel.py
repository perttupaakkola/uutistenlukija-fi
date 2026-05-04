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

    return {
        "source": "local public/static reports and pipeline/logs only; external analytics APIs not queried",
        "ga4": {
            "status": "blocked_or_unknown",
            "reason": "no fresh external credentials/API calls used; see local GA4 cron logs for last known state",
            "daily_traffic_log": log_probe(traffic_log),
            "weekly_metrics_log": log_probe(weekly_log),
        },
        "gsc": {
            "status": "blocked" if gsc_blocked else "local_report_present",
            "reason": gsc_reason,
            "ctr_gap_report": {
                "source": str(ctr_path.relative_to(PROJECT_DIR)) if ctr_path else None,
                "generated_at": iso(gsc_generated),
                "age_minutes": age_minutes(gsc_generated, now),
                "data_source": gsc_source,
                "total_gaps_found": ctr.get("total_gaps_found") if ctr else None,
            },
            "fetch_log": log_probe(gsc_log),
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
