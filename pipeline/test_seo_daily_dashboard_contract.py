#!/usr/bin/env python3
"""Pure contract tests. All rows are SYNTHETIC TEST-ONLY, never analytics evidence.

Run directly with python3 -I -B. Install an audit deny policy BEFORE reading or
executing source declarations. Never import the reporter/provider bootstrap.
Only unchanged AST function declarations are compiled; requests are test doubles.
"""
import ast
import datetime
import os
from pathlib import Path
import sys
import sysconfig
import unittest

SOURCE = Path(__file__).with_name("seo_daily_dashboard.py").resolve()
STDLIB = Path(sysconfig.get_path("stdlib")).resolve()
DENIED = []


def audit(event, args):
    forbidden = event.startswith(("socket.", "subprocess.", "ctypes.")) or event in {
        "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec",
        "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.link", "os.symlink",
        "os.chmod", "os.chown", "os.truncate", "os.listdir", "os.scandir",
    }
    if event == "open":
        path, mode, flags = args
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if isinstance(path, (str, bytes, os.PathLike)):
            p = Path(os.fsdecode(path)).resolve()
            stdlib = p.is_relative_to(STDLIB) and "site-packages" not in p.parts and p.suffix in {".py", ".pyc"}
            forbidden = bool(writing) or not (p == SOURCE or p == Path(__file__).resolve() or stdlib)
        else:
            forbidden = True
    if forbidden:
        DENIED.append(event)
        raise PermissionError("isolated SEO contract test denied: " + event)


sys.addaudithook(audit)
TREE = ast.parse(SOURCE.read_text(), filename=str(SOURCE))
NAMES = {"summarize_sc_data", "fetch_sc_data", "format_report"}
DECLARATIONS: list[ast.stmt] = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in NAMES]
NS = {"datetime": datetime.datetime, "timezone": datetime.timezone, "timedelta": datetime.timedelta}
exec(compile(ast.Module(body=DECLARATIONS, type_ignores=[]), str(SOURCE), "exec"), NS)


def row(i=0, ctr=0.0061, impressions=10000):
    return {"keys": [f"synthetic-test-only-{i}"], "clicks": round(ctr * impressions),
            "impressions": impressions, "ctr": ctr, "position": 4.0}


