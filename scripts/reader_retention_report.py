#!/usr/bin/env python3
"""Canonical rolling-30 goal report from existing saved direct provider envelopes.

Offline only: no credentials, refresh, provider or send path. The GA4 input is the
existing {fetched_at,http_status,endpoint,request,response} runReport envelope.
Usage: reader_retention_report.py --ga4 FILE [--returning FILE] [--gsc FILE]
Defaults to stdout; --output explicitly writes a report. No daily-user summation.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from analytics_contract import ga4_rows, validate_source

METRICS = {
    "screenPageViews": "Direct GA4 whole-window page views; target 10000",
    "activeUsers": "Direct GA4 deduplicated whole-window active users; target 1000; not a count of proven loyal humans",
    "returning_active_share": "Returning active users / direct active users in the same window; fraction; not acquisition-cohort retention",
    "bounceRate": "GA4 fraction of sessions not engaged; percentage only at presentation",
    "article_read": "Consented visible article dwell >=15s and >=75% depth observed after consent; reading proxy, not comprehension",
}


def build_report(ga4, returning=None, gsc=None, now=None):
    now = now or datetime.now(timezone.utc)
    report = {"schema_version": 1, "generated_at": now.isoformat(), "status": "blocked",
              "metric_dictionary": METRICS, "goal": None,
              "traffic": {"scope": "all_measured_unsegmented", "qa_internal_separated": False,
                          "classification": "Only explicit traffic_type=qa/internal labels classify those events. Unlabelled traffic is unclassified, not proof of humans or bots. Experiment IDs alone are not QA labels."},
              "cohort_retention": {"status": "unavailable", "reason": "Requires acquisition-cohort provider report; returning share is not cohort retention"},
              "experiment_decision": {"status": "insufficient_evidence", "eligible_exposure": None,
                  "reason": "No matched eligible exposure/decision record supplied. Event counts and experiment IDs alone do not establish efficacy or classify all traffic.",
                  "uncertainty": "Consent coverage and unlabelled QA/internal traffic are unresolved."},
              "returning_active_share": {"status": "unavailable"}}
    state = validate_source(ga4, "ga4", now, expected_days=30)
    report["source"] = state
    if not state["fresh"]:
        return report
    request = ga4["request"]
    rows = ga4_rows(ga4)
    if request.get("dimensions") or request.get("dimensionFilter") or request.get("metricFilter") or len(rows) != 1:
        report["source"] = {"fresh": False, "reason": "goal_requires_unfiltered_direct_totals"}
        return report
    totals = rows[0]
    if any(name not in totals for name in ("screenPageViews", "activeUsers")):
        report["source"] = {"fresh": False, "reason": "missing_goal_metrics"}
        return report
    report.update(status="fresh", query_window=state["query_window"],
                  goal={name: {"observed": totals[name], "target": target,
                               "completion_fraction": totals[name] / target}
                        for name, target in (("screenPageViews", 10000), ("activeUsers", 1000))})
    report["goal_met"] = totals["screenPageViews"] >= 10000 and totals["activeUsers"] >= 1000
    report["direct_totals"] = totals
    if returning is not None:
        rstate = validate_source(returning, "ga4", now, expected_days=30)
        report["returning_active_share"] = {"status": "blocked", "source": rstate}
        req = returning.get("request", {})
        if (rstate["fresh"] and rstate["query_window"] == state["query_window"]
                and req.get("dimensions") == [{"name": "newVsReturning"}]
                and not req.get("dimensionFilter") and not req.get("metricFilter")):
            matches = [r for r in ga4_rows(returning) if r.get("newVsReturning") == "returning"]
            if len(matches) == 1 and "activeUsers" in matches[0] and totals["activeUsers"] > 0:
                numerator = matches[0]["activeUsers"]
                if numerator <= totals["activeUsers"]:
                    report["returning_active_share"] = {"status": "fresh", "numerator": numerator,
                        "denominator": totals["activeUsers"], "unit": "fraction",
                        "value": numerator / totals["activeUsers"], "is_cohort_retention": False}
    if gsc is not None:
        gstate = validate_source(gsc, "gsc", now)
        report["search"] = {"source": gstate, "property_totals": gsc.get("property_totals") if gstate["fresh"] else None,
                            "note": "Separate GSC finalized window/population; dimension sums are not site totals."}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ga4", type=Path, required=True)
    parser.add_argument("--returning", type=Path)
    parser.add_argument("--gsc", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    def read(path):
        if path is None:
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
    report = build_report(read(args.ga4), read(args.returning), read(args.gsc))
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 0 if report["status"] == "fresh" else 1


if __name__ == "__main__":
    raise SystemExit(main())
