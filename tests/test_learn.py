"""Invariant tests for the learning loop.

The loop must never invent a metric: with too little traffic the honest verdict is
`no_evidence`, and a failed measurement must not be reported as a successful review.
"""
import json
import tempfile
import unittest
from pathlib import Path

from news_mvp import learn


class GoalStatus(unittest.TestCase):
    def test_derives_percentages_from_measured_values(self):
        status = learn.goal_status({"ga4": {"views": 500, "active_users": 50}})
        self.assertEqual(status["views_pct"], 5.0)
        self.assertEqual(status["users_pct"], 5.0)
        self.assertEqual(status["views_target"], learn.TARGET_VIEWS)

    def test_missing_ga4_does_not_crash(self):
        status = learn.goal_status({})
        self.assertIsNone(status["views"])
        self.assertIsNone(status["views_pct"])


class Diagnose(unittest.TestCase):
    def _article(self, **kw):
        base = {"id": "a" * 8, "created_at": "2026-09-16T00:00:00+00:00", "title": "Otsikko",
                "summary": "Kuvaus", "category": "Kotimaa", "title_length": 20,
                "summary_length": 10, "has_image": True}
        base.update(kw)
        return base

    def test_low_ctr_with_signal_raises_seo_hypothesis(self):
        data = {"ga4": {"views": 100, "active_users": 10},
                "gsc": {"impressions": 5000, "clicks": 90}}
        found = [h for h in learn.diagnose(data, [self._article()]) if h["lane"] == "seo"]
        self.assertTrue(found, "expected an SEO hypothesis at 1.8% CTR")
        self.assertEqual(found[0]["confidence"], "high")

    def test_low_traffic_yields_no_evidence_not_a_verdict(self):
        data = {"ga4": {"views": 2, "active_users": 2},
                "gsc": {"impressions": 10, "clicks": 0}}
        hypotheses = learn.diagnose(data, [self._article()])
        seo = [h for h in hypotheses if h["lane"] == "seo" and "snippet" in h["target"]]
        for h in seo:
            self.assertEqual(h["confidence"], "no_evidence")

    def test_missing_gsc_does_not_crash(self):
        self.assertIsInstance(learn.diagnose({"ga4": {"views": 1}}, []), list)

    def test_image_shortfall_detected(self):
        articles = [self._article(has_image=False) for _ in range(5)] + [self._article()]
        lanes = {h["lane"] for h in learn.diagnose({"ga4": {"views": 5, "active_users": 1}}, articles)}
        self.assertIn("publishing_quality", lanes)

    def test_hypotheses_are_ranked_by_priority(self):
        data = {"ga4": {"views": 66, "active_users": 51},
                "gsc": {"impressions": 8443, "clicks": 148}}
        articles = [self._article(title_length=107, has_image=False)] * 12 + [self._article()] * 7
        hypotheses = learn.diagnose(data, articles)
        priorities = [h["priority"] for h in hypotheses]
        self.assertEqual(priorities, sorted(priorities), priorities)


class Ledger(unittest.TestCase):
    def test_records_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            learn.record({"kind": "review", "goal": {"views": 1}}, Path(tmp))
            rows = learn.history(Path(tmp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "review")
            self.assertIn("recorded_at", rows[0])

    def test_history_is_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(learn.history(Path(tmp)), [])

    def test_appends_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                learn.record({"kind": "review", "n": i}, Path(tmp))
            rows = learn.history(Path(tmp))
            self.assertEqual([r["n"] for r in rows], [0, 1, 2])


class Report(unittest.TestCase):
    def test_failed_review_is_reported_as_failure(self):
        text = learn.format_report({"ok": False, "error": "boom"})
        self.assertIn("failed", text.lower())

    def test_success_report_names_the_goal(self):
        result = {"ok": True, "goal": {"views": 66, "views_target": 10000, "views_pct": 0.66,
                                       "users": 51, "users_target": 1000, "users_pct": 5.1},
                  "articles": 19,
                  "hypotheses": [{"lane": "seo", "confidence": "high", "hypothesis": "H",
                                  "evidence": "E", "metric": "M", "target": "T"}]}
        text = learn.format_report(result)
        self.assertIn("10000", text)
        self.assertIn("seo", text)


if __name__ == "__main__":
    unittest.main()
