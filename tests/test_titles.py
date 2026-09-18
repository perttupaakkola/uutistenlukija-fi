"""Headline budget contracts: <=60 characters, key noun first, repairs bounded and safe."""
import unittest

from news_mvp.controller import repair_title
from news_mvp.editorial import ROOT


class FakeModel:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def call(self, role, packet, draft=None):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class TitleRepair(unittest.TestCase):
    def _draft(self, title):
        return {"title": title, "summary": "s", "category": "Kotimaa", "paragraphs": []}

    def test_short_title_is_left_alone_without_a_model_call(self):
        model = FakeModel({"title": "should not be used"})
        draft = self._draft("Lyhyt otsikko")
        self.assertIs(repair_title(model, {}, draft), draft)
        self.assertEqual(model.calls, 0)

    def test_over_long_title_gets_one_bounded_repair(self):
        model = FakeModel({"title": "Tiivis otsikko aiheesta"})
        result = repair_title(model, {}, self._draft("x" * 80))
        self.assertEqual(result["title"], "Tiivis otsikko aiheesta")
        self.assertEqual(model.calls, 1)

    def test_repair_returning_over_budget_is_rejected(self):
        model = FakeModel({"title": "y" * 61})
        draft = self._draft("x" * 80)
        self.assertEqual(repair_title(model, {}, draft)["title"], "x" * 80)

    def test_repair_failure_keeps_original_title(self):
        model = FakeModel(RuntimeError("model down"))
        draft = self._draft("x" * 80)
        self.assertEqual(repair_title(model, {}, draft)["title"], "x" * 80)

    def test_repair_with_garbage_output_keeps_original_title(self):
        for bad in ({"nope": 1}, "screen", None, {"title": 5}, {"title": "   "}):
            model = FakeModel(bad)
            draft = self._draft("x" * 80)
            self.assertEqual(repair_title(model, {}, draft)["title"], "x" * 80, bad)


class PromptContract(unittest.TestCase):
    def test_writer_prompt_carries_the_60_character_budget(self):
        self.assertIn("60", (ROOT / "prompts/writer.md").read_text())

    def test_reviewer_prompt_carries_the_title_check(self):
        self.assertIn("60", (ROOT / "prompts/reviewer.md").read_text())

    def test_titler_prompt_exists_and_bounds_output(self):
        text = (ROOT / "prompts/titler.md").read_text()
        self.assertIn("60", text)
        self.assertIn('"title"', text)


if __name__ == "__main__":
    unittest.main()
