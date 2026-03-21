"""
generate_dashboard.py — Single-page HTML pipeline dashboard for Uutistenlukija.

Reads all pipeline state files and writes static/pipeline-dashboard.html,
served at /pipeline-dashboard/ by Hugo as a static file.

Usage:
    python3 generate_dashboard.py
    python3 generate_dashboard.py --output /custom/path/dashboard.html
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

_PIPELINE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR  = _PIPELINE_DIR.parent
_LOGS_DIR     = _PIPELINE_DIR / "logs"
_REJECTED_DIR = _PIPELINE_DIR / "rejected"
_STATIC_DIR   = _PROJECT_DIR / "static"

METRICS_JSON         = _LOGS_DIR / "metrics.json"
METRICS_JSONL        = _PIPELINE_DIR / "metrics.jsonl"
SERVICE_HEALTH_JSON  = _PIPELINE_DIR / "service_health.json"
BACKFILL_PROGRESS    = _LOGS_DIR / "backfill-progress.json"
BUILD_MANIFEST_JSON  = _PIPELINE_DIR / "build_manifest.json"
DEFAULT_OUTPUT       = _STATIC_DIR / "pipeline-dashboard" / "index.html"


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _load_jsonl(path: Path, limit: int = 100) -> list[dict]:
    if not path.exists():
        return []
    records = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return records[-limit:]


def _load_rejected(limit: int = 10) -> list[dict]:
    """Load the most recent rejected article files."""
    if not _REJECTED_DIR.exists():
        return []
    files = sorted(_REJECTED_DIR.glob("*.json"), reverse=True)[:limit]
    results = []
    for f in files:
        data = _load_json(f)
        if data:
            results.append({
                "filename": f.name,
                "score": data.get("score", "?"),
                "reason": data.get("reason", ""),
                "title": data.get("article", {}).get("title", f.stem)[:80],
                "ts": f.stem[:15].replace("_", "T"),
            })
    return results


def _fmt_duration(secs) -> str:
    try:
        s = float(secs)
    except (TypeError, ValueError):
        return "?"
    if s < 60:
        return f"{s:.0f}s"
    return f"{s/60:.1f}m"


def _fmt_ts(ts: str) -> str:
    """Format ISO timestamp to human-readable."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts


def _age(ts: str) -> str:
    """Return human-readable age from ISO timestamp."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        secs = delta.total_seconds()
        if secs < 120:
            return "just now"
        if secs < 3600:
            return f"{secs/60:.0f}m ago"
        if secs < 86400:
            return f"{secs/3600:.1f}h ago"
        return f"{secs/86400:.1f}d ago"
    except Exception:
        return ts


def _pct(num, denom) -> str:
    if not denom:
        return "0%"
    return f"{100 * num / denom:.0f}%"


# ── Section builders ──────────────────────────────────────────────────────────

def _build_pipeline_section(metrics_records: list[dict], jsonl_records: list[dict]) -> str:
    """Pipeline health — last run stats + 7-day trend."""
    if not metrics_records and not jsonl_records:
        return _empty_section("Pipeline Health", "No metrics data found.")

    # Last run from metrics.json (richer data)
    last = metrics_records[-1] if metrics_records else {}
    ts = last.get("timestamp", last.get("ts", ""))
    success = last.get("success", last.get("result") == "success")
    duration = last.get("total_duration_sec", last.get("duration_s", 0))
    articles = last.get("article_count", last.get("published", 0))
    steps = last.get("steps", {})
    errors = last.get("errors", [])

    status_cls = "ok" if success else "err"
    status_txt = "✅ Success" if success else "❌ Failed"

    # 7-day stats from jsonl
    recent = jsonl_records[-50:] if jsonl_records else []
    total_runs = len(recent)
    success_runs = sum(1 for r in recent if r.get("published", 0) > 0)
    total_published = sum(r.get("published", 0) for r in recent)
    avg_per_run = round(total_published / total_runs, 1) if total_runs else 0
    success_rate = _pct(success_runs, total_runs)
    avg_duration = round(
        sum(r.get("duration_s", 0) for r in recent) / total_runs, 1
    ) if total_runs else 0

    # Sparkline data (last 20 runs — published count)
    spark_data = [r.get("published", 0) for r in recent[-20:]]
    spark_max = max(spark_data) if spark_data else 1
    spark_bars = "".join(
        f'<span class="spark-bar" style="height:{max(2, int(24 * v / spark_max))}px" '
        f'title="{v} articles"></span>'
        for v in spark_data
    )

    # Step breakdown for last run
    step_rows = ""
    for step_name, step_data in steps.items():
        if not isinstance(step_data, dict):
            continue
        s_ok = step_data.get("success", True)
        s_dur = _fmt_duration(step_data.get("duration_sec", step_data.get("duration_s", 0)))
        s_cls = "ok" if s_ok else "err"
        extra = ""
        if "count" in step_data:
            extra = f" ({step_data['count']} items)"
        elif "dropped" in step_data:
            extra = f" ({step_data.get('passed',0)} passed, {step_data['dropped']} dropped)"
        step_rows += (
            f'<tr><td>{step_name}</td>'
            f'<td class="status-{s_cls}">{"✅" if s_ok else "❌"}</td>'
            f'<td>{s_dur}</td>'
            f'<td class="muted">{extra}</td></tr>'
        )

    errors_html = ""
    if errors:
        err_items = "".join(f"<li>{e}</li>" for e in errors[:5])
        errors_html = f'<div class="alert-box"><strong>Errors:</strong><ul>{err_items}</ul></div>'

    return f"""
