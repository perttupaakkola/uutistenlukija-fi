#!/usr/bin/env python3
"""Persist a compact trend snapshot from the CTR gap report artifact."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _frontmatter_description(slug: str) -> tuple[str, int]:
    path = PROJECT_DIR / "content" / "posts" / f"{slug}.md"
    if not path.exists():
        return "", 0
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip().strip('"')
            return value, len(value)
    return "", 0


def _load_cohort(cohort_path: Path | None) -> tuple[str, list[dict]]:
    if not cohort_path or not cohort_path.exists():
        return "", []
    data = json.loads(cohort_path.read_text(encoding="utf-8"))
    items = []
    for slug in data.get("slugs", []):
        description, length = _frontmatter_description(slug)
        items.append({"slug": slug, "description_length": length, "description": description})
    return data.get("cohort", ""), items


def build_snapshot(report_path: Path, cohort_path: Path | None = None) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    gaps = report.get("gaps", [])
    top20 = gaps[:20]
    cohort_name, cohort_items = _load_cohort(cohort_path)
    metric_items = cohort_items or top20
    return {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "artifact": str(report_path),
        "generated_at": report.get("generated_at", ""),
        "data_source": report.get("data_source", ""),
        "total_gaps_found": report.get("total_gaps_found", len(gaps)),
        "cohort": cohort_name,
        "cohort_size": len(cohort_items),
        "top20_empty_descriptions": sum(1 for gap in metric_items if int(gap.get("description_length", 0) or 0) == 0),
        "top20_under80_descriptions": sum(1 for gap in metric_items if int(gap.get("description_length", 0) or 0) < 80),
        "top5": [
            {
                "slug": gap.get("slug", ""),
                "title": gap.get("title", ""),
                "description_length": int(gap.get("description_length", 0) or 0),
                "word_count": int(gap.get("word_count", 0) or 0),
                "ctr_gap_score": int(gap.get("ctr_gap_score", 0) or 0),
            }
            for gap in top20[:5]
        ],
        "recommended_experiment": "Experiment A: repair empty meta descriptions for the 20 synthetic CTR-gap slugs",
        "acceptance": "20/20 selected slugs get 120-160 char Finnish descriptions; no duplicates/wrapper leakage; regenerated top20_empty_descriptions becomes 0 for cohort.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Persist compact CTR gap trend snapshot")
    parser.add_argument("--report", default="static/api/ctr-gap-report.json")
    parser.add_argument("--output", default="static/api/ctr-gap-trend-snapshot.json")
    parser.add_argument("--cohort", default="static/api/ctr-gap-cohort.json")
    args = parser.parse_args()

    report_path = (PROJECT_DIR / args.report).resolve()
    output_path = (PROJECT_DIR / args.output).resolve()
    cohort_path = (PROJECT_DIR / args.cohort).resolve() if args.cohort else None
    snapshot = build_snapshot(report_path, cohort_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ctr_gap_trend_snapshot] Snapshot written to {output_path}")
    print(
        "[ctr_gap_trend_snapshot] "
        f"top20_empty_descriptions={snapshot['top20_empty_descriptions']} "
        f"top20_under80_descriptions={snapshot['top20_under80_descriptions']}"
    )


if __name__ == "__main__":
    main()
