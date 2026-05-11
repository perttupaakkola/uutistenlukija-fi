import os
import tempfile
import unittest
import shutil
from unittest import mock

import health_check


class HealthCheckLockPathTests(unittest.TestCase):
    def test_pipeline_lock_path_matches_auto_publish_location(self):
        self.assertEqual(
            os.path.abspath(health_check.LOCK_FILE),
            os.path.abspath(os.path.join(os.path.dirname(health_check.__file__), ".pipeline_lock")),
        )

    def test_pipeline_lock_preserves_fresh_dead_pid_during_grace_window(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write("999999\n2026-04-25T07:50:01Z\n")
            tmp_path = tmp.name

        with mock.patch.object(health_check, "LOCK_FILE", tmp_path), mock.patch.object(
            health_check.os, "kill", side_effect=ProcessLookupError
        ):
            result = health_check.check_pipeline_lock()

        self.assertEqual(result["status"], "OK")
        self.assertIn("grace window", result["message"])
        self.assertEqual(result["value"]["pid"], 999999)
        self.assertFalse(result["value"]["pid_alive"])
        self.assertFalse(result["value"]["dead_lock_cleared"])
        self.assertTrue(os.path.exists(tmp_path))
        os.remove(tmp_path)

    def test_pipeline_lock_clears_dead_pid_after_grace_window(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write("999999\n2026-04-25T07:50:01Z\n")
            tmp_path = tmp.name
        old_mtime = health_check.time.time() - ((health_check.DEAD_LOCK_GRACE_MINUTES + 1) * 60)
        os.utime(tmp_path, (old_mtime, old_mtime))

        with mock.patch.object(health_check, "LOCK_FILE", tmp_path), mock.patch.object(
            health_check.os, "kill", side_effect=ProcessLookupError
        ):
            result = health_check.check_pipeline_lock()

        self.assertEqual(result["status"], "OK")
        self.assertIn("Removed dead .pipeline_lock for PID 999999", result["message"])
        self.assertEqual(result["value"]["pid"], 999999)
        self.assertFalse(result["value"]["pid_alive"])
        self.assertTrue(result["value"]["dead_lock_cleared"])
        self.assertFalse(os.path.exists(tmp_path))


class HealthCheckDiskTests(unittest.TestCase):
    def _mock_usage(self, total_gb, used_gb):
        gb = 1024 ** 3
        total = int(total_gb * gb)
        used = int(used_gb * gb)
        free = total - used
        return shutil._ntuple_diskusage(total=total, used=used, free=free)

    def test_disk_warns_at_high_used_percentage_even_above_free_gb_floor(self):
        with mock.patch.object(health_check.shutil, "disk_usage", return_value=self._mock_usage(75, 68)):
            result = health_check.check_disk_space()

        self.assertEqual(result["status"], "WARN")
        self.assertGreater(result["value"]["free_gb"], 2.0)
        self.assertGreaterEqual(result["value"]["used_pct"], health_check.DISK_WARN_USED_PCT)
        self.assertIn("Disk pressure", result["message"])

    def test_disk_errors_at_critical_used_percentage(self):
        with mock.patch.object(health_check.shutil, "disk_usage", return_value=self._mock_usage(75, 73)):
            result = health_check.check_disk_space()

        self.assertEqual(result["status"], "ERROR")
        self.assertGreaterEqual(result["value"]["used_pct"], health_check.DISK_ERROR_USED_PCT)
        self.assertIn("Disk critical", result["message"])


if __name__ == "__main__":
    unittest.main()