<section class="card">
  <h2>🔄 Pipeline Health</h2>
  <div class="stat-row">
    <div class="stat"><span class="label">Last Run</span><span class="value">{_age(ts)}</span><span class="sub">{_fmt_ts(ts)}</span></div>
    <div class="stat"><span class="label">Status</span><span class="value status-{status_cls}">{status_txt}</span></div>
    <div class="stat"><span class="label">Duration</span><span class="value">{_fmt_duration(duration)}</span></div>
    <div class="stat"><span class="label">Published</span><span class="value">{articles}</span><span class="sub">this run</span></div>
  </div>
  <div class="stat-row">
    <div class="stat"><span class="label">7-day Success Rate</span><span class="value">{success_rate}</span><span class="sub">{success_runs}/{total_runs} runs</span></div>
    <div class="stat"><span class="label">Avg Articles/Run</span><span class="value">{avg_per_run}</span></div>
    <div class="stat"><span class="label">Avg Duration</span><span class="value">{_fmt_duration(avg_duration)}</span></div>
    <div class="stat"><span class="label">Total Published (recent)</span><span class="value">{total_published}</span></div>
  </div>
  <div class="sparkline-label">Published per run (last {len(spark_data)}):</div>
  <div class="sparkline">{spark_bars}</div>
  {f'<h3 class="sub-heading">Last Run Steps</h3><table class="data-table"><thead><tr><th>Step</th><th>Status</th><th>Duration</th><th>Notes</th></tr></thead><tbody>{step_rows}</tbody></table>' if step_rows else ''}
  {errors_html}
</section>
"""


def _build_services_section(health: dict | None) -> str:
    """Service status — Kie.ai / Unsplash / Pexels."""
    if not health:
        return _empty_section("Service Status", "No service_health.json found.")

    services = health.get("services", health) if isinstance(health, dict) else {}
    rows = ""
    for svc_name, data in services.items():
        if not isinstance(data, dict):
            continue
        failures = data.get("consecutive_failures", 0)
        last_ok = data.get("last_success", "")
        skip_until = data.get("skip_until", "")
        state = data.get("state", "unknown")

        if skip_until:
            try:
                skip_dt = datetime.fromisoformat(skip_until.replace("Z", "+00:00"))
                if skip_dt > datetime.now(timezone.utc):
                    status_cls = "warn"
                    status_txt = f"⏸ Skipped until {_fmt_ts(skip_until)}"
                else:
                    status_cls = "ok"
                    status_txt = "✅ Available"
            except Exception:
                status_cls = "warn"
                status_txt = f"⏸ Skip window active"
        elif failures >= 10:
            status_cls = "err"
            status_txt = f"❌ Down ({failures} failures)"
        elif failures >= 3:
            status_cls = "warn"
            status_txt = f"⚠️ Degraded ({failures} failures)"
        elif failures == 0:
            status_cls = "ok"
            status_txt = "✅ Healthy"
        else:
            status_cls = "warn"
            status_txt = f"⚠️ {failures} failure(s)"

        age_ok = _age(last_ok) if last_ok else "never"
        rows += (
            f'<tr><td><strong>{svc_name}</strong></td>'
            f'<td class="status-{status_cls}">{status_txt}</td>'
            f'<td class="muted">{failures}</td>'
            f'<td class="muted">{age_ok}</td></tr>'
        )

    if not rows:
        return _empty_section("Service Status", "No service records found in service_health.json.")

    return f"""
