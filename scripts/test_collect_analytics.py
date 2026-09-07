"""Offline collector regression tests; all writes restricted to caller scratch dir."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_analytics as c

NOW = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
SCRATCH = Path(os.environ.get("COLLECTOR_TEST_SCRATCH", "/home/pertt/outputs/news-rebuild-20260907/scratch/collector"))


def response(request):
    dims = [d["name"] for d in request.get("dimensions", [])]
    values = {"screenPageViews": 108, "activeUsers": 54, "sessions": 67,
              "engagementRate": .75, "bounceRate": .25, "totalUsers": 54}
    dim_rows = {(): [[]], ("newVsReturning",): [["new"], ["returning"]],
                ("date",): [["20260906"], ["20260905"]],
                ("pagePath", "pageTitle"): [["/news/", "Uutinen"]],
                ("sessionSource", "sessionMedium"): [["google", "organic"]]}
    rows = []
    for ds in dim_rows[tuple(dims)]:
        metrics = dict(values)
        if ds == ["new"]:
            metrics["activeUsers"] = 52
        if ds == ["returning"]:
            metrics["activeUsers"] = 6
        rows.append({"dimensionValues": [{"value": d} for d in ds],
                     "metricValues": [{"value": str(metrics[m["name"]])} for m in request["metrics"]]})
    return {"dimensionHeaders": request.get("dimensions", []),
            "metricHeaders": [dict(m, type="TYPE_INTEGER" if "Rate" not in m["name"] else "TYPE_FLOAT") for m in request["metrics"]],
            "rows": rows, "rowCount": len(rows), "metadata": {"timeZone": "Europe/Helsinki"}}


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.auth = []

    def token(self, service):
        self.auth.append(service)
        return "fixture-only-not-a-token"

    def post(self, endpoint, request, token):
        self.calls.append((endpoint, copy.deepcopy(request)))
        if endpoint == c.GSC_ENDPOINT:
            if request.get("aggregationType") == "byProperty":
                return 200, {"responseAggregationType": "byProperty", "rows": [
                    {"clicks": 6, "impressions": 1000, "ctr": .006, "position": 8}]}
            return 200, {"rows": [{"keys": ["news" if request.get("dimensions") == ["query"] else "https://uutistenlukija.fi/news/"],
                                  "clicks": 3, "impressions": 900, "ctr": 3/900, "position": 9}]}
        return 200, response(request)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "absolute-output"
        self.fake = FakeProvider()

    def run_collection(self, **kw):
        return c.execute(self.out, now=NOW, token_fn=self.fake.token,
                         transport=kw.pop("transport", self.fake.post), **kw)

    def test_full_envelopes_compatibility_and_independent_denominator(self):
        code, evidence = self.run_collection()
        self.assertEqual(code, 0)
        data = json.loads((self.out / "daily-report.json").read_text())
        reader = json.loads((self.out / "reader-retention-report.json").read_text())
        self.assertEqual(reader["direct_totals"]["activeUsers"], 54)
        self.assertEqual(reader["returning_active_share"]["value"], 6/54)
        self.assertEqual(reader["goal"]["screenPageViews"]["observed"], 108)
        self.assertEqual(data["ga4_source"], json.loads((self.out / "ga4-rolling30.json").read_text()))
        self.assertEqual(data["ga4_source"]["response"], response(data["ga4_source"]["request"]))
        self.assertEqual(set(data["ga4_source"]), {"endpoint", "request", "response", "http_status", "fetched_at"})
        self.assertEqual(data["search_console"]["total_clicks"], 6)  # not page sum 3
        self.assertEqual(data["search_console"]["period"], "28d")
        self.assertEqual(data["search_console"]["top_queries"][0]["query"], "news")
        self.assertIn("top_pages_7d", data)
        self.assertEqual(len(self.fake.calls), 9)
        self.assertEqual(evidence["status"], "fresh")
        self.assertTrue(evidence["artifacts"]["daily_report"]["fresh"])
        self.assertEqual((self.out / "daily-report.json").stat().st_mode & 0o777, 0o600)
        for endpoint, request in self.fake.calls:
            if endpoint == c.GA4_ENDPOINT:
                self.assertEqual(request["dateRanges"][0]["endDate"], "2026-09-06")
                self.assertNotIn("dimensionFilter", request)
                self.assertNotIn("metricFilter", request)
        self.assertEqual(self.fake.calls[0][0], c.GA4_ENDPOINT)
        self.assertNotIn("dimensions", self.fake.calls[0][1])
        self.assertEqual(self.fake.calls[0][1]["dateRanges"], [{"startDate": "2026-08-08", "endDate": "2026-09-06"}])
        self.assertEqual(self.fake.calls[1][1]["dimensions"], [{"name": "newVsReturning"}])

    def test_daily_freshness_requires_component_envelopes_and_exact_projections(self):
        from analytics_contract import validate_daily_report
        artifacts = c.collect(NOW, self.fake.token, self.fake.post)
        original = artifacts["daily-report.json"]
        self.assertTrue(validate_daily_report(original, NOW)["fresh"])
        for component in ("daily_pageviews", "top_pages_7d", "traffic_sources_7d"):
            for mode in ("missing", "truncated", "projection", "window"):
                with self.subTest(component=component, mode=mode):
                    data = copy.deepcopy(original)
                    if mode == "missing": del data["ga4_components"][component]
                    if mode == "truncated": data["ga4_components"][component]["response"]["rows"] = []
                    if mode == "projection": data[component] = []
                    if mode == "window": data["query_windows"][component]["endDate"] = "2026-09-01"
                    self.assertFalse(validate_daily_report(data, NOW)["fresh"])

    def test_partial_http_malformed_empty_and_limited_preserve_last_good(self):
        self.run_collection()
        paths = [p for p in self.out.iterdir() if p.name not in ("collector-status.json", "post-reauth-freshness-evidence.json")]
        before = {p: p.read_bytes() for p in paths}
        for mode in ("partial", "http", "row_count", "string_count", "empty", "threshold", "timezone", "duplicate", "gsc_error"):
            with self.subTest(mode=mode):
                def bad(endpoint, request, token):
                    status, data = self.fake.post(endpoint, request, token)
                    if endpoint == c.GSC_ENDPOINT:
                        if mode == "gsc_error":
                            return 200, {"error": {"message": "DO_NOT_EXPOSE"}}
                        return status, data
                    if mode == "partial": data["error"] = {"message": "DO_NOT_EXPOSE"}
                    if mode == "http": return 403, data
                    if mode == "row_count": data["rowCount"] = 999
                    if mode == "string_count": data["rowCount"] = "1"
                    if mode == "empty": data.update(rows=[], rowCount=0)
                    if mode == "threshold": data["metadata"]["subjectToThresholding"] = True
                    if mode == "timezone": data["metadata"]["timeZone"] = "UTC"
                    if mode == "duplicate": data["rows"] *= 2; data["rowCount"] *= 2
                    return status, data
                code, evidence = self.run_collection(transport=bad)
                self.assertEqual(code, 1)
                self.assertEqual({p: p.read_bytes() for p in paths}, before)
                self.assertFalse(evidence["artifacts"]["daily_report"]["fresh"])
                self.assertNotIn("DO_NOT_EXPOSE", json.dumps(evidence))

    def test_auth_failure_no_requests_and_no_raw_error(self):
        def fail(service): raise RuntimeError("DO_NOT_EXPOSE")
        code, evidence = c.execute(self.out, now=NOW, token_fn=fail, transport=self.fake.post)
        self.assertEqual(code, 1)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse((self.out / "daily-report.json").exists())
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(evidence))

    def test_no_write_does_not_create_output(self):
        code, _ = self.run_collection(no_write=True)
        self.assertEqual(code, 0)
        self.assertFalse(self.out.exists())

    def test_window_helsinki_midnight_dst_leap_and_year(self):
        for timestamp, end in (("2026-09-06T21:01:00+00:00", "2026-09-06"),
                                ("2026-09-06T20:59:00+00:00", "2026-09-05"),
                                ("2026-01-01T00:01:00+00:00", "2025-12-31"),
                                ("2024-03-01T00:01:00+00:00", "2024-02-29"),
                                ("2026-03-29T22:01:00+00:00", "2026-03-29")):
            with self.subTest(timestamp=timestamp):
                result = c.window(datetime.fromisoformat(timestamp), 30)
                self.assertEqual(result["endDate"], end)
                self.assertEqual((datetime.fromisoformat(end) - datetime.fromisoformat(result["startDate"])).days, 29)

    def test_saved_gsc_skips_auth_and_gsc_queries(self):
        artifacts = c.collect(NOW, self.fake.token, self.fake.post)
        path = Path(self.tmp.name) / "gsc.json"
        path.write_text(json.dumps(artifacts["search-console-data.json"]))
        self.fake.calls.clear(); self.fake.auth.clear()
        self.assertEqual(self.run_collection(gsc_input=path)[0], 0)
        self.assertEqual(self.fake.auth, ["ga4"])
        self.assertEqual(len(self.fake.calls), 6)

    def test_http_error_redacted(self):
        error = HTTPError(c.GA4_ENDPOINT, 401, "DO_NOT_EXPOSE", {}, io.BytesIO(b"DO_NOT_EXPOSE"))
        with patch.object(c.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(c.CollectionError, "^http_401$"):
                c.post_json(c.GA4_ENDPOINT, {}, "fixture")

    def test_auth_helper_failure_never_reads_token_files(self):
        with patch.object(c, "service_account_access_token", side_effect=RuntimeError("DO_NOT_EXPOSE")), patch.object(Path, "read_text", side_effect=AssertionError("no credential access")):
            with self.assertRaisesRegex(c.CollectionError, "^auth_failed$"):
                c.get_token("ga4")

    def test_oauth_fallback_is_scoped_and_never_persists_access_token(self):
        from unittest.mock import MagicMock
        http = MagicMock()
        http.__enter__.return_value = http
        http.status = 200
        http.read.return_value = b'{"access_token":"fixture-refreshed"}'
        creds = {"client_id": "fixture-id", "client_secret": "fixture-secret", "refresh_token": "fixture-refresh"}
        with patch.object(c, "service_account_access_token", return_value=None) as helper, \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", return_value=json.dumps(creds)), \
             patch.object(Path, "write_text", side_effect=AssertionError("token write forbidden")), \
             patch.object(c.urllib.request, "urlopen", return_value=http):
            self.assertEqual(c.get_token("ga4"), "fixture-refreshed")
        helper.assert_called_once_with(["https://www.googleapis.com/auth/analytics.readonly"])

    def test_cli_absolute_override_and_no_write(self):
        with patch.object(c, "execute", return_value=(1, {"status": "blocked"})) as run, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(c.main(["--output-dir", str(self.out), "--no-write", "--gsc-input", "/audit/input.json"]), 1)
        self.assertEqual(run.call_args.args[0], self.out)
        self.assertTrue(run.call_args.kwargs["no_write"])
        self.assertEqual(run.call_args.kwargs["gsc_input"], Path("/audit/input.json"))

    def test_write_failure_restores_exact_last_good_bytes(self):
        self.run_collection()
        names = ["daily-report.json", "ga4-rolling30.json", "ga4-returning30.json", "reader-retention-report.json", "search-console-data.json"]
        before = {name: (self.out / name).read_bytes() for name in names}
        real_replace = os.replace
        calls = 0
        def failing_replace(source, target):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("disk failure")
            return real_replace(source, target)
        with patch.object(c.os, "replace", side_effect=failing_replace):
            code, evidence = self.run_collection()
        self.assertEqual(code, 1)
        self.assertEqual(evidence["reason"], "output_write_failed")
        self.assertEqual({name: (self.out / name).read_bytes() for name in names}, before)
        self.assertEqual(list(self.out.glob(".analytics-*")), [])

    def test_freshness_consumer_accepts_produced_daily_envelope(self):
        import analytics_freshness_evidence as freshness
        self.run_collection()
        report = json.loads((self.out / "daily-report.json").read_text())
        # Consumer validates original source, never file mtime or compatibility sums.
        result = freshness.summarize_daily_report(report, None, NOW, 30)
        self.assertTrue(result["fresh"])
        self.assertEqual(result["reason"], "validated_source")

    def test_existing_shell_entrypoint_resolves_checkout_and_forwards_args(self):
        fakebin = Path(self.tmp.name) / "bin"
        fakebin.mkdir()
        executable = fakebin / "python3"
        executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        executable.chmod(0o700)
        result = subprocess.run(["bash", str(c.PROJECT_DIR / "pipeline/check-analytics.sh"), "--output-dir", str(self.out), "--dry-run"],
                  cwd=self.tmp.name, env=dict(os.environ, PATH=str(fakebin)+":"+os.environ["PATH"]), capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(c.PROJECT_DIR / "scripts/collect_analytics.py"), "--output-dir", str(self.out), "--dry-run"])


if __name__ == "__main__":
    unittest.main()
