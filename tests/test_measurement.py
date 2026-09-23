import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_mvp import measurement
from news_mvp.measurement import classify_path, collect, join_rows, normalize_url
from news_mvp.site import article_path

SITE = "https://uutistenlukija.fi"


class NormalizeUrlTest(unittest.TestCase):
    def test_site_urls_and_paths(self):
        self.assertEqual(normalize_url(SITE + "/uutiset/2024/01/foo/"), "/uutiset/2024/01/foo/")
        self.assertEqual(normalize_url("/uutiset/2024/01/foo/"), "/uutiset/2024/01/foo/")
        self.assertEqual(normalize_url("/sivu/2/", "uutistenlukija.fi"), "/sivu/2/")
        self.assertEqual(normalize_url(SITE), "/")
        self.assertEqual(normalize_url(SITE + "?x=1"), "/")

    def test_query_and_fragment_removed(self):
        self.assertEqual(normalize_url("/uutiset/x?utm=1&b=2"), "/uutiset/x")
        self.assertEqual(normalize_url(SITE + "/sivu/2/?page=3#top"), "/sivu/2/")

    def test_path_case_and_trailing_slash_preserved(self):
        self.assertEqual(normalize_url("/Uutiset/X/"), "/Uutiset/X/")
        self.assertNotEqual(normalize_url("/uutiset/x"), normalize_url("/uutiset/x/"))

    def test_foreign_and_host_mismatch(self):
        for value in (
            "https://example.com/uutiset/x",
            "https://www.uutistenlukija.fi/uutiset/x",
            "https://sub.uutistenlukija.fi/",
            "https://uutistenlukija.fi.evil.com/uutiset/x",
            "http://uutistenlukija.fi/uutiset/x",
            "https://uutistenlukija.fi:8443/uutiset/x",
            "https://user:pass@uutistenlukija.fi/uutiset/x",
            "https:/uutistenlukija.fi/uutiset/x",
        ):
            self.assertIsNone(normalize_url(value), value)
        self.assertIsNone(normalize_url("/uutiset/x", "example.com"))
        self.assertIsNone(normalize_url("/uutiset/x", "www.uutistenlukija.fi"))

    def test_malformed_traversal_and_control(self):
        for value in (
            "//uutistenlukija.fi/uutiset/x",
            "//evil.com/uutiset/x",
            "uutiset/x",
            "/uutiset/%zz",
            "/uutiset/%2",
            "/uutiset/%2e%2e/secret",
            "/uutiset/%2E%2E/",
            "/uutiset/%2e/",
            "/a/../uutiset/",
            "/uutiset/%2fetc/passwd",
            "/uutiset/%5c",
            "/uutiset\\x",
            "https://uutistenlukija.fi\\@evil.com/uutiset/",
            "/uutiset/ x",
            "/uutiset/a%20b/",
            "/uutiset/\tx",
            "/uutiset/x\n",
            "/uutiset/\x00x",
        ):
            self.assertIsNone(normalize_url(value), value)

    def test_empty_unknown_and_no_implicit_root(self):
        for value in ("", "(not set)", "(NOT SET)", "(none)", "unknown", None, 42, "?q=1", "#f"):
            self.assertIsNone(normalize_url(value), value)
        self.assertEqual(normalize_url("/"), "/")

    def test_host_argument_absent_or_matching(self):
        self.assertEqual(normalize_url("/uutiset/x"), "/uutiset/x")
        self.assertEqual(normalize_url("/uutiset/x", "uutistenlukija.fi"), "/uutiset/x")
        self.assertEqual(normalize_url("/uutiset/x", "UUTISTENLUKIJA.FI"), "/uutiset/x")

    def test_explicit_host_requires_exact_site_host(self):
        for host in ("", "(not set)", "(NOT SET)", "unknown", "none", "-", " uutistenlukija.fi",
                     "uutistenlukija.fi ", "uutistenlukija.fi.", "www.uutistenlukija.fi",
                     "uutistenlukija.fi:443", "sub.uutistenlukija.fi", "example.com", 42):
            self.assertIsNone(normalize_url("/uutiset/x", host), host)
            self.assertEqual(classify_path("/uutiset/x", host), "excluded", host)
        self.assertEqual(classify_path("/uutiset/x", "uutistenlukija.fi"), "reboot")

    def test_malformed_url_returns_none(self):
        for value in ("https://[broken/", "https://[broken/uutiset/x", "https://uutistenlukija.fi[/x"):
            self.assertIsNone(normalize_url(value), value)
            self.assertEqual(classify_path(value), "excluded", value)

    def test_userinfo_and_explicit_port_rejected(self):
        for value in (
            "https://@uutistenlukija.fi/uutiset/a/",
            "https://:pass@uutistenlukija.fi/uutiset/a/",
            "https://user@uutistenlukija.fi/uutiset/a/",
            "https://uutistenlukija.fi:/uutiset/a/",
            "https://uutistenlukija.fi:443/uutiset/a/",
            "https://uutistenlukija.fi:8443/uutiset/a/",
        ):
            self.assertIsNone(normalize_url(value), value)
            self.assertEqual(classify_path(value), "excluded", value)

    def test_ambiguous_decoding_rejected(self):
        for value in (
            "/uutiset/a%3Fb/",
            "/uutiset/a%23b/",
            "/uutiset/a%252fb/",
            "/uutiset/a%2525b/",
            SITE + "/uutiset/a%3Fb/",
        ):
            self.assertIsNone(normalize_url(value), value)
            self.assertEqual(classify_path(value), "excluded", value)

    def test_safe_utf8_and_idempotent_normalization(self):
        fixtures = (
            "/uutiset/x",
            "/uutiset/x/",
            "/uutiset/%C3%A4/",
            "/uutiset/caf%C3%A9/",
            "/uutiset/%E2%82%AC/",
            "/uutiset/2024/01/foo/?utm=1#top",
            SITE,
            SITE + "/sivu/2/",
        )
        for value in fixtures:
            once = normalize_url(value)
            self.assertIsNotNone(once, value)
            self.assertEqual(normalize_url(once), once, value)
            self.assertEqual(classify_path(once), classify_path(value), value)


