import os
import unittest

import health_check


class HealthCheckLockPathTests(unittest.TestCase):
    def test_pipeline_lock_path_matches_auto_publish_location(self):
        self.assertEqual(
            os.path.abspath(health_check.LOCK_FILE),
            os.path.abspath(os.path.join(os.path.dirname(health_check.__file__), ".pipeline_lock")),
        )


if __name__ == "__main__":
    unittest.main()
