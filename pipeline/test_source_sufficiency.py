import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline import staged_publish
from pipeline.source_sufficiency import (
    article_source_ratio,
    deduplicated_selected_source_words,
    selected_source_admission_errors,
)
from pipeline.staged_publish import worker_source_ratio_issues


def words(count, prefix="source"):
    return " ".join(f"{prefix}{index}" for index in range(count))


def block(count=200, *, url="https://example.test/story", text=None):
    return {
        "source": "Fixture",
        "source_url": url,
        "source_domain": "example.test",
        "text": text or words(count),
    }


def packet(blocks):
    return {
        "clean_source_blocks": blocks,
        "selected_source_provenance_error": "",
        "source_selection_outcome": "usable_source_packet",
    }


def usage(url="https://example.test/story"):
    return [{"source_url": url, "used": True, "dependent_claims": ["fixture claim"]}]


class SourceSufficiencyTests(unittest.TestCase):
    def test_duplicate_raw_total_above_200_cannot_inflate_distinct_199(self):
        full = words(199)
        blocks = [block(text=full), block(text=full)]
        self.assertEqual(deduplicated_selected_source_words(blocks), 199)
        self.assertIn("thin_distinct_source", selected_source_admission_errors(packet(blocks)))

    def test_exact_200_with_public_provenance_reaches_admission(self):
        self.assertEqual(selected_source_admission_errors(packet([block()])), ())

    def test_missing_or_invalid_selected_url_is_hard_reject(self):
        errors = selected_source_admission_errors(packet([block(url="")]))
        self.assertIn("selected_source_url_missing", errors)
        self.assertIn("selected_source_url_invalid", errors)

    def test_ratio_boundary_200_to_270_passes_and_271_fails(self):
        source_blocks = [block()]
        self.assertEqual(article_source_ratio(words(270, "article"), source_blocks), 1.35)
        self.assertEqual(worker_source_ratio_issues(packet(source_blocks), {"content": words(270, "article"), "source_usage": usage()}), [])
        issues = worker_source_ratio_issues(packet(source_blocks), {"content": words(271, "article"), "source_usage": usage()})
        self.assertEqual(len(issues), 1)
        self.assertIn("exceeds 1.35", issues[0])

    def test_worker_never_writes_ratio_failure_to_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for box in ("ready", "writing", "outbox", "failed"):
                (root / box).mkdir()
            source_blocks = [block()]
            ready = root / "ready/packet.json"
            ready.write_text(json.dumps({
                "packet": {
                    **packet(source_blocks),
                    "packet_id": "packet",
                    "category": "Ulkomaat",
                    "category_hint": "Ulkomaat",
                },
                "original_article": {
                    "title": "Fixture",
                    "description": "Fixture description",
                    "link": "https://example.test/story",
                    "category": "Ulkomaat",
                    "category_hint": "Ulkomaat",
                },
            }), encoding="utf-8")
            payload = {
                "packet_id": "packet",
                "title": "Fixture",
                "summary": "Fixture summary",
                "content": words(271, "article"),
                "category": "Ulkomaat",
                "tags": ["fixture"],
                "summary_bullets": ["one", "two", "three"],
                "content_type": "article",
                "editorial_reviewed": True,
                "confidence": 0.9,
                "journalist_note": "",
                "source_usage": usage(),
            }
            with patch.object(staged_publish, "STAGED_ROOT", root), \
                 patch.object(staged_publish, "_basic_payload_issues", return_value=[]), \
                 patch.object(staged_publish, "_run_monica", side_effect=[json.dumps(payload), json.dumps(payload)]):
                status, detail = staged_publish.process_one_packet(ready, object())
            self.assertEqual(status, "failed")
            self.assertIn("ratio exceeds", detail)
            self.assertFalse((root / "outbox/packet.json").exists())
            self.assertTrue((root / "failed/packet.json").exists())

    def test_exact_199_268_fails_before_writer_and_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for box_name in ("ready", "writing", "outbox", "failed"):
                (root / box_name).mkdir()
            ready = root / "ready/packet.json"
            ready.write_text(json.dumps({
                "packet": {**packet([block(199)]), "packet_id": "packet", "category": "Ulkomaat"},
                "original_article": {"title": "Fixture", "link": "https://example.test/story"},
            }), encoding="utf-8")
            prospective_payload = {"content": words(268, "article")}
            with patch.object(staged_publish, "STAGED_ROOT", root), \
                 patch.object(staged_publish, "_run_monica", return_value=json.dumps(prospective_payload)) as writer:
                status, detail = staged_publish.process_one_packet(ready, object())
            self.assertEqual(len(prospective_payload["content"].split()), 268)
            self.assertEqual(status, "failed")
            self.assertIn("thin_distinct_source", detail)
            writer.assert_not_called()
            self.assertFalse((root / "outbox/packet.json").exists())
            failed = json.loads((root / "failed/packet.json").read_text(encoding="utf-8"))
            self.assertEqual(failed["writer_failure_feedback"]["stage"], "pre_monica_source_admission")

    def test_usage_reduction_enforces_used_source_floor(self):
        blocks = [
            block(120, url="https://example.test/one"),
            block(120, url="https://example.test/two", text=words(120, "other")),
        ]
        payload = {
            "content": words(160, "article"),
            "source_usage": [
                {"source_url": "https://example.test/one", "used": True, "dependent_claims": ["one"]},
                {"source_url": "https://example.test/two", "used": False, "dependent_claims": []},
            ],
        }
        issues = worker_source_ratio_issues(packet(blocks), payload)
        self.assertTrue(any("used-source distinct words below 200" in issue for issue in issues))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for box_name in ("ready", "writing", "outbox", "failed"):
                (root / box_name).mkdir()
            ready = root / "ready/packet.json"
            ready.write_text(json.dumps({
                "packet": {**packet(blocks), "packet_id": "packet", "category": "Ulkomaat"},
                "original_article": {"title": "Fixture", "link": "https://example.test/one"},
            }), encoding="utf-8")
            complete_payload = {
                "packet_id": "packet", "title": "Fixture", "summary": "Summary",
                "content": payload["content"], "category": "Ulkomaat", "tags": ["fixture"],
                "summary_bullets": ["one", "two", "three"], "content_type": "article",
                "editorial_reviewed": True, "confidence": 0.9, "journalist_note": "",
                "source_usage": payload["source_usage"],
            }
            with patch.object(staged_publish, "STAGED_ROOT", root), \
                 patch.object(staged_publish, "_basic_payload_issues", return_value=[]), \
                 patch.object(staged_publish, "_run_monica", side_effect=[json.dumps(complete_payload), json.dumps(complete_payload)]):
                status, detail = staged_publish.process_one_packet(ready, object())
            self.assertEqual(status, "failed")
            self.assertIn("used-source distinct words below 200", detail)
            self.assertFalse((root / "outbox/packet.json").exists())
            self.assertTrue((root / "failed/packet.json").exists())


if __name__ == "__main__":
    unittest.main()