class ClassifyPathTest(unittest.TestCase):
    def test_reboot(self):
        for value in ("/", SITE + "/", "/uutiset/", "/uutiset/2024/01/foo/",
                      SITE + "/uutiset/2024/01/foo/", "/sivu/", "/sivu/2/",
                      "/uutiset/x?utm=1"):
            self.assertEqual(classify_path(value), "reboot", value)

    def test_legacy_and_prefix_boundary(self):
        for value in ("/uutiset", "/sivu", "/uutisetfake/", "/uutisetfake", "/sivut/",
                      "/sivu2/", "/blog/post/", "/oppaat/", "/posts/1", "/muu", "/Uutiset/x/"):
            self.assertEqual(classify_path(value), "legacy", value)

    def test_excluded(self):
        for value in ("", "(not set)", None, "https://example.com/uutiset/x",
                      "https://uutistenlukija.fi/uutiset/%2e%2e/x", "//evil.com/uutiset/x",
                      "/a/../uutiset/", "/uutiset/ x"):
            self.assertEqual(classify_path(value), "excluded", value)
        self.assertEqual(classify_path("/uutiset/x", "example.com"), "excluded")
        self.assertEqual(classify_path("/uutiset/x", "uutistenlukija.fi"), "reboot")


class JoinRowsArticleValidationTest(unittest.TestCase):
    """Fail-closed article input: only exact deployed /uutiset/... canonicals join."""

    def _article(self, **overrides):
        article = {
            "id": "a1",
            "canonical_url": SITE + "/uutiset/2026/09/example/",
            "deployed": True,
            "aliases": [],
            "metadata": {"description": True, "og": False, "jsonld": None},
        }
        article.update(overrides)
        return article

    def _gsc_row(self, page="/uutiset/2026/09/example/", **overrides):
        row = {"page": page, "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3.0}
        row.update(overrides)
        return row

    def _ga4_row(self, landing_page="/uutiset/2026/09/example/", **overrides):
        row = {"landing_page": landing_page, "hostname": "uutistenlukija.fi",
               "views": 4, "active_users": 3, "sessions": 2}
        row.update(overrides)
        return row

    def test_not_deployed_rejected(self):
        for deployed in (False, None, "true", 1, 0):
            with self.assertRaises(ValueError, msg=deployed):
                join_rows([self._article(deployed=deployed)], [], [])

    def test_foreign_and_nonarticle_canonical_rejected(self):
        for canonical in (
            "https://example.com/uutiset/x/",
            "https://www.uutistenlukija.fi/uutiset/x/",
            "http://uutistenlukija.fi/uutiset/x/",
            "/uutiset/2026/09/example/",         # path-only: not the exact absolute canonical
            "/posts/2026/09/example/",          # legacy site path, not a deployed article
            "/sivu/2/",                          # reboot archive, not a deployed article
            "/",                                 # root, not a deployed article
            "/uutiset",                          # bare prefix is legacy, not an article
            "/uutiset/",                         # empty suffix after the /uutiset/ prefix
            "/uutisetfake/x/",                   # boundary lookalike is legacy
            "uutiset/x/",                        # relative, ambiguous
            "//uutistenlukija.fi/uutiset/x/",    # protocol-relative
            "/uutiset/%2e%2e/secret",            # traversal
            None,
        ):
            with self.assertRaises(ValueError, msg=canonical):
                join_rows([self._article(canonical_url=canonical)], [], [])

    def test_noncanonical_full_urls_rejected_compactly(self):
        for canonical in (
            "https://uutistenlukija.fi/uutiset/x/?utm_source=feed",  # query must be stripped
            "https://uutistenlukija.fi/uutiset/x/#top",              # fragment must be stripped
            "https://uutistenlukija.fi/uutiset/%2e%2e/secret",       # traversal
            "https://uutistenlukija.fi/uutiset/",                    # empty /uutiset/ suffix
            "https://uutistenlukija.fi/",                            # rootuutiset
        ):
            with self.assertRaises(ValueError, msg=canonical):
                join_rows([self._article(canonical_url=canonical)], [], [])
        report = join_rows([self._article()], [], [])
        self.assertEqual(
            report["article_performance"][0]["canonical_url"],
            SITE + "/uutiset/2026/09/example/",
        )

    def test_duplicate_id_rejected(self):
        articles = [self._article(), self._article(canonical_url=SITE + "/uutiset/2026/09/other/")]
        with self.assertRaises(ValueError):
            join_rows(articles, [], [])

    def test_ambiguous_canonical_or_alias_ownership_rejected(self):
        first = self._article(id="a1", aliases=["/uutiset/2026/09/shared/"])
        duplicate_canonical = self._article(id="a2", canonical_url=SITE + "/uutiset/2026/09/example/")
        with self.assertRaises(ValueError):
            join_rows([first, duplicate_canonical], [], [])
        alias_owner = self._article(id="a3", canonical_url=SITE + "/uutiset/2026/09/other/",
                                    aliases=["/uutiset/2026/09/shared/"])
        with self.assertRaises(ValueError):
            join_rows([first, alias_owner], [], [])

    def test_alias_input_fail_closed(self):
        for aliases in ("/uutiset/old/", {"url": "/uutiset/old/"}, [42], ["/uutiset/old/", "/uutiset/old/"]):
            with self.assertRaises(ValueError, msg=aliases):
                join_rows([self._article(aliases=aliases)], [], [])
        for alias in ("https://example.com/uutiset/old/", "/uutiset/%zz", "uutiset/old/"):
            with self.assertRaises(ValueError, msg=alias):
                join_rows([self._article(aliases=[alias])], [], [])

    def test_metadata_unknown_kept_unknown_and_types_enforced(self):
        report = join_rows([self._article(metadata={"description": True})], [], [])
        self.assertEqual(
            report["article_performance"][0]["metadata"],
            {"description": True, "og": None, "jsonld": None},
        )
        for metadata in ({"description": "yes"}, {"og": 1}, {"jsonld": 0}, "present", 42):
            with self.assertRaises(ValueError, msg=metadata):
                join_rows([self._article(metadata=metadata)], [], [])

    def test_missing_aliases_defaults_to_empty(self):
        report = join_rows([self._article(aliases=None)], [], [])
        self.assertEqual(report["article_performance"][0]["aliases"], [])


class JoinRowsMatchingTest(unittest.TestCase):
    """Exact normalized-path matching only; nothing is inferred."""

    def setUp(self):
        self.article = {
            "id": "a1",
            "canonical_url": "https://uutistenlukija.fi/uutiset/2026/09/example/",
            "deployed": True,
            "aliases": ["/uutiset/2026/09/old-slug/"],
            "metadata": {"description": True, "og": True, "jsonld": False},
        }

    def test_exact_canonical_alias_and_query_variant_join(self):
        gsc_rows = [
            {"page": "https://uutistenlukija.fi/uutiset/2026/09/example/?utm_source=x",
             "clicks": 2, "impressions": 10, "ctr": 0.2, "position": 5.0},
            {"page": "/uutiset/2026/09/old-slug/",
             "clicks": 1, "impressions": 5, "ctr": 0.2, "position": 8.0},
        ]
        ga4_rows = [
            {"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
             "views": 6, "active_users": 5, "sessions": 4},
            {"landing_page": "/uutiset/2026/09/old-slug/?ref=feed", "hostname": "uutistenlukija.fi",
             "views": 3, "active_users": 2, "sessions": 1},
        ]
        report = join_rows([self.article], gsc_rows, ga4_rows)
        self.assertEqual(report["measurement_status"], "ok")
        entry = report["article_performance"][0]
        self.assertEqual(entry["id"], "a1")
        self.assertEqual(entry["canonical_url"], SITE + "/uutiset/2026/09/example/")
        self.assertIs(entry["deployed"], True)
        self.assertEqual(entry["aliases"], ["/uutiset/2026/09/old-slug/"])
        self.assertEqual(entry["metadata"], {"description": True, "og": True, "jsonld": False})
        self.assertEqual(entry["gsc"]["status"], "ok")
        self.assertEqual(entry["gsc"]["clicks"], 3)
        self.assertEqual(entry["gsc"]["impressions"], 15)
        self.assertEqual(entry["gsc"]["position"], 6)  # (2*10 + 1*5) / 15
        self.assertAlmostEqual(entry["gsc"]["ctr"], 0.2)
        self.assertEqual(sorted(entry["gsc"]["paths"]),
                         ["/uutiset/2026/09/example/", "/uutiset/2026/09/old-slug/"])
        self.assertEqual(entry["ga4"]["status"], "ok")
        self.assertEqual(entry["ga4"]["views"], 9)
        self.assertEqual(entry["ga4"]["sessions"], 5)
        self.assertIsNone(entry["ga4"]["active_users"])
        self.assertIn("nonadditive", entry["ga4"]["note"])
        self.assertIn("landing page", entry["ga4"]["note"])

    def test_query_variants_aggregate_with_weighted_position(self):
        gsc_rows = [
            {"page": "/uutiset/2026/09/example/", "clicks": 2, "impressions": 10, "ctr": 0.2, "position": 5.0},
            {"page": "/uutiset/2026/09/example/?page=2", "clicks": 0, "impressions": 30, "ctr": 0.0, "position": 9.0},
        ]
        report = join_rows([self.article], gsc_rows, [])
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["impressions"], 40)
        self.assertEqual(entry["gsc"]["clicks"], 2)
        self.assertEqual(entry["gsc"]["position"], 8)  # (2*10 + 9*30) / 40
        self.assertEqual(entry["gsc"]["ctr"], 0.05)
        self.assertEqual(report["measurement_status"], "ok")

    def test_no_prefix_or_unreviewed_alias_inference(self):
        gsc_rows = [
            {"page": "/uutiset/2026/09/example/extra/", "clicks": 9, "impressions": 90, "ctr": 0.1, "position": 1.0},
            {"page": "/uutiset-extra/2026/09/example/", "clicks": 8, "impressions": 80, "ctr": 0.1, "position": 1.0},
            {"page": "/uutiset/2026/09/other-slug/", "clicks": 7, "impressions": 70, "ctr": 0.1, "position": 1.0},
        ]
        report = join_rows([self.article], gsc_rows, [])
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "missing")
        self.assertIsNone(entry["gsc"]["clicks"])
        self.assertIsNone(entry["gsc"]["impressions"])
        unmatched_paths = sorted(row["normalized_path"] for row in report["unmatched"])
        self.assertEqual(unmatched_paths, [
            "/uutiset-extra/2026/09/example/",
            "/uutiset/2026/09/example/extra/",
            "/uutiset/2026/09/other-slug/",
        ])
        for row in report["unmatched"]:
            self.assertIn("no supplied deployed article owns", row["reason"])
            self.assertIs(row["raw"], next(raw for raw in gsc_rows if raw["page"].endswith(row["normalized_path"])))

    def test_no_trailing_slash_or_scheme_guessing(self):
        articles = [
            {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/example", "deployed": True},
            {"id": "a2", "canonical_url": SITE + "/uutiset/2026/09/slashed/", "deployed": True},
        ]
        gsc_rows = [
            {"page": "/uutiset/2026/09/example/", "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 2.0},
            {"page": "https://uutistenlukija.fi/uutiset/2026/09/slashed", "clicks": 4,
             "impressions": 40, "ctr": 0.1, "position": 2.0},
        ]
        report = join_rows(articles, gsc_rows, [])
        self.assertEqual([entry["gsc"]["status"] for entry in report["article_performance"]],
                         ["missing", "missing"])
        self.assertEqual(report["providers"]["gsc"]["unmatched_rows"], 2)
        self.assertIn("no supplied deployed article owns", report["unmatched"][0]["reason"])

    def test_foreign_host_and_malformed_rows_excluded_with_reasons(self):
        gsc_rows = [
            {"page": "https://example.com/uutiset/2026/09/example/", "clicks": 1,
             "impressions": 10, "ctr": 0.1, "position": 3.0},
            {"page": "/uutiset/%zz", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3.0},
        ]
        ga4_rows = [
            {"landing_page": "/uutiset/2026/09/example/", "hostname": "example.com",
             "views": 5, "active_users": 2, "sessions": 3},
            {"landing_page": "/uutiset/2026/09/example/", "hostname": None,
             "views": 5, "active_users": 2, "sessions": 3},
            {"landing_page": "/uutiset/2026/09/example/", "hostname": "",
             "views": 5, "active_users": 2, "sessions": 3},
        ]
        report = join_rows([self.article], gsc_rows, ga4_rows)
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "missing")
        self.assertEqual(entry["ga4"]["status"], "missing")
        self.assertEqual(report["measurement_status"], "ok")
        self.assertEqual(report["cohorts"]["gsc"]["excluded"]["rows"], 2)
        self.assertEqual(report["cohorts"]["ga4"]["excluded"]["rows"], 3)
        reasons = [row["reason"] for row in report["unmatched"]]
        self.assertTrue(any("same-site URL or /path" in reason for reason in reasons))
        self.assertTrue(any("not the site host" in reason for reason in reasons))
        self.assertTrue(any("unknown or empty" in reason for reason in reasons))

    def test_empty_successful_provider_is_missing_not_zero(self):
        report = join_rows([self.article], [], [])
        entry = report["article_performance"][0]
        self.assertEqual(report["measurement_status"], "ok")
        self.assertEqual(entry["gsc"]["status"], "missing")
        self.assertIsNone(entry["gsc"]["clicks"])
        self.assertIsNone(entry["gsc"]["impressions"])
        self.assertIsNone(entry["gsc"]["ctr"])
        self.assertEqual(entry["ga4"]["status"], "missing")
        self.assertIsNone(entry["ga4"]["views"])
        self.assertIn("not zero", entry["gsc"]["note"])
        self.assertIn("not zero", entry["ga4"]["note"])

    def test_measured_zero_kept_as_zero(self):
        gsc_rows = [{"page": "/uutiset/2026/09/example/", "clicks": 0, "impressions": 0,
                     "ctr": 0.0, "position": None}]
        ga4_rows = [{"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
                     "views": 0, "active_users": 0, "sessions": 0}]
        report = join_rows([self.article], gsc_rows, ga4_rows)
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "ok")
        self.assertEqual(entry["gsc"]["clicks"], 0)
        self.assertEqual(entry["gsc"]["impressions"], 0)
        self.assertIsNone(entry["gsc"]["ctr"])
        self.assertIsNone(entry["gsc"]["position"])
        self.assertEqual(entry["gsc"]["unknown_rows"]["position"], 1)
        self.assertIn("position unknown", entry["gsc"]["note"])
        self.assertEqual(entry["ga4"]["status"], "ok")
        self.assertEqual(entry["ga4"]["views"], 0)
        self.assertEqual(entry["ga4"]["sessions"], 0)
        self.assertEqual(entry["ga4"]["active_users"], 0)
        self.assertEqual(report["measurement_status"], "ok")

    def test_zero_exposure_position_zero_treated_unknown(self):
        gsc_rows = [{"page": "/uutiset/2026/09/example/", "clicks": 0, "impressions": 0,
                     "ctr": 0.0, "position": 0}]
        report = join_rows([self.article], gsc_rows, [])
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "ok")
        self.assertIsNone(entry["gsc"]["position"])
        self.assertEqual(entry["gsc"]["unknown_rows"]["position"], 1)


