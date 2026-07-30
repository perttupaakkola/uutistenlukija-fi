from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import staged_publish
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import staged_publish


class TalousInterimPriorityTests(unittest.TestCase):
    def test_talous_research_admission_gains_one_slot_only_below_floor(self) -> None:
        articles = [
            {
                "title": f"Kotimaa {index}",
                "category_hint": "Kotimaa",
            }
            for index in range(4)
        ] + [
            {
                "title": f"Ulkomaat {index}",
                "category_hint": "Ulkomaat",
            }
            for index in range(4)
        ] + [
            {
                "title": f"Talous {index}",
                "category_hint": "Talous",
            }
            for index in range(3)
        ]

        nominal = staged_publish.select_research_candidates(
            articles,
            max_candidates=8,
        )
        below_floor = staged_publish.select_research_candidates(
            articles,
            max_candidates=8,
            talous_priority_active=True,
        )

        nominal_talous = sum(
            staged_publish.article_category(article) == "Talous"
            for article in nominal
        )
        below_floor_talous = sum(
            staged_publish.article_category(article) == "Talous"
            for article in below_floor
        )
        self.assertEqual(len(nominal), 8)
        self.assertEqual(len(below_floor), 8)
        self.assertEqual(nominal_talous, 2)
        self.assertEqual(below_floor_talous, 3)

    def test_repository_category_mix_deactivates_priority_at_floor(self) -> None:
        below = staged_publish.talous_interim_priority_state(
            {"Talous": 14, "Kotimaa": 86}
        )
        at_floor = staged_publish.talous_interim_priority_state(
            {"Talous": 15, "Kotimaa": 85}
        )

        self.assertEqual(below["share"], 0.14)
        self.assertTrue(below["active"])
        self.assertEqual(at_floor["share"], 0.15)
        self.assertFalse(at_floor["active"])

    def test_source_floor_still_rejects_weak_talous_candidate(self) -> None:
        qualifying = {
            "title": "Yritysten luottamus vahvistui",
            "category_hint": "Talous",
            "research": (
                "[Lähde: A]\n"
                + "sana " * 100
                + "\n\n[Lähde: B]\n"
                + "sana " * 100
            ),
            "description": "Kahteen lähteeseen perustuva talousuutinen.",
            "story_confidence": 0.9,
        }
        weak = {
            "title": "Ohut talouskatkelma",
            "category_hint": "Talous",
            "research": "[Lähde: A]\n" + "sana " * 100,
            "description": "Yksi lyhyt lähdekatkelma.",
            "story_confidence": 0.98,
        }

        self.assertTrue(staged_publish.passes_priority_source_floor(qualifying))
        self.assertTrue(staged_publish.scan_candidate_passes_talous_reserve(qualifying))
        self.assertFalse(staged_publish.passes_priority_source_floor(weak))
        self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(weak))

    def test_duplicate_talous_candidate_remains_terminal_during_cooldown(self) -> None:
        article = {
            "title": "Jo julkaistu Talous-uutinen",
            "url": "https://example.test/already-published",
            "category_hint": "Talous",
        }
        digest = staged_publish.stable_digest(article)

        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp)
            for box in ["ready", "writing", "outbox", "published", "failed"]:
                (staged_root / box).mkdir()
            (staged_root / "failed" / "duplicate.json").write_text(
                json.dumps(
                    {
                        "digest": digest,
                        "duplicate_rejected": True,
                        "packet": {"category_hint": "Talous"},
                        "original_article": article,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(staged_publish, "STAGED_ROOT", staged_root):
                should_skip = staged_publish.should_skip_staged_cooldown(
                    article,
                    hours=24,
                )

        self.assertTrue(should_skip)


if __name__ == "__main__":
    unittest.main()
