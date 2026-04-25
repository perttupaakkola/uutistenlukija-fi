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

    def test_pipeline_lock_warns_when_pid_is_dead_even_if_fresh(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write("999999\n2026-04-25T07:50:01Z\n")
            tmp_path = tmp.name

        try:
            with mock.patch.object(health_check, "LOCK_FILE", tmp_path), mock.patch.object(
                health_check.os, "kill", side_effect=ProcessLookupError
            ):
                result = health_check.check_pipeline_lock()
        finally:
            os.unlink(tmp_path)

        self.assertEqual(result["status"], "WARN")
        self.assertIn("dead PID 999999", result["message"])
        self.assertEqual(result["value"]["pid"], 999999)
        self.assertFalse(result["value"]["pid_alive"])


if __name__ == "__main__":
    unittest.main()