class JoinRowsValidationTest(unittest.TestCase):
    """Malformed provider metrics never silently become zero."""

    def setUp(self):
        self.article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/example/", "deployed": True}
        self.page = "/uutiset/2026/09/example/"

    def _assert_error_row(self, row):
        report = join_rows([self.article], [row], [])
        self.assertEqual(report["measurement_status"], "error")
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "error")
        self.assertIsNone(entry["gsc"]["clicks"])
        self.assertIsNone(entry["gsc"]["impressions"])
        self.assertIsNone(entry["gsc"]["position"])
        self.assertIsNone(entry["gsc"]["ctr"])
        self.assertTrue(any("invalid metrics" in reason for reason in entry["gsc"]["reasons"]))
        self.assertIn("totals withheld", entry["gsc"]["note"])
        self.assertEqual(len(report["unmatched"]), 1)
        self.assertEqual(report["unmatched"][0]["status"], "error")
        self.assertIn("invalid metrics", report["unmatched"][0]["reason"])
        self.assertTrue(report["issues"])
        return report

    def test_missing_and_invalid_gsc_metrics(self):
        base = {"page": self.page, "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3.0}
        invalid_rows = []
        for field in ("clicks", "impressions", "ctr", "position"):
            row = dict(base)
            del row[field]
            invalid_rows.append(row)
        for field, value in (("clicks", -1), ("clicks", True), ("clicks", "3"), ("clicks", float("nan")),
                             ("impressions", -5), ("impressions", float("inf")), ("ctr", -0.1),
                             ("position", 0.5), ("position", 0), ("position", "3"), ("position", float("nan"))):
            row = dict(base)
            row[field] = value
            invalid_rows.append(row)
        over_clicks = dict(base, clicks=11)
        invalid_rows.append(over_clicks)
        for row in invalid_rows:
            self._assert_error_row(row)

    def test_missing_and_invalid_ga4_metrics(self):
        base = {"landing_page": self.page, "hostname": "uutistenlukija.fi",
                "views": 5, "active_users": 2, "sessions": 3}
        invalid_rows = []
        for field in ("views", "active_users", "sessions"):
            row = dict(base)
            del row[field]
            invalid_rows.append(row)
        for field, value in (("views", -1), ("views", True), ("views", "5"), ("views", float("inf")),
                             ("active_users", -2), ("active_users", float("nan")), ("sessions", None)):
            row = dict(base)
            row[field] = value
            invalid_rows.append(row)
        for row in invalid_rows:
            report = join_rows([self.article], [], [row])
            self.assertEqual(report["measurement_status"], "error")
            entry = report["article_performance"][0]
            self.assertEqual(entry["ga4"]["status"], "error")
            self.assertIsNone(entry["ga4"]["views"])
            self.assertIsNone(entry["ga4"]["sessions"])
            self.assertIsNone(entry["ga4"]["active_users"])
            self.assertTrue(report["issues"])

    def test_non_object_rows_rejected_not_zero(self):
        report = join_rows([self.article], ["not-a-row"], [None])
        self.assertEqual(report["measurement_status"], "error")
        self.assertEqual(report["providers"]["gsc"]["rows"], 1)
        self.assertEqual(report["providers"]["ga4"]["rows"], 1)
        self.assertEqual([row["status"] for row in report["unmatched"]], ["error", "error"])

    def test_huge_numbers_yield_controlled_error_not_crash(self):
        huge = 10 ** 400
        gsc_rows = [
            {"page": self.page, "clicks": huge, "impressions": huge, "ctr": 0.1, "position": 3.0},
            {"page": "/uutiset/2026/09/other/", "clicks": 1, "impressions": 10,
             "ctr": 0.1, "position": huge},
        ]
        report = join_rows([self.article], gsc_rows, [])
        self.assertEqual(report["measurement_status"], "error")
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "error")
        self.assertIsNone(entry["gsc"]["clicks"])
        self.assertTrue(all(row["status"] == "error" for row in report["unmatched"]))
        self.assertTrue(any("finite" in issue for issue in report["issues"]))
        ga4_report = join_rows([self.article], [], [{
            "landing_page": self.page, "hostname": "uutistenlukija.fi",
            "views": huge, "active_users": 1, "sessions": 1,
        }])
        self.assertEqual(ga4_report["measurement_status"], "error")
        self.assertIsNone(ga4_report["article_performance"][0]["ga4"]["views"])

    def test_invalid_metrics_not_counted_in_cohort_totals(self):
        rows = [
            {"page": self.page, "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 2.0},
            {"page": "/uutiset/2026/09/broken/", "clicks": -5, "impressions": 50, "ctr": 0.1, "position": 2.0},
        ]
        report = join_rows([self.article], rows, [])
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["rows"], 2)
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["clicks"], 5)
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["impressions"], 50)
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["unknown_rows"]["clicks"], 1)
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["error_rows"], 1)

    def test_foreign_gsc_metrics_are_preserved_or_unknown(self):
        valid = {"page": "https://foreign.invalid/uutiset/a/", "clicks": 2,
                 "impressions": 10, "ctr": 0.2, "position": 4.0}
        report = join_rows([self.article], [valid], [])
        excluded = report["cohorts"]["gsc"]["excluded"]
        self.assertEqual(report["measurement_status"], "ok")
        self.assertEqual(excluded["clicks"], 2)
        self.assertEqual(excluded["impressions"], 10)
        self.assertEqual(excluded["position"], 4)
        self.assertEqual(excluded["measured_rows"], 1)
        self.assertEqual(report["article_performance"][0]["gsc"]["status"], "missing")

        invalid = dict(valid, clicks=-1)
        report = join_rows([self.article], [invalid], [])
        excluded = report["cohorts"]["gsc"]["excluded"]
        self.assertEqual(report["measurement_status"], "error")
        self.assertIsNone(excluded["clicks"])
        self.assertIsNone(excluded["impressions"])
        self.assertEqual(excluded["measured_rows"], 0)
        self.assertEqual(excluded["error_rows"], 1)
        self.assertEqual(excluded["unknown_rows"]["clicks"], 1)
        self.assertEqual(report["unmatched"][0]["status"], "error")

    def test_provider_status_error_and_missing_stay_unknown(self):
        rows = [{"page": self.page, "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 2.0}]
        error = join_rows([self.article], rows, [], gsc_status="error")
        self.assertEqual(error["measurement_status"], "error")
        entry = error["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "error")
        self.assertIsNone(entry["gsc"]["clicks"])
        self.assertIn("metrics unknown, not zero", entry["gsc"]["note"])
        missing = join_rows([self.article], rows, [], ga4_status="missing")
        self.assertEqual(missing["measurement_status"], "incomplete")
        self.assertEqual(missing["article_performance"][0]["ga4"]["status"], "missing")
        self.assertIsNone(missing["article_performance"][0]["ga4"]["views"])
        with self.assertRaises(ValueError):
            join_rows([self.article], rows, [], gsc_status="partial")
        with self.assertRaises(ValueError):
            join_rows([self.article], rows, [], truncated="yes")

    def test_none_provider_rows_are_missing_not_empty_success(self):
        report = join_rows([self.article], None, None)
        self.assertEqual(report["measurement_status"], "incomplete")
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "missing")
        self.assertEqual(entry["ga4"]["status"], "missing")
        self.assertIn("provider data is None", report["issues"][0])
        empty = join_rows([self.article], [], [])
        self.assertEqual(empty["measurement_status"], "ok")


class JoinRowsDuplicatesTest(unittest.TestCase):
    """Exact duplicates collapse; conflicting duplicates make the report incomplete."""

    def setUp(self):
        self.article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/example/", "deployed": True}

    def test_exact_duplicate_rows_counted_once(self):
        row = {"page": "/uutiset/2026/09/example/", "clicks": 3, "impressions": 30,
               "ctr": 0.1, "position": 4.0}
        ga4_row = {"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
                   "views": 7, "active_users": 6, "sessions": 5}
        report = join_rows([self.article], [row, dict(row)], [ga4_row, dict(ga4_row)])
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["clicks"], 3)
        self.assertEqual(entry["gsc"]["impressions"], 30)
        self.assertEqual(entry["ga4"]["views"], 7)
        self.assertEqual(entry["ga4"]["active_users"], 6)
        self.assertEqual(report["providers"]["gsc"]["exact_duplicate_rows"], 1)
        self.assertEqual(report["providers"]["ga4"]["exact_duplicate_rows"], 1)
        self.assertEqual(report["measurement_status"], "ok")

    def test_conflicting_duplicate_rows_make_report_incomplete(self):
        first = {"page": "/uutiset/2026/09/example/", "clicks": 3, "impressions": 30,
                 "ctr": 0.1, "position": 4.0}
        second = {"page": "/uutiset/2026/09/example/", "clicks": 9, "impressions": 90,
                  "ctr": 0.1, "position": 4.0}
        report = join_rows([self.article], [first, second], [])
        self.assertEqual(report["measurement_status"], "incomplete")
        entry = report["article_performance"][0]
        self.assertEqual(entry["gsc"]["status"], "missing")  # contradictory rows are not counted
        self.assertEqual(report["providers"]["gsc"]["conflicting_duplicate_rows"], 2)
        self.assertEqual(report["providers"]["gsc"]["unmatched_rows"], 2)
        self.assertTrue(all(row["status"] == "error" for row in report["unmatched"]))
        self.assertTrue(any("conflicting duplicate" in issue for issue in report["issues"]))
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["rows"], 2)
        self.assertIsNone(report["cohorts"]["gsc"]["reboot"]["clicks"])
        self.assertEqual(report["cohorts"]["gsc"]["reboot"]["error_rows"], 2)

    def test_conflicting_duplicate_ga4_identity(self):
        first = {"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
                 "views": 7, "active_users": 6, "sessions": 5}
        second = {"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
                  "views": 70, "active_users": 6, "sessions": 5}
        report = join_rows([self.article], [], [first, second])
        self.assertEqual(report["measurement_status"], "incomplete")
        self.assertEqual(report["article_performance"][0]["ga4"]["status"], "missing")
        self.assertEqual(report["providers"]["ga4"]["conflicting_duplicate_rows"], 2)
        self.assertIsNone(report["article_performance"][0]["ga4"]["views"])

    def test_distinct_query_variant_rows_are_not_duplicates(self):
        rows = [
            {"page": "/uutiset/2026/09/example/", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 2.0},
            {"page": "/uutiset/2026/09/example/?page=2", "clicks": 1, "impressions": 10,
             "ctr": 0.1, "position": 4.0},
        ]
        report = join_rows([self.article], rows, [])
        self.assertEqual(report["measurement_status"], "ok")
        self.assertEqual(report["providers"]["gsc"]["exact_duplicate_rows"], 0)
        self.assertEqual(report["providers"]["gsc"]["conflicting_duplicate_rows"], 0)
        self.assertEqual(report["article_performance"][0]["gsc"]["impressions"], 20)