<section class="card">
  <h2>🔌 Service Status</h2>
  <table class="data-table">
    <thead><tr><th>Service</th><th>Status</th><th>Failures</th><th>Last Success</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _build_quality_section(metrics_records: list[dict], rejected: list[dict]) -> str:
    """Quality gate — avg score, rejection rate, last rejected articles."""
    if not metrics_records and not rejected:
        return _empty_section("Quality Gate", "No quality data available.")

    # Aggregate quality stats from metrics records
    gate_stats = [r.get("steps", {}).get("quality_gate", {}) for r in metrics_records if r.get("steps", {}).get("quality_gate")]
    total_dropped = sum(s.get("dropped", 0) for s in gate_stats)
    total_passed  = sum(s.get("passed",  0) for s in gate_stats)
    total_checked = total_dropped + total_passed
    reject_rate = _pct(total_dropped, total_checked)

    scores = [s["avg_score"] for s in gate_stats if "avg_score" in s]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    threshold = gate_stats[-1].get("threshold", 40) if gate_stats else 40

    # Rejection reason breakdown (from jsonl reject_reasons)
    reason_totals: dict[str, int] = {}
    for r in metrics_records:
        for k, v in r.get("reject_reasons", {}).items():
            reason_totals[k] = reason_totals.get(k, 0) + v

    reason_rows = ""
    for reason, count in sorted(reason_totals.items(), key=lambda x: -x[1]):
        pct = _pct(count, total_dropped) if total_dropped else "0%"
        reason_rows += f"<tr><td>{reason}</td><td>{count}</td><td class='muted'>{pct}</td></tr>"

    # Last 10 rejected articles
    rejected_rows = ""
    for r in rejected:
        ts_display = r["ts"][:13].replace("_", " ") if len(r["ts"]) >= 13 else r["ts"]
        score = r.get("score", "?")
        score_cls = "err" if isinstance(score, int) and score < 40 else "warn"
        rejected_rows += (
            f'<tr><td class="muted">{ts_display}</td>'
            f'<td><span class="score-badge score-{score_cls}">{score}/80</span></td>'
            f'<td>{r["title"]}</td>'
            f'<td class="muted reason-cell">{r["reason"][:100]}</td></tr>'
        )

    score_display = f"{avg_score}/80" if avg_score is not None else "—"

    return f"""
<section class="card">
  <h2>🎯 Quality Gate</h2>
  <div class="stat-row">
    <div class="stat"><span class="label">Rejection Rate</span><span class="value">{reject_rate}</span><span class="sub">{total_dropped}/{total_checked} articles</span></div>
    <div class="stat"><span class="label">Avg Score</span><span class="value">{score_display}</span><span class="sub">threshold {threshold}/80</span></div>
    <div class="stat"><span class="label">Passed</span><span class="value">{total_passed}</span></div>
    <div class="stat"><span class="label">Rejected</span><span class="value">{total_dropped}</span></div>
  </div>
  {f'<h3 class="sub-heading">Rejection Reasons</h3><table class="data-table"><thead><tr><th>Reason</th><th>Count</th><th>%</th></tr></thead><tbody>{reason_rows}</tbody></table>' if reason_rows else ''}
  {f'<h3 class="sub-heading">Last 10 Rejected Articles</h3><table class="data-table wide"><thead><tr><th>Time</th><th>Score</th><th>Title</th><th>Reason</th></tr></thead><tbody>{rejected_rows}</tbody></table>' if rejected_rows else '<p class="muted">No rejected articles on record.</p>'}
</section>
"""


