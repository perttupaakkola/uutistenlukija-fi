import unittest
from types import SimpleNamespace
from unittest.mock import patch

import run_pipeline


class DuplicateOnlyBatchTests(unittest.TestCase):
    def test_all_post_rewrite_duplicates_are_successful_noop(self):
        scanned = [{
            "title": "Fresh source item",
            "description": "This source has enough words to survive the thin-source prefilter " * 3,
            "research": "[Lähde: example.com] " + ("supporting source words " * 80),
            "source_domain": "example.com",
            "source_tier": 1,
        }]
        rewritten = [{
            "title": "Already published rewritten title",
            "content": "valid article body " * 80,
            "description": "desc",
        }]

        def published_dedup_side_effect(articles, window_hours=24):
            if articles and "content" in articles[0]:
                return []
            return articles

        with patch.object(run_pipeline, "scan_all_feeds", return_value=scanned), \
             patch.object(run_pipeline, "poll_firehose", return_value=[]), \
             patch.object(run_pipeline, "filter_new_articles", side_effect=lambda articles: articles), \
             patch.object(run_pipeline, "check_published_duplicates", side_effect=published_dedup_side_effect), \
             patch.object(run_pipeline, "dedup_within_batch", side_effect=lambda articles: articles), \
             patch.object(run_pipeline, "enrich_with_research", side_effect=lambda articles: articles), \
             patch.object(run_pipeline, "rewrite_articles", return_value=rewritten), \
             patch.object(run_pipeline, "_run_quality_gate", return_value=SimpleNamespace(passed=rewritten, rejected=[], reject_reasons={}, stats={})), \
             patch.object(run_pipeline, "notify_discord_warning"), \
             patch.object(run_pipeline, "_write_final_metrics") as metrics, \
             patch.object(run_pipeline, "publish_articles") as publish:
            ok = run_pipeline.run(quick=True, max_articles=3, dedup_window=48)

        self.assertTrue(ok)
        publish.assert_not_called()
        self.assertTrue(metrics.call_args.kwargs["success"])


if __name__ == "__main__":
    unittest.main()
