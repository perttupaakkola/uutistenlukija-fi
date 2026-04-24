import unittest

import update_publish_metrics


class PublishMetricsOutcomeTest(unittest.TestCase):
    def test_successful_zero_publish_duplicate_noop_is_skip(self):
        run = {
            "success": True,
            "article_count": 0,
            "errors": [],
            "steps": {
                "scanner": {"success": True, "total": 25},
                "dedup": {"success": True, "remaining": 19},
                "research": {"success": True, "enriched": 19},
                "rewriter": {"success": True, "input_count": 9, "output_count": 2},
                "kw_dedup": {"dropped": 2, "passed": 0},
            },
        }

        self.assertEqual(update_publish_metrics.classify_outcome(run), "skip")

    def test_failed_run_is_error(self):
        run = {
            "success": False,
            "article_count": 0,
            "errors": ["writer crashed"],
            "steps": {"scanner": {"success": False, "total": 10}},
        }

        self.assertEqual(update_publish_metrics.classify_outcome(run), "error")


if __name__ == "__main__":
    unittest.main()
