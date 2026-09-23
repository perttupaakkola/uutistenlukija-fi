"""Invariant tests for the learning loop.

The loop must never invent a metric. A readership diagnosis requires a complete measurement
whose rows are valid, non-duplicate, exactly deployed articles on this site; anything less
must abstain with `insufficient_evidence` and `no_evidence` rather than guess. Article shape
alone is never readership evidence, and the ceiling is never raised from a shortfall.
"""
import json
import math
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from news_mvp import learn


class Measure(unittest.TestCase):
    """The collector seam: parameter forwarding, verbatim reports, classified failures."""

    def _collect(self, **kwargs):
        with mock.patch("news_mvp.measurement.collect", create=True, **kwargs) as collect:
            result = learn.measure(timeout=17, state_dir=Path("/tmp/state"))
        return collect, result

    def test_forwards_timeout_and_state_dir_to_the_collector(self):
        collect, result = self._collect(return_value={"measurement_status": "ok"})
        collect.assert_called_once_with(timeout=17, state_dir=Path("/tmp/state"))
        self.assertEqual(result, {"ok": True, "data": {"measurement_status": "ok"}})

    def test_incomplete_report_is_preserved_verbatim(self):
        report = {"measurement_status": "incomplete", "truncated": True, "notes": ["quota"]}
        _, result = self._collect(return_value=report)
        self.assertEqual(result, {"ok": True, "data": report})

    def test_non_dict_report_is_classified_as_invalid(self):
        for report in (None, "report", 42, ["ga4"]):
            with self.subTest(report=report):
                _, result = self._collect(return_value=report)
                self.assertEqual(result, {"ok": False, "error": "invalid measurement report"})

    def test_exception_details_are_not_leaked(self):
        secret = "Bearer sk-live-supersecret"
        _, result = self._collect(side_effect=RuntimeError(f"collector rejected {secret}"))
        self.assertEqual(result, {"ok": False, "error": "measurement collection failed"})
        self.assertNotIn(secret, json.dumps(result))


class GoalStatus(unittest.TestCase):
    def test_derives_percentages_from_measured_values(self):
        status = learn.goal_status({"ga4": {"views": 500, "active_users": 50,
                                            "dimension_free": True, "status": "ok"}})
        self.assertEqual(status["views_pct"], 5.0)
        self.assertEqual(status["users_pct"], 5.0)
        self.assertEqual(status["views_target"], learn.TARGET_VIEWS)

    def test_unverified_or_cohort_ga4_totals_stay_unknown(self):
        cohort = {"views": 500, "active_users": 50, "status": "ok"}
        for data in ({}, {"ga4": cohort}, {"ga4": {"views": 500, "active_users": 50,
                                                  "dimension_free": False, "status": "ok"}},
                     {"ga4": {"views": 500, "active_users": 50, "dimension_free": True,
                              "status": "incomplete"}}):
            with self.subTest(data=data):
                status = learn.goal_status(data)
                self.assertIsNone(status["views"])
                self.assertIsNone(status["users"])
                self.assertIsNone(status["views_pct"])
                self.assertIsNone(status["users_pct"])

    def test_missing_ga4_does_not_crash(self):
        status = learn.goal_status({})
        self.assertIsNone(status["views"])
        self.assertIsNone(status["views_pct"])