def _build_backfill_section(progress: list[dict] | None) -> str:
    """Backfill progress — tier status + word count chart."""
    from backfill_thin_articles import find_thin_articles

    # Live tier counts
    tiers = [(50, 0), (100, 0), (150, 0), (200, 0)]
    try:
        tier_rows_live = ""
        for threshold, _ in tiers:
            thin = find_thin_articles(threshold)
            total_under = len(thin)
            avg_wc = round(sum(w for w, _ in thin) / total_under, 0) if thin else 0
            tier_cls = "ok" if total_under == 0 else "warn" if total_under < 5 else "err"
            tier_rows_live += (
                f'<tr><td>&lt;{threshold}w</td>'
                f'<td class="status-{tier_cls}">{total_under}</td>'
                f'<td class="muted">{avg_wc:.0f}w avg</td></tr>'
            )
    except Exception as e:
        tier_rows_live = f'<tr><td colspan="3" class="muted">Could not load live counts: {e}</td></tr>'

    # History chart data
    if not progress:
        history_html = '<p class="muted">No backfill history yet.</p>'
    else:
        real_runs = [r for r in progress if not r.get("dry_run")]
        if not real_runs:
            history_html = '<p class="muted">No real backfill runs yet (only dry-runs).</p>'
        else:
            # Bar chart: before vs after words
            chart_bars = ""
            for i, r in enumerate(real_runs[-20:]):
                before = r.get("avg_before", 0)
                after  = r.get("avg_after",  0)
                exp    = r.get("expanded", 0)
                date   = r.get("date", "")[:10]
                thr    = r.get("threshold", "?")
                if exp == 0:
                    continue
                label = f"{date} (×{exp}, <{thr}w)"
                # Normalise to 200px max
                max_val = max(after, 300)
                bar_before = max(2, int(80 * before / max_val))
                bar_after  = max(2, int(80 * after  / max_val))
                chart_bars += f"""
  <div class="bar-group" title="{label}: {before:.0f}w → {after:.0f}w">
    <div class="bar-before" style="width:{bar_before}px">{before:.0f}w</div>
    <div class="bar-after"  style="width:{bar_after}px">{after:.0f}w</div>
    <div class="bar-label">{date}</div>
  </div>"""

            history_html = (
                f'<h3 class="sub-heading">Word count before → after per batch</h3>'
                f'<div class="bar-legend">'
                f'<span class="legend-before">■ Before</span>'
                f'<span class="legend-after">■ After</span>'
                f'</div>'
                f'<div class="bar-chart">{chart_bars}</div>'
                if chart_bars else
                '<p class="muted">Not enough expansion runs to chart.</p>'
            )

        # Summary stats
        total_expanded = sum(r.get("expanded", 0) for r in real_runs)
        last_run = real_runs[-1] if real_runs else {}
        last_run_date = last_run.get("date", "never")[:10]

        history_html = (
            f'<div class="stat-row">'
            f'<div class="stat"><span class="label">Total Expanded</span>'
            f'<span class="value">{total_expanded}</span></div>'
            f'<div class="stat"><span class="label">Last Run</span>'
            f'<span class="value">{last_run_date}</span></div>'
            f'<div class="stat"><span class="label">Batches Run</span>'
            f'<span class="value">{len(real_runs)}</span></div>'
            f'</div>'
            + history_html
        )

    return f"""
<section class="card">
  <h2>📈 Backfill Progress</h2>
  <h3 class="sub-heading">Thin Article Counts (live)</h3>
  <table class="data-table narrow">
    <thead><tr><th>Tier</th><th>Remaining</th><th>Avg Words</th></tr></thead>
    <tbody>{tier_rows_live}</tbody>
  </table>
  {history_html}
</section>
"""


def _empty_section(title: str, msg: str) -> str:
    return f'<section class="card"><h2>{title}</h2><p class="muted">{msg}</p></section>'


# ── HTML template ─────────────────────────────────────────────────────────────

