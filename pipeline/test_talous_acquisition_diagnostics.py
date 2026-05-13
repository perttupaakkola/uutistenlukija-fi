import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "talous_acquisition_diagnostics.py"
spec = importlib.util.spec_from_file_location("talous_acquisition_diagnostics", SCRIPT)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class TalousAcquisitionDiagnosticsTests(unittest.TestCase):
    def test_parse_scan_stages_and_research_clues(self):
        fixture = Path(__file__).resolve().parent / "tests" / "fixtures" / "staged_scan_sample.log"
        runs = diag.load_scan_runs(fixture, 999999)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["stages"]["discovered"]["categories"]["Talous"], 5)
        self.assertEqual(runs[0]["stages"]["research_result"]["buckets"]["Talous"]["research_fallback"], 1)
        self.assertEqual(runs[0]["stages"]["min_source_words_pass"]["categories"], {})
        self.assertEqual(runs[0]["research_items"][0]["original"], "only 42w (too thin, discarded)")
        self.assertEqual(runs[0]["research_items"][0]["result"], "No usable sources")


    def test_report_marks_source_pass_to_queue_conversion_gap(self):
        fixture = Path(__file__).resolve().parent / "tests" / "fixtures" / "staged_scan_source_pass_gap.log"
        fixture.write_text(
            "\n".join([
                '[2099-01-01T00:00:00Z] scan-stage: discovered total=5 categories={"Talous": 3, "Kotimaa": 2}',
                '[2099-01-01T00:00:01Z] scan-stage: dedup total=5 categories={"Talous": 3, "Kotimaa": 2}',
                '[2099-01-01T00:00:02Z] scan-stage: cooldown total=5 categories={"Talous": 3, "Kotimaa": 2}',
                '[2099-01-01T00:00:03Z] scan-stage: research_candidates total=5 categories={"Talous": 3, "Kotimaa": 2}',
                '[2099-01-01T00:00:04Z] scan-stage: research_result total=5 buckets={"Talous": {"research_enriched": 3}, "Kotimaa": {"research_enriched": 2}}',
                '[2099-01-01T00:00:05Z] scan-stage: min_source_words_pass total=5 categories={"Talous": 3, "Kotimaa": 2}',
                '[2099-01-01T00:00:06Z] scan-stage: queued_candidates total=1 categories={"Talous": 1}',
            ]) + "\n",
            encoding="utf-8",
        )
        runs = diag.load_scan_runs(fixture, 999999)
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            diag.print_report(runs, 999999, fixture)

        text = out.getvalue()
        self.assertIn("source_pass_to_queue_conversion=1/3 (33.3%)", text)
        self.assertIn("conversion_gap_note=scan enqueue is capped", text)


if __name__ == "__main__":
    unittest.main()
