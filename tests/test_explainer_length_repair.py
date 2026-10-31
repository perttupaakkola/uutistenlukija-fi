"""Real case 31 Oct 2026: a 412-word explainer draft (Jämsä athlete award) was reused on
every retry and failed with the same 500–900 word error. It must get one bounded repair."""
import json
import unittest
from pathlib import Path

from news_mvp.controller import repair_explainer_length
from news_mvp.editorial import explainer_word_count

FIXTURE = Path(__file__).resolve().parent / "fixtures/explainers/short-draft-2026-10-31.json"


class Model:
    def __init__(self, value):
        self.value, self.calls = value, []

    def call(self, role, packet, draft=None, *, context=None):
        self.calls.append((role, context))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value(draft) if callable(self.value) else self.value


def lengthen(draft):
    paragraphs = [dict(p) for p in draft["paragraphs"]]
    paragraphs[1]["text"] += " " + " ".join(["lisätieto"] * 200)
    return {**draft, "paragraphs": paragraphs, "image": {"tampered": True}}


class LengthRepair(unittest.TestCase):
    def setUp(self):
        self.draft = json.loads(FIXTURE.read_text())
        self.packet = {"kind": "explainer"}

    def test_real_short_draft_is_counted_short(self):
        self.assertEqual(explainer_word_count(self.draft), 412)

    def test_one_bounded_repair_is_used_and_image_kept(self):
        model = Model(lengthen)
        result = repair_explainer_length(model, self.packet, self.draft)
        self.assertEqual(len(model.calls), 1)
        role, context = model.calls[0]
        self.assertEqual(role, "reviser")
        self.assertIn("412 sanaa", context["review"]["reasons"][0])
        self.assertTrue(500 <= explainer_word_count(result) <= 900)
        self.assertEqual(result["image"], self.draft["image"])
        self.assertEqual(result["kind"], "explainer")

    def test_failed_or_worse_repair_keeps_draft(self):
        for value in (RuntimeError("down"), {"withhold": True},
                      lambda d: {**d, "paragraphs": d["paragraphs"][:2]}):
            model = Model(value)
            self.assertIs(repair_explainer_length(model, self.packet, self.draft), self.draft)
            self.assertEqual(len(model.calls), 1)

    def test_in_range_and_news_drafts_make_no_call(self):
        model = Model(lengthen)
        ok = lengthen(self.draft)
        self.assertIs(repair_explainer_length(model, self.packet, ok), ok)
        self.assertIs(repair_explainer_length(model, {}, self.draft), self.draft)
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()
