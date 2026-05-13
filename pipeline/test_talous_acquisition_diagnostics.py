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


if __name__ == "__main__":
    unittest.main()