class SEOContractTest(unittest.TestCase):
    def sample(self, queries=None, pages=None, candidates=None):
        return NS["summarize_sc_data"](
            {"rows": queries if queries is not None else [row()]},
            {"rows": pages if pages is not None else [row()]},
            {"rows": candidates if candidates is not None else [row()]},
            "2026-01-01", "2026-01-08")

    def report(self, sc):
        return NS["format_report"]({"has_data": False}, sc, "TEST-ONLY")

    def test_explicit_units_and_compatibility(self):
        sc = self.sample()
        self.assertEqual(sc["units"]["ctr"], "fraction")
        self.assertEqual(sc["units"]["ctr_fraction"], "fraction")
        self.assertEqual(sc["top_queries"][0]["ctr_fraction"], 0.0061)
        self.assertEqual(sc["deprecated_aliases"]["total_clicks"], "selected_query_clicks")
        self.assertEqual(sc["total_clicks"], sc["selected_query_clicks"])
        self.assertEqual(sc["total_impressions"], sc["selected_query_impressions"])
        self.assertIsNone(sc["property_totals"])

    def test_selected_sums_cover_twenty_not_displayed_ten(self):
        sc = self.sample(queries=[row(i) for i in range(20)])
        self.assertEqual(sc["selected_query_clicks"], 1220)
        self.assertEqual(len(sc["top_queries"]), 10)
        meta = sc["samples"]["queries"]
        self.assertEqual((meta["requested_limit"], meta["returned_rows"], meta["stored_rows"]), (20, 20, 10))
        self.assertTrue(meta["row_limit_reached"])
        self.assertFalse(sc["completeness"]["complete"])
        self.assertIn("ei koko sivuston", self.report(sc))

    def test_short_empty_and_unavailable_never_claim_complete(self):
        for response, status in [({"rows": []}, "rows_present"), ({}, "empty_or_unavailable")]:
            sc = NS["summarize_sc_data"](response, response, response, "a", "b")
            self.assertFalse(sc["completeness"]["complete"])
            self.assertEqual(sc["samples"]["queries"]["response_status"], status)
            self.assertIsNone(sc["completeness"]["provider_omissions"])
            self.assertIn("kattavuus", self.report(sc))
        self.assertFalse(self.sample()["completeness"]["complete"])

    def test_fraction_percent_conversion_once(self):
        for fraction, rendered in [(0.0061, "0.6% CTR"), (0.0014, "0.1% CTR"), (0.61, "61.0% CTR")]:
            sc = self.sample(queries=[row(ctr=fraction)], candidates=[row(ctr=fraction)])
            text = self.report(sc)
            self.assertIn(rendered, text)
            self.assertEqual(sc["top_queries"][0]["ctr_fraction"], fraction)

    def test_low_ctr_threshold_and_candidate_metadata(self):
        rows = [row(1, 0.019, 200), row(2, 0.02, 300), row(3, 0.001, 199)]
        sc = self.sample(candidates=rows)
        self.assertEqual(len(sc["low_ctr_pages"]), 1)
        self.assertEqual(sc["samples"]["low_ctr_candidates"]["returned_rows"], 3)
        self.assertEqual(sc["samples"]["low_ctr_candidates"]["stored_rows"], 1)
        self.assertIn("otos", self.report(sc))

    def test_input_rows_are_not_mutated(self):
        r = row()
        self.sample(queries=[r], pages=[r], candidates=[r])
        self.assertNotIn("ctr_fraction", r)

    def test_missing_ctr_is_unavailable_not_zero(self):
        r = row()
        del r["ctr"]
        sc = self.sample(queries=[r], candidates=[r])
        self.assertIsNone(sc["top_queries"][0]["ctr_fraction"])
        self.assertEqual(sc["low_ctr_pages"], [])
        self.assertIn("ei saatavilla CTR", self.report(sc))

    def test_candidate_cap_stored_and_formatted_subsets(self):
        sc = self.sample(candidates=[row(i) for i in range(50)])
        meta = sc["samples"]["low_ctr_candidates"]
        self.assertEqual((meta["returned_rows"], meta["stored_rows"]), (50, 5))
        self.assertTrue(meta["row_limit_reached"])
        self.assertEqual(self.report(sc).count("korjaa otsikko/kuvaus"), 3)

    def test_state_alias_is_explicit_without_running_main(self):
        main = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        state = next(n.value for n in ast.walk(main) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "state" for t in n.targets))
        assert isinstance(state, ast.Dict)
        fields = {k.value: v for k, v in zip(state.keys, state.values) if isinstance(k, ast.Constant)}
        self.assertEqual(ast.dump(fields["sc_clicks"]), ast.dump(fields["sc_selected_query_clicks"]))
        self.assertEqual(ast.literal_eval(fields["sc_clicks_scope"]), "selected_query_sample_not_property_total")
        self.assertEqual(ast.literal_eval(fields["deprecated_aliases"]), {"sc_clicks": "sc_selected_query_clicks"})

    def test_exact_existing_request_policy_only_test_double(self):
        requests = []
        def synthetic_request(token, payload):
            self.assertEqual(token, "SYNTHETIC-TEST-ONLY")
            requests.append(payload)
            return {"rows": [row()]}
        NS["sc_request"] = synthetic_request
        sc = NS["fetch_sc_data"]("SYNTHETIC-TEST-ONLY")
        self.assertEqual(len(requests), 3)
        self.assertEqual([p["rowLimit"] for p in requests], [20, 10, 50])
        self.assertEqual([p["dimensions"] for p in requests], [["query"], ["page"], ["page"]])
        self.assertTrue(all(set(p) == {"startDate", "endDate", "dimensions", "rowLimit", "orderBy"} for p in requests))
        self.assertEqual([p["orderBy"][0]["fieldName"] for p in requests], ["clicks", "clicks", "impressions"])
        self.assertEqual(sc["schema_version"], 2)

    def test_legacy_formatter_is_truthfully_labeled(self):
        sc = {"has_data": True, "period": "TEST", "total_clicks": 4,
              "total_impressions": 100, "top_queries": [row()], "low_ctr_pages": []}
        self.assertIn("ei koko sivuston", self.report(sc))
        self.assertIn("0.6% CTR", self.report(sc))

    def test_audit_denies_before_io(self):
        before = len(DENIED)
        for event, args in [("open", ("/test-only/.env", "r", 0)),
                            ("open", ("/test-only/state.json", "r", 0)),
                            ("open", (str(SOURCE), "w", os.O_WRONLY)),
                            ("socket.connect", (None, None)),
                            ("subprocess.Popen", ("test-only", [], None, None))]:
            with self.assertRaises(PermissionError):
                sys.audit(event, *args)
        self.assertEqual(len(DENIED) - before, 5)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SEOContractTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"AUDIT denied_events={len(DENIED)} (5 expected self-checks); source_declarations={len(DECLARATIONS)}")
    sys.exit(not result.wasSuccessful() or len(DENIED) != 5)
