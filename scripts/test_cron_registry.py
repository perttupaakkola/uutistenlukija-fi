#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "cron_registry.json"


class CronRegistryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.by_name = {job["name"]: job for job in cls.jobs}

    def test_job_names_are_unique(self):
        self.assertEqual(len(self.jobs), len(self.by_name))

    def test_paused_or_migrated_local_jobs_are_disabled(self):
        for name in ("firehose_cron", "staged_scan", "staged_publish"):
            with self.subTest(name=name):
                job = self.by_name[name]
                self.assertIs(job.get("enabled"), False)
                self.assertTrue(job.get("disabled_reason"))

    def test_live_monica_worker_uses_the_stable_canonical_marker(self):
        job = self.by_name["staged_monica_worker"]
        self.assertEqual(
            job["marker_file_path"],
            "pipeline/logs/staged-monica-worker.log",
        )
        self.assertIn("END rc=0", job["latest_line_required_pattern"])
        self.assertTrue(
            any("END rc=" in pattern for pattern in job["latest_line_forbidden_patterns"])
        )


if __name__ == "__main__":
    unittest.main()