def _html(body: str, generated_at: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Dashboard — Uutistenlukija.fi</title>
<style>
  :root {{
    --bg: #0f1117; --card: #1a1d27; --border: #2a2d3a;
    --text: #e2e8f0; --muted: #718096; --accent: #4299e1;
    --ok: #48bb78; --warn: #ecc94b; --err: #fc8181;
    --before: #718096; --after: #4299e1;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; padding: 24px; }}
  h1 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 4px; }}
  h2 {{ font-size: 1.05rem; font-weight: 600; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
  h3.sub-heading {{ font-size: 0.85rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin: 20px 0 10px; }}
  .header {{ margin-bottom: 24px; }}
  .header .meta {{ color: var(--muted); font-size: 0.8rem; margin-top: 2px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 20px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }}
  .stat-row {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 16px; }}
  .stat {{ flex: 1; min-width: 100px; }}
  .stat .label {{ display: block; font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px; }}
  .stat .value {{ display: block; font-size: 1.5rem; font-weight: 700; line-height: 1.2; }}
  .stat .sub {{ display: block; font-size: 0.75rem; color: var(--muted); }}
  .status-ok {{ color: var(--ok); }}
  .status-warn {{ color: var(--warn); }}
  .status-err {{ color: var(--err); }}
  .muted {{ color: var(--muted); }}
  .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 4px; }}
  .data-table th {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); color: var(--muted); font-weight: 500; }}
  .data-table td {{ padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  .data-table tr:last-child td {{ border-bottom: none; }}
  .data-table.narrow {{ max-width: 360px; }}
  .reason-cell {{ max-width: 280px; word-break: break-word; }}
  .score-badge {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; }}
  .score-err {{ background: rgba(252,129,129,0.15); color: var(--err); }}
  .score-warn {{ background: rgba(236,201,75,0.15); color: var(--warn); }}
  .sparkline {{ display: flex; align-items: flex-end; gap: 2px; height: 28px; margin-top: 4px; margin-bottom: 16px; }}
  .spark-bar {{ display: inline-block; min-width: 4px; background: var(--accent); border-radius: 1px; opacity: 0.7; }}
  .sparkline-label {{ font-size: 0.75rem; color: var(--muted); margin-top: 8px; }}
  .alert-box {{ background: rgba(252,129,129,0.08); border: 1px solid rgba(252,129,129,0.25); border-radius: 6px; padding: 10px 14px; margin-top: 12px; font-size: 0.82rem; }}
  .alert-box ul {{ padding-left: 16px; margin-top: 4px; }}
  .bar-chart {{ display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }}
  .bar-group {{ display: flex; flex-direction: column; gap: 3px; }}
  .bar-label {{ font-size: 0.7rem; color: var(--muted); margin-top: 2px; }}
  .bar-before {{ background: var(--before); color: var(--text); font-size: 0.7rem; padding: 2px 6px; border-radius: 2px; min-width: 30px; white-space: nowrap; }}
  .bar-after  {{ background: var(--after);  color: var(--bg);  font-size: 0.7rem; padding: 2px 6px; border-radius: 2px; min-width: 30px; white-space: nowrap; }}
  .bar-legend {{ display: flex; gap: 16px; font-size: 0.75rem; color: var(--muted); margin-bottom: 8px; }}
  .legend-before {{ color: var(--before); }}
  .legend-after  {{ color: var(--after); }}
  .refresh-note {{ margin-top: 24px; text-align: center; font-size: 0.75rem; color: var(--muted); }}
  @media (max-width: 600px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .stat .value {{ font-size: 1.2rem; }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>🛠 Pipeline Dashboard — Uutistenlukija.fi</h1>
  <div class="meta">Generated {generated_at} · Refreshes on each pipeline run</div>
</div>
<div class="grid">
{body}
</div>
<p class="refresh-note">Run <code>python3 pipeline/generate_dashboard.py</code> to refresh manually.</p>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def generate(output: Path = DEFAULT_OUTPUT) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Load data
    metrics_records = _load_json(METRICS_JSON, [])
    jsonl_records   = _load_jsonl(METRICS_JSONL, limit=100)
    service_health  = _load_json(SERVICE_HEALTH_JSON)
    backfill_prog   = _load_json(BACKFILL_PROGRESS)
    rejected        = _load_rejected(limit=10)

    # Build sections
    sections = [
        _build_pipeline_section(metrics_records, jsonl_records),
        _build_services_section(service_health),
        _build_quality_section(metrics_records, rejected),
        _build_backfill_section(backfill_prog),
    ]

    html = _html("\n".join(sections), now)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[dashboard] Written to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate pipeline dashboard HTML")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output path (default: {DEFAULT_OUTPUT})")
    args = parser.parse_args()
    generate(args.output)
