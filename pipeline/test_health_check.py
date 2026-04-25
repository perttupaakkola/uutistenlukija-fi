import os
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