class Diagnose(unittest.TestCase):
    """The evidence gate: only verified joined rows may produce a readership verdict."""

    REPORT_KEYS = ("lane", "priority", "verdict", "hypothesis", "evidence", "metric",
                   "target", "action", "confidence")

    def _row(self, slug="a", **kw):
        row = {"id": slug,
               "canonical_url": f"https://uutistenlukija.fi/uutiset/{slug}",
               "deployed": True,
               "gsc": {"status": "ok", "clicks": 1, "impressions": 200, "position": 5.0},
               "metadata": {"description": True, "og": True, "jsonld": True}}
        gsc = kw.pop("gsc", None)
        if gsc:
            row["gsc"].update(gsc)
        metadata = kw.pop("metadata", None)
        if metadata is not None:
            row["metadata"] = metadata
        row.update(kw)
        return row

    def _data(self, rows, **kw):
        data = {"measurement_status": "ok", "truncated": False, "article_performance": rows,
                "ga4": {"views": 5, "active_users": 2}}
        data.update(kw)
        return data

    def _exposed_rows(self, count=3, **kw):
        return [self._row(slug=f"art-{i}", gsc=kw) for i in range(count)]

    def _missing_row(self, slug="missing"):
        """A deployed article the analytics pull found no GSC row for."""
        return {"id": slug,
                "canonical_url": f"https://uutistenlukija.fi/uutiset/{slug}",
                "deployed": True,
                "gsc": {"status": "missing"},
                "metadata": {"description": True, "og": True, "jsonld": True}}

    def _assert_abstains(self, data):
        hypotheses = learn.diagnose(data, [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        verdict = hypotheses[0]
        self.assertEqual(verdict["verdict"], "insufficient_evidence")
        self.assertEqual(verdict["confidence"], "no_evidence")
        self.assertIn("Evidence gate failed", verdict["evidence"])
        for key in self.REPORT_KEYS:
            self.assertIn(key, verdict)
        return verdict

    def _assert_no_nonfinite_leaks(self, hypothesis):
        """An abstention or verdict must never carry inf/nan into its own report text."""
        for key, value in hypothesis.items():
            if isinstance(value, float):
                self.assertTrue(math.isfinite(value), f"{key} is not finite: {value!r}")
            elif isinstance(value, str):
                self.assertIsNone(re.search(r"\b(?:inf|nan)\b", value, re.IGNORECASE),
                                  f"{key} exposes a non-finite value: {value!r}")

    def test_tiny_cohort_abstains(self):
        rows = [self._row(gsc={"clicks": 0, "impressions": 40, "position": 6.0})]
        self._assert_abstains(self._data(rows))

    def test_unknown_measurement_status_abstains(self):
        data = self._data(self._exposed_rows())
        del data["measurement_status"]
        self._assert_abstains(data)

    def test_truncated_measurement_abstains(self):
        self._assert_abstains(self._data(self._exposed_rows(), truncated=True))

    def test_domain_only_totals_abstain(self):
        data = {"ga4": {"views": 4, "active_users": 3},
                "gsc": {"impressions": 9000, "clicks": 12}}
        self._assert_abstains(data)

    def test_unpublished_row_abstains(self):
        self._assert_abstains(self._data([self._row(deployed=False)]))

    def test_foreign_url_abstains(self):
        row = self._row(canonical_url="https://example.com/uutiset/a")
        self._assert_abstains(self._data([row]))

    def test_invalid_rows_fail_closed(self):
        cases = [
            {"clicks": True},                          # bool is not a number
            {"impressions": float("nan")},             # non-finite
            {"position": 0.0},                         # position below 1
            {"clicks": -1},                            # negative
            {"clicks": 500},                           # clicks above impressions
            {"impressions": "500"},                    # string, not a number
        ]
        for override in cases:
            with self.subTest(override=override):
                self._assert_abstains(self._data([self._row(gsc=override)]))
        broken_status = self._row()
        broken_status["gsc"]["status"] = "error"
        self._assert_abstains(self._data([broken_status]))
        self._assert_abstains(self._data(["not-a-row"]))
        self._assert_abstains(self._data([self._row(id="")]))
        huge = self._row()
        huge["gsc"]["impressions"] = 10 ** 400
        self._assert_abstains(self._data([huge]))

    def test_non_exact_canonical_urls_abstain(self):
        cases = [
            "https://uutistenlukija.fi/uutiset/../posts/legacy/",   # traversal
            "https://uutistenlukija.fi/uutiset/validarticle?x=1",   # query
            "https://uutistenlukija.fi/uutiset/validarticle#x",     # fragment
            "https://uutistenlukija.fi/uutiset/",                   # no article suffix
        ]
        for canonical_url in cases:
            with self.subTest(canonical_url=canonical_url):
                row = self._row(canonical_url=canonical_url)
                self._assert_abstains(self._data([row]))

    def test_exact_canonical_article_stays_tentative(self):
        row = self._row(slug="validarticle",
                        gsc={"clicks": 1, "impressions": 500, "position": 5.0})
        hypotheses = learn.diagnose(self._data([row]), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        self.assertEqual(hypotheses[0]["verdict"], "tentative")

    def test_duplicate_canonical_rows_abstain(self):
        self._assert_abstains(self._data([self._row(slug="same"), self._row(slug="same")]))

    def test_aggregate_overflow_from_individually_valid_rows_abstains(self):
        # Two rows are each valid on their own (clicks 0 <= impressions 1e308, position 5),
        # but their impressions sum past the finite float range. The aggregate is not
        # evidence, so it must abstain rather than emit an inf/nan-bearing hypothesis.
        rows = [self._row(slug="huge-a", gsc={"clicks": 0, "impressions": 1e308,
                                             "position": 5.0}),
                self._row(slug="huge-b", gsc={"clicks": 0, "impressions": 1e308,
                                              "position": 5.0})]
        verdict = self._assert_abstains(self._data(rows))
        self.assertIn("not finite", verdict["evidence"])
        self._assert_no_nonfinite_leaks(verdict)

    def test_huge_finite_click_ratio_is_not_falsely_healthy(self):
        # 100 * clicks overflows to +inf for huge-but-valid clicks, which used to make a
        # 1.9% cohort look like a healthy CTR and suppress the verdict entirely.
        row = self._row(slug="huge-clicks", gsc={"clicks": 1.9e306, "impressions": 1e308,
                                                 "position": 1.0})
        hypotheses = learn.diagnose(self._data([row]), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        self.assertEqual(hypotheses[0]["verdict"], "tentative")
        self.assertIn("1.90% CTR", hypotheses[0]["evidence"])
        self._assert_no_nonfinite_leaks(hypotheses[0])
        # A genuinely healthy ratio on the same huge scale still yields no verdict.
        healthy = self._row(slug="huge-healthy", gsc={"clicks": 5e306, "impressions": 1e308,
                                                      "position": 1.0})
        self.assertEqual(learn.diagnose(self._data([healthy]), []), [])

    def test_overflowing_weighted_position_abstains_rather_than_reporting_nan(self):
        row = self._row(slug="huge-position", gsc={"clicks": 1, "impressions": 1e308,
                                                   "position": 5.0})
        verdict = self._assert_abstains(self._data([row]))
        self._assert_no_nonfinite_leaks(verdict)

    def test_duplicate_article_ids_with_distinct_urls_abstain(self):
        first = self._row(slug="same-id", gsc={"clicks": 1, "impressions": 500, "position": 5.0})
        second = self._row(slug="same-id", gsc={"clicks": 1, "impressions": 500, "position": 5.0})
        second["canonical_url"] = "https://uutistenlukija.fi/uutiset/same-id-second"
        verdict = self._assert_abstains(self._data([first, second]))
        self.assertIn("duplicate article ids", verdict["evidence"])

    def test_duplicate_article_ids_cannot_pad_evidence_with_missing_or_zero_rows(self):
        measured = self._row(slug="dup", gsc={"clicks": 1, "impressions": 1000,
                                              "position": 8.0})
        missing = self._missing_row("dup")
        missing["canonical_url"] = "https://uutistenlukija.fi/uutiset/dup-missing"
        self._assert_abstains(self._data([measured, missing]))
        quiet = self._row(slug="dup", gsc={"clicks": 0, "impressions": 0, "position": None})
        quiet["canonical_url"] = "https://uutistenlukija.fi/uutiset/dup-quiet"
        self._assert_abstains(self._data([measured, quiet]))

    def test_distinct_ids_on_distinct_urls_remain_tentative(self):
        rows = [self._row(slug="one", gsc={"clicks": 1, "impressions": 500, "position": 5.0}),
                self._row(slug="two", gsc={"clicks": 1, "impressions": 500, "position": 5.0})]
        hypotheses = learn.diagnose(self._data(rows), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        self.assertEqual(hypotheses[0]["verdict"], "tentative")

    def test_missing_gsc_row_does_not_discard_the_measured_cohort(self):
        """Normal complete analytics: some deployed articles simply have no GSC row."""
        rows = [self._row(slug="low", gsc={"clicks": 1, "impressions": 1000, "position": 8.0}),
                self._missing_row()]
        hypotheses = learn.diagnose(self._data(rows), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        hypothesis = hypotheses[0]
        self.assertEqual(hypothesis["verdict"], "tentative")
        # Coverage must be explicit: measured/exposed/missing counts, no bare domain claim.
        evidence = hypothesis["evidence"]
        self.assertIn("1 clicks / 1000 impressions", evidence)
        self.assertIn("1 exposed URL(s)", evidence)
        self.assertIn("1 measured row(s)", evidence)
        self.assertIn("1 deployed article(s) with a missing GSC row", evidence)
        self.assertIn("never counted as zero", evidence)
        self.assertIn(hypothesis["confidence"], ("low", "medium"))
        self.assertNotEqual(hypothesis["confidence"], "high")

    def test_missing_rows_are_never_read_as_zero(self):
        # A missing row is excluded, not imputed, so it cannot pad impressions or breadth.
        rows = [self._row(slug="low", gsc={"clicks": 1, "impressions": 1000, "position": 8.0}),
                self._missing_row("m0"), self._missing_row("m1"), self._missing_row("m2")]
        hypothesis = learn.diagnose(self._data(rows), [])[0]
        self.assertIn("1 exposed URL(s)", hypothesis["evidence"])
        self.assertIn("3 deployed article(s) with a missing GSC row", hypothesis["evidence"])
        self.assertIn("0.10% CTR", hypothesis["evidence"])
        # Breadth is exposure, not deployed count: three missing rows cannot lift confidence.
        self.assertEqual(hypothesis["confidence"], "low")

    def test_all_missing_gsc_rows_are_insufficient(self):
        self._assert_abstains(self._data([self._missing_row("m0"), self._missing_row("m1")]))

    def test_missing_and_zero_impressions_are_insufficient(self):
        zero = self._row(slug="quiet", gsc={"clicks": 0, "impressions": 0, "position": None})
        self._assert_abstains(self._data([zero, self._missing_row("m0")]))

    def test_missing_row_with_no_gsc_payload_is_unknown_coverage(self):
        for gsc in ({"status": "missing", "clicks": 0, "impressions": 0, "position": None},
                    None,
                    {}):
            with self.subTest(gsc=gsc):
                row = self._row(slug="absent")
                row["gsc"] = gsc
                rows = [self._row(slug="low", gsc={"clicks": 1, "impressions": 1000,
                                                   "position": 8.0}), row]
                hypothesis = learn.diagnose(self._data(rows), [])[0]
                self.assertEqual(hypothesis["verdict"], "tentative")
                self.assertIn("1 deployed article(s) with a missing GSC row",
                              hypothesis["evidence"])

    def test_zero_impression_rows_cannot_raise_confidence(self):
        # Impressions dominate the weighted position, but breadth must come from exposure.
        exposed = self._row(slug="exposed",
                            gsc={"clicks": 1, "impressions": 1000, "position": 9.0})
        unexposed = [self._row(slug=f"quiet-{i}",
                               gsc={"clicks": 0, "impressions": 0, "position": None})
                     for i in range(10)]
        hypothesis = learn.diagnose(self._data([exposed] + unexposed), [])[0]
        self.assertEqual(hypothesis["confidence"], "low")
        self.assertIn("1 exposed URL(s)", hypothesis["evidence"])
        self.assertIn("11 measured row(s)", hypothesis["evidence"])
        self.assertIn("position 9", hypothesis["evidence"])

    def test_zero_impression_rows_generate_no_metadata_advice(self):
        exposed = self._row(slug="exposed", gsc={"clicks": 1, "impressions": 1000, "position": 9.0},
                            metadata={"description": True, "og": True, "jsonld": True})
        lean = self._row(slug="quiet-0", gsc={"clicks": 0, "impressions": 0, "position": None},
                         metadata={"description": False, "og": False, "jsonld": False})
        quiet_two = self._row(slug="quiet-1", gsc={"clicks": 0, "impressions": 0, "position": None},
                              metadata={"description": None, "og": None, "jsonld": None})
        action = learn.diagnose(self._data([exposed, lean, quiet_two]), [])[0]["action"]
        self.assertNotIn("Audit/fill", action)
        self.assertNotIn("Verify", action)
        self.assertNotIn("quiet-0", action)
        self.assertNotIn("quiet-1", action)

    def test_positive_impressions_with_no_position_still_abstains(self):
        cases = [{"clicks": 1, "impressions": 500},
                 {"clicks": 1, "impressions": 500, "position": None},
                 {"clicks": 1, "impressions": 500, "position": 0.0},
                 {"clicks": 1, "impressions": 500, "position": float("nan")}]
        for override in cases:
            with self.subTest(override=override):
                row = self._row(slug="noposition")
                row["gsc"] = {"status": "ok", **override}
                self._assert_abstains(self._data([row]))

    def test_positive_impressions_with_position_one_is_valid(self):
        rows = [self._row(slug="top", gsc={"clicks": 1, "impressions": 1000, "position": 1.0})]
        hypotheses = learn.diagnose(self._data(rows), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        self.assertEqual(hypotheses[0]["verdict"], "tentative")
        self.assertIn("position 1", hypotheses[0]["evidence"])

    def test_zero_impression_zero_click_row_with_no_position_is_valid(self):
        rows = [self._row(slug="quiet", gsc={"clicks": 0, "impressions": 0, "position": None}),
                self._row(slug="low", gsc={"clicks": 1, "impressions": 1000, "position": 8.0})]
        hypotheses = learn.diagnose(self._data(rows), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        self.assertEqual(hypotheses[0]["verdict"], "tentative")
        self.assertIn("1 exposed URL(s)", hypotheses[0]["evidence"])
        self.assertIn("1000 impressions", hypotheses[0]["evidence"])

    def test_missing_rows_cannot_raise_confidence_or_mint_advice(self):
        exposed = self._row(slug="exposed", gsc={"clicks": 1, "impressions": 1000, "position": 9.0})
        absent = [self._missing_row(f"m{i}") for i in range(6)]
        for row in absent:
            row["metadata"] = {"description": False, "og": False, "jsonld": False}
        hypothesis = learn.diagnose(self._data([exposed] + absent), [])[0]
        self.assertEqual(hypothesis["confidence"], "low")
        self.assertNotIn("Audit/fill", hypothesis["action"])
        self.assertNotIn("Verify", hypothesis["action"])

    def test_invalid_observed_metrics_still_abstain_with_missing_rows_present(self):
        broken = self._row(slug="broken", gsc={"clicks": 1, "impressions": 500,
                                               "position": float("inf")})
        self._assert_abstains(self._data([broken, self._missing_row()]))
        errored = self._row(slug="errored")
        errored["gsc"]["status"] = "error"
        self._assert_abstains(self._data([errored, self._missing_row()]))

    def test_zero_click_exposed_cohort_is_allowed(self):
        rows = self._exposed_rows(3, clicks=0, impressions=500, position=8.0)
        hypotheses = learn.diagnose(self._data(rows), [])
        self.assertEqual(len(hypotheses), 1, hypotheses)
        self.assertEqual(hypotheses[0]["lane"], "seo")
        self.assertEqual(hypotheses[0]["verdict"], "tentative")
        self.assertIn("0 clicks / 1500 impressions", hypotheses[0]["evidence"])
        self.assertNotEqual(hypotheses[0]["confidence"], "high")

    def test_low_ctr_position_drives_the_investigation(self):
        page_one = self._data(self._exposed_rows(3, clicks=1, impressions=500, position=4.0))
        beyond = self._data(self._exposed_rows(3, clicks=1, impressions=500, position=28.0))
        near = learn.diagnose(page_one, [])[0]
        far = learn.diagnose(beyond, [])[0]
        self.assertIn("query/title intent", near["action"])
        self.assertIn("ranking/visibility", far["action"])
        self.assertIn("ranking/visibility", far["hypothesis"])
        self.assertIn("position 4", near["evidence"])
        self.assertIn("position 28", far["evidence"])
        for hypothesis in (near, far):
            self.assertIn("not causal proof", hypothesis["hypothesis"])
            self.assertNotIn("Snippets win impressions", hypothesis["hypothesis"])
            self.assertNotIn("rewrite titles", hypothesis["action"])

    def test_evidence_names_values_and_the_url_set(self):
        rows = [self._row(slug="alpha", gsc={"clicks": 2, "impressions": 400, "position": 3.5}),
                self._row(slug="beta", gsc={"clicks": 1, "impressions": 300, "position": 12.0})]
        hypothesis = learn.diagnose(self._data(rows), [])[0]
        self.assertIn("3 clicks / 700 impressions", hypothesis["evidence"])
        self.assertIn("https://uutistenlukija.fi/uutiset/alpha", hypothesis["evidence"])
        self.assertIn("https://uutistenlukija.fi/uutiset/beta", hypothesis["evidence"])
        self.assertEqual(hypothesis["confidence"], "low")

    def test_medium_confidence_needs_exposure_and_breadth(self):
        small = self._exposed_rows(1, clicks=1, impressions=500, position=5.0)
        broad = self._exposed_rows(4, clicks=4, impressions=500, position=5.0)
        self.assertEqual(learn.diagnose(self._data(small), [])[0]["confidence"], "low")
        self.assertEqual(learn.diagnose(self._data(broad), [])[0]["confidence"], "medium")

    def test_present_metadata_is_never_recommended(self):
        rows = self._exposed_rows(3, clicks=1, impressions=500, position=5.0)
        hypothesis = learn.diagnose(self._data(rows), [])[0]
        self.assertNotIn("Audit/fill", hypothesis["action"])
        self.assertNotIn("Verify", hypothesis["action"])
        self.assertNotIn("missing metadata", hypothesis["action"])

    def test_missing_metadata_is_named_accurately(self):
        metadata = {"description": False, "og": True, "jsonld": True}
        rows = [self._row(slug=f"art-{i}", gsc={"clicks": 1, "impressions": 500, "position": 5.0},
                          metadata=dict(metadata)) for i in range(3)]
        action = learn.diagnose(self._data(rows), [])[0]["action"]
        self.assertIn("Audit/fill", action)
        self.assertIn("description on", action)
        self.assertIn("https://uutistenlukija.fi/uutiset/art-0", action)
        self.assertNotIn("og on", action)
        self.assertNotIn("jsonld on", action)

    def test_numeric_zero_metadata_is_unknown_not_missing(self):
        metadata = {"description": 0, "og": True, "jsonld": True}
        rows = [self._row(slug=f"art-{i}", gsc={"clicks": 1, "impressions": 500, "position": 5.0},
                          metadata=dict(metadata)) for i in range(3)]
        action = learn.diagnose(self._data(rows), [])[0]["action"]
        self.assertIn("Verify", action)
        self.assertIn("description", action)
        self.assertNotIn("Audit/fill", action)

    def test_unknown_metadata_must_be_verified_first(self):
        metadata = {"description": True, "og": None, "jsonld": True}
        rows = [self._row(slug=f"art-{i}", gsc={"clicks": 1, "impressions": 500, "position": 5.0},
                          metadata=dict(metadata)) for i in range(3)]
        action = learn.diagnose(self._data(rows), [])[0]["action"]
        self.assertIn("Verify", action)
        self.assertIn("og", action)
        self.assertNotIn("Audit/fill", action)

    def test_huge_domain_gap_produces_no_volume_or_ceiling_action(self):
        rows = self._exposed_rows(3, clicks=1, impressions=500, position=5.0)
        data = self._data(rows, ga4={"views": 3, "active_users": 1})
        hypotheses = learn.diagnose(data, [])
        self.assertTrue(hypotheses)
        for hypothesis in hypotheses:
            self.assertNotEqual(hypothesis["lane"], "volume")
            self.assertNotIn("ceiling", hypothesis["action"].lower())
            self.assertNotIn("ceiling", hypothesis["target"].lower())
            self.assertNotIn("publishing volume", hypothesis["hypothesis"].lower())

    def test_articles_only_observations_produce_no_readership_diagnosis(self):
        articles = [{"id": f"a{i}", "title": "T" * 120, "category": "Kotimaa",
                     "has_image": False, "title_length": 120, "summary_length": 5}
                    for i in range(20)]
        for data in ({}, {"ga4": {"views": 3, "active_users": 1}}, None):
            with self.subTest(data=data):
                self._assert_abstains(data if data is not None else {})
                hypotheses = learn.diagnose(data, articles)
                self.assertEqual(len(hypotheses), 1, hypotheses)
                self.assertEqual(hypotheses[0]["verdict"], "insufficient_evidence")

    def test_healthy_ctr_yields_no_verdict(self):
        rows = self._exposed_rows(3, clicks=40, impressions=500, position=3.0)
        self.assertEqual(learn.diagnose(self._data(rows), []), [])
        text = learn.format_report({"ok": True, "goal": learn.goal_status({}), "articles": 3,
                                    "hypotheses": []})
        self.assertIn("No hypotheses", text)
        self.assertNotIn("insufficient", text.lower())

    def test_hypotheses_are_ranked_and_report_compatible(self):
        rows = self._exposed_rows(3, clicks=1, impressions=500, position=5.0)
        hypotheses = learn.diagnose(self._data(rows), [])
        priorities = [h["priority"] for h in hypotheses]
        self.assertEqual(priorities, sorted(priorities), priorities)
        for hypothesis in hypotheses:
            for key in self.REPORT_KEYS:
                self.assertIn(key, hypothesis)
        text = learn.format_report({"ok": True, "goal": learn.goal_status({}), "articles": 3,
                                    "hypotheses": hypotheses})
        self.assertIn("seo", text)
        self.assertIn("impressions", text)


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

    def test_old_review_rows_stay_readable_after_the_measurement_seam(self):
        """Pre-seam rows carry no hypotheses/measurement; history and delta must not break."""
        with tempfile.TemporaryDirectory() as tmp:
            learn.record({"kind": "review", "goal": {"views": 1, "users": 1},
                          "articles_published": 2}, Path(tmp))
            with mock.patch.object(learn, "measure") as measure, \
                    mock.patch.object(learn, "read_published"):
                measure.return_value = {"ok": True, "data": {
                    "measurement_status": "ok", "truncated": False,
                    "article_performance": [],
                    "ga4": {"views": 3, "active_users": 1, "dimension_free": True,
                            "status": "ok"}}}
                result = learn.review(state_dir=Path("/tmp/state"), learning_dir=Path(tmp))
            rows = learn.history(Path(tmp))
            self.assertTrue(result["ok"])
            self.assertEqual(rows[0]["kind"], "review")
            self.assertEqual(rows[1]["delta"], {"views": 2, "users": 0, "articles": -2})


class ReviewSeam(unittest.TestCase):
    """review() must consume the joined collector report and persist it whole."""

    def _measure(self, data):
        patcher = mock.patch.object(learn, "measure")
        measure = patcher.start()
        self.addCleanup(patcher.stop)
        measure.return_value = {"ok": True, "data": data}
        return measure

    def _forbid_structural_reads(self):
        patcher = mock.patch.object(learn, "read_published",
                                    side_effect=AssertionError("review must not read published"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _row(self, slug, **kw):
        row = {"id": slug,
               "canonical_url": f"https://uutistenlukija.fi/uutiset/{slug}",
               "deployed": True,
               "gsc": {"status": "ok", "clicks": 1, "impressions": 500, "position": 5.0},
               "metadata": {"description": True, "og": True, "jsonld": True}}
        row.update(kw)
        return row

    def test_forwards_state_dir_and_uses_the_joined_report_only(self):
        state_dir = Path("/tmp/review-state")
        rows = [self._row(f"art-{i}") for i in range(3)]
        data = {"measurement_status": "ok", "truncated": False,
                "article_performance": rows,
                "ga4": {"views": 5, "active_users": 2},
                "windows": {"gsc": "28d", "ga4": "28d"},
                "providers": ["ga4", "gsc"],
                "cohorts": [{"name": "landing", "rows": 3}],
                "limitations": ["cohort rows are landing-page grouped"],
                "coverage": {"measured": 3, "missing": 0}}
        measure = self._measure(data)
        self._forbid_structural_reads()
        with tempfile.TemporaryDirectory() as tmp:
            result = learn.review(state_dir=state_dir, learning_dir=Path(tmp))
            persisted = learn.history(Path(tmp))[-1]
        measure.assert_called_once_with(state_dir=state_dir)
        self.assertTrue(result["ok"])
        self.assertEqual(result["articles"], 3)
        self.assertEqual(result["hypotheses"][0]["verdict"], "tentative")
        self.assertEqual(result["measurement"], data)
        self.assertEqual(persisted["hypotheses"], result["hypotheses"])
        self.assertEqual(persisted["measurement"], data)
        self.assertEqual(persisted["kind"], "review")

    def test_missing_or_nonlist_article_performance_yields_insufficient(self):
        cases = {"absent": "absent", "null": None, "string": "rows",
                 "mapping": {"id": "a"}, "empty": []}
        for label, rows in cases.items():
            with self.subTest(case=label):
                data = {"measurement_status": "ok", "truncated": False}
                if rows != "absent":
                    data["article_performance"] = rows
                self._measure(data)
                self._forbid_structural_reads()
                with tempfile.TemporaryDirectory() as tmp:
                    result = learn.review(state_dir=Path("/tmp/state"), learning_dir=Path(tmp))
                    persisted = learn.history(Path(tmp))[-1]
                self.assertEqual(result["articles"], 0)
                self.assertEqual(result["hypotheses"][0]["verdict"], "insufficient_evidence")
                self.assertEqual(persisted["measurement"], data)

    def test_tiny_and_truncated_reports_persist_insufficient_verdict(self):
        tiny = {"measurement_status": "ok", "truncated": False,
                "article_performance": [self._row("small", gsc={"status": "ok", "clicks": 0,
                                                              "impressions": 40, "position": 6.0})]}
        truncated = {"measurement_status": "ok", "truncated": True,
                     "article_performance": [self._row("art-0")]}
        for data in (tiny, truncated):
            with self.subTest(data=data):
                self._measure(data)
                self._forbid_structural_reads()
                with tempfile.TemporaryDirectory() as tmp:
                    result = learn.review(state_dir=Path("/tmp/state"), learning_dir=Path(tmp))
                    persisted = learn.history(Path(tmp))[-1]
                self.assertEqual(result["hypotheses"][0]["verdict"], "insufficient_evidence")
                self.assertEqual(persisted["hypotheses"], result["hypotheses"])
                self.assertEqual(persisted["measurement"], data)

    def test_error_report_is_not_measured_into_a_ledger_review(self):
        measure = mock.patch.object(learn, "measure",
                                    return_value={"ok": False, "error": "boom"})
        measure.start()
        self.addCleanup(measure.stop)
        self._forbid_structural_reads()
        with tempfile.TemporaryDirectory() as tmp:
            result = learn.review(state_dir=Path("/tmp/state"), learning_dir=Path(tmp))
            rows = learn.history(Path(tmp))
        self.assertFalse(result["ok"])
        self.assertEqual(rows[-1]["kind"], "review_failed")


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


class Actions(unittest.TestCase):
    def test_record_action_appends_to_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = learn.record_action("Enabled generated images", lane="publishing_quality",
                                      learning_dir=Path(tmp))
            self.assertEqual(row["kind"], "action")
            self.assertEqual(learn.history(Path(tmp))[0]["description"], "Enabled generated images")

    def test_report_shows_delta_and_actions_when_present(self):
        result = {"ok": True, "goal": {"views": 70, "views_target": 10000, "views_pct": 0.7,
                                       "users": 55, "users_target": 1000, "users_pct": 5.5},
                  "articles": 20, "hypotheses": [],
                  "delta": {"views": 4, "users": 2, "articles": 1},
                  "actions": [{"description": "Enabled generated images", "lane": "publishing_quality"}]}
        text = learn.format_report(result)
        self.assertIn("Since last review", text)
        self.assertIn("Enabled generated images", text)

    def test_report_without_delta_stays_compatible(self):
        result = {"ok": True, "goal": {"views": 1, "views_target": 10000, "views_pct": 0.01,
                                       "users": 1, "users_target": 1000, "users_pct": 0.1},
                  "articles": 1, "hypotheses": []}
        self.assertNotIn("Since last review", learn.format_report(result))


if __name__ == "__main__":
    unittest.main()
