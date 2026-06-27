import importlib.util
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
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
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "staged_scan_source_pass_gap.log"
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
            out = StringIO()
            with redirect_stdout(out):
                diag.print_report(runs, 999999, fixture)

        text = out.getvalue()
        self.assertIn("source_pass_to_queue_conversion=1/3 (33.3%)", text)
        self.assertIn("reserve_qualified_to_queue_conversion=1/1 (100.0%)", text)
        self.assertIn("unique_dropped_talous_candidates=0", text)
        self.assertIn("conversion_gap_note=min_source_words_pass uses broad total text", text)

    def test_report_surfaces_talous_enqueue_drop_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "staged_scan_drop_details.log"
            fixture.write_text(
                "\n".join([
                    '[2099-01-01T00:00:00Z] scan-stage: discovered total=2 categories={"Talous": 1, "Kotimaa": 1}',
                    '[2099-01-01T00:00:01Z] scan-stage: min_source_words_pass total=2 categories={"Talous": 1, "Kotimaa": 1}',
                    '[2099-01-01T00:00:02Z] scan-stage: queued_candidates total=1 categories={"Kotimaa": 1}',
                    '[2099-01-01T00:00:02Z] scan-stage-drop: talous_enqueue_drop [{"candidate_id":"abc123def0","title":"Marimekon osake kiitää","source":"Arvopaperi","source_words":44,"source_blocks":1,"research_bucket":"research_enriched","reserve_pass":false,"guardrail":"not_org_source_talous","drop_reason":"source_floor_one_block_too_short"}]',
                ]) + "\n",
                encoding="utf-8",
            )
            runs = diag.load_scan_runs(fixture, 999999)
            out = StringIO()
            with redirect_stdout(out):
                diag.print_report(runs, 999999, fixture)

        text = out.getvalue()
        self.assertIn("drop_reasons={'source_floor_one_block_too_short': 1}", text)
        self.assertIn("reserve_qualified_to_queue_conversion=0/0 (0.0%)", text)
        self.assertIn("unique_dropped_talous_candidates=1", text)
        self.assertIn("candidate_id=abc123def0", text)
        self.assertIn("source_words=44", text)
        self.assertIn("source_blocks=1", text)
        self.assertIn("guardrail=not_org_source_talous", text)
        self.assertIn("reserve_pass=False", text)
        self.assertIn("drop_reason=source_floor_one_block_too_short", text)

    def test_report_infers_legacy_talous_enqueue_drop_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "staged_scan_legacy_drop_details.log"
            fixture.write_text(
                "\n".join([
                    '[2099-01-01T00:00:00Z] scan-stage: min_source_words_pass total=2 categories={"Talous": 1, "Kotimaa": 1}',
                    '[2099-01-01T00:00:01Z] scan-stage: queued_candidates total=1 categories={"Kotimaa": 1}',
                    '[2099-01-01T00:00:01Z] scan-stage-drop: talous_enqueue_drop [{"title":"Järjestö mainostaa jäsenkampanjaa","source":"Suomen Yrittäjät","source_words":146,"source_blocks":1,"research_bucket":"research_enriched","reserve_pass":false,"guardrail":"down_rank_promotional_org_source"}]',
                ]) + "\n",
                encoding="utf-8",
            )
            runs = diag.load_scan_runs(fixture, 999999)
            out = StringIO()
            with redirect_stdout(out):
                diag.print_report(runs, 999999, fixture)

        text = out.getvalue()
        self.assertIn("drop_reasons={'org_source_guardrail_penalty': 1}", text)
        self.assertIn("unique_dropped_talous_candidates=1", text)
        self.assertIn("candidate_id=", text)
        self.assertIn("drop_reason=org_source_guardrail_penalty", text)


if __name__ == "__main__":
    unittest.main()