class JoinRowsTruncationTest(unittest.TestCase):
    def test_truncated_report_forbids_certainty(self):
        article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/example/", "deployed": True}
        row = {"page": "/uutiset/2026/09/example/", "clicks": 3, "impressions": 30,
               "ctr": 0.1, "position": 4.0}
        ga4_row = {"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
                    "views": 3, "active_users": 2, "sessions": 1}
        report = join_rows([article], [row], [ga4_row], truncated=True)
        self.assertEqual(report["measurement_status"], "incomplete")
        self.assertIs(report["truncated"], True)
        self.assertIn("truncation_note", report)
        self.assertIn("cannot support certainty", report["truncation_note"])
        self.assertIs(report["providers"]["gsc"]["incomplete"], True)
        self.assertIs(report["providers"]["ga4"]["incomplete"], True)
        # Measured rows are still reported, but the report itself refuses certainty.
        self.assertEqual(report["article_performance"][0]["gsc"]["clicks"], 3)

    def test_untruncated_default_present(self):
        article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/example/", "deployed": True}
        report = join_rows([article], [], [])
        self.assertIs(report["truncated"], False)
        self.assertNotIn("truncation_note", report)


class JoinRowsCohortTest(unittest.TestCase):
    def test_gsc_cohorts_and_no_prefix_attribution(self):
        gsc_rows = [
            {"page": "https://uutistenlukija.fi/", "clicks": 1, "impressions": 5, "ctr": 0.2, "position": 1.0},
            {"page": "/uutiset/2026/09/a/", "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 3.0},
            {"page": "/sivu/2/", "clicks": 0, "impressions": 2, "ctr": 0.0, "position": 6.0},
            {"page": "/posts/2026-01-01-old/", "clicks": 4, "impressions": 40, "ctr": 0.1, "position": 9.0},
            {"page": "/uutisetfake/2026/09/a/", "clicks": 3, "impressions": 30, "ctr": 0.1, "position": 7.0},
            {"page": "/uutiset", "clicks": 1, "impressions": 1, "ctr": 1.0, "position": 2.0},
            {"page": "https://example.com/uutiset/2026/09/a/", "clicks": 5, "impressions": 50,
             "ctr": 0.1, "position": 2.0},
        ]
        article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/a/", "deployed": True}
        report = join_rows([article], gsc_rows, [])
        cohorts = report["cohorts"]["gsc"]
        self.assertEqual(cohorts["reboot"]["rows"], 3)
        self.assertEqual(cohorts["reboot"]["clicks"], 3)
        self.assertEqual(cohorts["reboot"]["impressions"], 27)
        self.assertEqual(cohorts["legacy"]["rows"], 3)  # /posts, /uutisetfake, bare /uutiset
        self.assertEqual(cohorts["legacy"]["clicks"], 8)
        self.assertEqual(cohorts["legacy"]["impressions"], 71)
        self.assertEqual(cohorts["excluded"]["rows"], 1)
        self.assertIn("not deployed articles", cohorts["reboot"]["note"])
        # The /uutisetfake and /uutiset rows never leak into the article.
        self.assertEqual(report["article_performance"][0]["gsc"]["clicks"], 2)
        self.assertEqual(report["providers"]["gsc"]["attributed_rows"], 1)
        self.assertEqual(report["providers"]["gsc"]["unmatched_rows"], 6)

    def test_ga4_cohorts_unknown_hostname_unattributed_not_trusted(self):
        ga4_rows = [
            {"landing_page": "/", "hostname": "uutistenlukija.fi", "views": 3, "active_users": 2, "sessions": 2},
            {"landing_page": "/uutiset/2026/09/a/", "hostname": "uutistenlukija.fi",
             "views": 4, "active_users": 3, "sessions": 3},
            {"landing_page": "/posts/2026-01-01-old/", "hostname": "uutistenlukija.fi",
             "views": 5, "active_users": 4, "sessions": 4},
            {"landing_page": "", "hostname": "uutistenlukija.fi", "views": 1, "active_users": 1, "sessions": 1},
            {"landing_page": "(not set)", "hostname": "(not set)", "views": 1, "active_users": 1, "sessions": 1},
            {"landing_page": "(not set)", "hostname": "uutistenlukija.fi", "views": 1, "active_users": 1, "sessions": 1},
            {"landing_page": "/", "hostname": None, "views": 1, "active_users": 1, "sessions": 1},
        ]
        article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/a/", "deployed": True}
        report = join_rows([article], [], ga4_rows)
        cohorts = report["cohorts"]["ga4"]
        self.assertEqual(cohorts["reboot"]["rows"], 2)
        self.assertEqual(cohorts["reboot"]["views"], 7)
        self.assertEqual(cohorts["legacy"]["rows"], 1)
        self.assertEqual(cohorts["unattributed"]["rows"], 2)  # known host + empty/(not set) landing
        self.assertEqual(cohorts["excluded"]["rows"], 2)      # unknown host and explicit None hostname
        self.assertIn("never summed", cohorts["reboot"]["note"])
        self.assertIsNone(cohorts["reboot"]["active_users"])
        self.assertEqual(report["measurement_status"], "ok")
        self.assertEqual(report["article_performance"][0]["ga4"]["views"], 4)

    def test_cohort_unknown_counts_and_additive_totals(self):
        gsc_rows = [
            {"page": "/uutiset/2026/09/a/", "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 4.0},
            {"page": "/uutiset/2026/09/b/", "clicks": 0, "impressions": 0, "ctr": 0.0, "position": None},
        ]
        report = join_rows([], gsc_rows, [])
        reboot = report["cohorts"]["gsc"]["reboot"]
        self.assertEqual(reboot["rows"], 2)
        self.assertEqual(reboot["clicks"], 2)
        self.assertEqual(reboot["impressions"], 20)
        self.assertEqual(reboot["position"], 4)
        self.assertEqual(reboot["unknown_rows"]["position"], 1)
        self.assertEqual(report["providers"]["gsc"]["unmatched_rows"], 2)


class JoinRowsReportContractTest(unittest.TestCase):
    def test_report_is_json_serializable(self):
        import json
        article = {
            "id": "a1",
            "canonical_url": SITE + "/uutiset/2026/09/example/",
            "deployed": True,
            "aliases": ["/uutiset/2026/09/old/"],
            "metadata": {"description": True, "og": None, "jsonld": False},
        }
        report = join_rows(
            [article],
            [{"page": "/uutiset/2026/09/old/", "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 3.5}],
            [{"landing_page": "/uutiset/2026/09/example/", "hostname": "uutistenlukija.fi",
              "views": 4, "active_users": 3, "sessions": 2}],
        )
        encoded = json.dumps(report)
        self.assertEqual(json.loads(encoded)["measurement_status"], "ok")
        self.assertEqual(
            sorted(report),
            ["article_performance", "cohorts", "coverage", "issues", "limitations", "measurement_status",
             "providers", "truncated", "unmatched"],
        )
        self.assertEqual(
            sorted(report["article_performance"][0]),
            ["aliases", "canonical_url", "deployed", "ga4", "gsc", "id", "metadata"],
        )
        self.assertTrue(any("GSC clicks are not GA4 views" in item for item in report["limitations"]))
        self.assertTrue(any("not additive" in item for item in report["limitations"]))
        self.assertTrue(any("privacy-suppressed" in item for item in report["limitations"]))
        self.assertTrue(any("windows are supplied by the adapter" in item for item in report["limitations"]))

    def test_unmatched_rows_preserved_for_every_provider_row(self):
        article = {"id": "a1", "canonical_url": SITE + "/uutiset/2026/09/example/", "deployed": True}
        gsc_rows = [
            {"page": "/posts/old/", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3.0},
            {"page": "/uutiset/2026/09/example/", "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 3.0},
        ]
        ga4_rows = [
            {"landing_page": "/posts/old/", "hostname": "uutistenlukija.fi",
             "views": 1, "active_users": 1, "sessions": 1},
        ]
        report = join_rows([article], gsc_rows, ga4_rows)
        self.assertEqual(len(report["unmatched"]), 2)
        by_provider = {row["provider"]: row for row in report["unmatched"]}
        self.assertEqual(by_provider["gsc"]["cohort"], "legacy")
        self.assertEqual(by_provider["gsc"]["normalized_path"], "/posts/old/")
        self.assertEqual(by_provider["ga4"]["cohort"], "legacy")
        self.assertIs(by_provider["gsc"]["raw"], gsc_rows[0])
        self.assertEqual(report["measurement_status"], "ok")
        self.assertEqual(report["providers"]["gsc"]["attributed_rows"], 1)


class CollectorTest(unittest.TestCase):
    def _make_db(self, root, identifier="a1", title="Test article", run_id=7):
        draft = {"title": title, "summary": "A summary"}
        db = sqlite3.connect(Path(root) / "jobs.sqlite")
        db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, draft TEXT, created_at TEXT)")
        db.execute("CREATE TABLE publications (job_id TEXT PRIMARY KEY, run_id INTEGER, status TEXT)")
        db.execute("INSERT INTO jobs VALUES (?, ?, ?)", (identifier, json.dumps(draft), "2026-09-22T00:00:00+00:00"))
        db.execute("INSERT INTO publications VALUES (?, ?, 'deployed')", (identifier, run_id))
        db.commit()
        db.close()
        return draft

    def _provider_requests(self, now):
        return {
            "ga4": {"dateRanges": [{"startDate": "2026-08-22", "endDate": "2026-09-20"}]},
            "gsc": {"startDate": "2026-08-20", "endDate": "2026-09-18", "dataState": "final"},
        }

    def test_collect_readonly_catalog_and_provider_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = self._make_db(root)
            path = "/" + article_path({"id": "a1", "draft": draft})
            url = SITE + path
            sitemap = f"<urlset><url><loc>{url}</loc></url></urlset>".encode()
            html = (
                f'<html><head><link rel="canonical" href="{url}">'
                '<meta name="description" content="summary">'
                '<meta property="og:title" content="title">'
                '<script type="application/ld+json">{}</script></head></html>'
            ).encode()

            def public(url_value, timeout):
                return sitemap if url_value.endswith("/sitemap.xml") else html

            def query(url_value, payload, token):
                if "analyticsdata" in url_value:
                    return {
                        "dimensionHeaders": [{"name": "landingPagePlusQueryString"}, {"name": "hostName"}],
                        "metricHeaders": [{"name": "screenPageViews"}, {"name": "activeUsers"}, {"name": "sessions"}],
                        "metadata": {"timeZone": "Europe/Helsinki"},
                        "rows": [{"dimensionValues": [{"value": path}, {"value": "uutistenlukija.fi"}],
                                  "metricValues": [{"value": "4"}, {"value": "3"}, {"value": "2"}]}],
                        "rowCount": 1,
                    }
                return {"rows": [{"keys": [url], "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 4}],
                        "rowCount": 1}

            with patch.object(measurement, "_public_bytes", side_effect=public), \
                 patch.object(measurement, "requests_for", side_effect=self._provider_requests), \
                 patch.object(measurement, "service_account_access_token", return_value=("secret-token", None, None)) as auth, \
                 patch.object(measurement, "query", side_effect=query) as queried:
                report = collect(root, now=datetime(2026, 9, 23, tzinfo=timezone.utc), timeout=2)

            self.assertEqual(report["measurement_status"], "ok")
            self.assertEqual(report["catalog"]["included"], 1)
            self.assertEqual(report["article_performance"][0]["canonical_url"], url)
            self.assertEqual(report["article_performance"][0]["metadata"],
                             {"description": True, "og": True, "jsonld": True})
            self.assertEqual(report["article_performance"][0]["gsc"]["clicks"], 2)
            self.assertEqual(report["article_performance"][0]["ga4"]["views"], 4)
            self.assertEqual(report["windows"]["gsc"]["dimensions"], ["page"])
            self.assertEqual(report["windows"]["gsc"]["rowLimit"], 5000)
            self.assertEqual(report["windows"]["gsc"]["time_zone"], "America/Los_Angeles")
            self.assertEqual(report["windows"]["ga4"]["limit"], 5000)
            self.assertEqual(report["windows"]["ga4"]["offset"], 0)
            self.assertEqual(report["windows"]["ga4"]["time_zone"], "Europe/Helsinki")
            self.assertTrue(all(call.args[0][0] in (measurement.GA4_SCOPE, measurement.GSC_SCOPE)
                                for call in auth.call_args_list))
            self.assertEqual(len(queried.call_args_list), 2)
            self.assertEqual(report["provider_fetch"]["gsc"]["data_scope"], "page_rows")
            self.assertEqual(report["provider_fetch"]["ga4"]["data_scope"], "landing_page_rows")
            json.dumps(report, allow_nan=False)

    def test_provider_cap_and_schema_failure_are_abstention_ready(self):
        gsc_payload = {
            "rows": [{"keys": [f"/posts/{index}/"], "clicks": 1, "impressions": 1,
                      "ctr": 1.0, "position": 1.0} for index in range(5000)],
            "rowCount": 5000,
        }
        adapted, truncated = measurement._adapt_gsc(gsc_payload)
        self.assertEqual(len(adapted), 5000)
        self.assertIs(truncated, True)
        bad_ga4 = {
            "dimensionHeaders": [{"name": "landingPagePlusQueryString"}, {"name": "hostName"}],
            "metricHeaders": [{"name": "screenPageViews"}, {"name": "activeUsers"}, {"name": "sessions"}],
            "metadata": {"timeZone": "UTC"}, "rows": [], "rowCount": 0,
        }
        with patch.object(measurement, "service_account_access_token", return_value=("token", None, None)), \
             patch.object(measurement, "query", return_value=bad_ga4):
            rows, status, summary = measurement._fetch_provider("ga4", {}, 1)
        self.assertIsNone(rows)
        self.assertEqual(status, "error")
        self.assertEqual(summary["error"], "schema_error")
        self.assertNotIn("UTC", json.dumps(summary))

    def test_missing_db_is_readonly_and_not_silently_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "missing-state"
            with patch.object(measurement, "_provider_requests", return_value={"ga4": {}, "gsc": {}}), \
                 patch.object(measurement, "_fetch_provider", side_effect=lambda kind, payload, timeout:
                              ([], "ok", {"status": "ok", "truncated": False, "rows": 0, "cap": 5000})):
                report = collect(root, now=datetime(2026, 9, 23, tzinfo=timezone.utc))
            self.assertFalse(root.exists())
            self.assertEqual(report["measurement_status"], "incomplete")
            self.assertEqual(report["catalog"]["status"], "incomplete")
            self.assertEqual(report["article_performance"], [])

    def test_current_live_proof_allows_explicit_historical_alias_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = self._make_db(root)
            current_path = "/" + article_path({"id": "a1", "draft": draft})
            current_url = SITE + current_path
            old_url = SITE + "/uutiset/old-hash/"
            evidence_dir = root / "deployments" / "7"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "live-readback.json").write_text(json.dumps({
                "job_id": "a1", "canonical_article": old_url, "live_html_sha256": "a" * 64,
            }))
            html = f'<link rel="canonical" href="{current_url}">'.encode()
            with patch.object(measurement, "_public_bytes", side_effect=lambda url_value, timeout:
                              f"<urlset><url><loc>{current_url}</loc></url></urlset>".encode()
                              if url_value.endswith("/sitemap.xml") else html):
                catalog = measurement._catalog(root, 1)
            self.assertEqual(catalog["status"], "ok")
            self.assertEqual(catalog["articles"][0]["aliases"], ["/uutiset/old-hash/"])
            self.assertEqual(catalog["evidence"]["readback_canonical_not_in_current_sitemap"], 1)

    def test_live_canonical_rejects_ambiguous_markup(self):
        url = SITE + "/uutiset/a/"
        fixtures = {
            "duplicatehref": (
                f'<link rel="canonical" href="https://foreign.invalid/" href="{url}">'
            ),
            "duplicaterel": f'<link rel="alternate" rel="canonical" href="{url}">',
            "ambiguous secondcanonical": (
                f'<link rel="canonical" href="{url}">'
                f'<link rel="canonical" href="{url}">'
            ),
        }
        for label, html in fixtures.items():
            with self.subTest(label=label), patch.object(measurement, "_public_bytes",
                                                         return_value=html.encode()):
                with self.assertRaises(measurement._LiveEvidenceError):
                    measurement._verify_live_article(url, "/uutiset/a/", 1)

    def test_cli_emits_stdout_json_without_output_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            fixture = {"measurement_status": "incomplete", "truncated": False}
            with patch.object(measurement, "collect", return_value=fixture), redirect_stdout(output):
                self.assertEqual(measurement._main(["--state-dir", temporary]), 0)
            self.assertEqual(json.loads(output.getvalue()), fixture)
            self.assertEqual(list(Path(temporary).iterdir()), [])


class DocstringContractTest(unittest.TestCase):
    """The merged review fix: bare /uutiset and /sivu are legacy, not reboot."""

    def test_bare_prefixes_are_legacy_and_slash_prefixes_reboot(self):
        for value in ("/uutiset", "/sivu", "/uutisetfake", "/sivut/"):
            self.assertEqual(classify_path(value), "legacy", value)
        for value in ("/uutiset/", "/uutiset/x/", "/sivu/2/"):
            self.assertEqual(classify_path(value), "reboot", value)
        self.assertIn("bare prefixes", __import__("news_mvp.measurement", fromlist=["x"]).__doc__)


if __name__ == "__main__":
    unittest.main()
