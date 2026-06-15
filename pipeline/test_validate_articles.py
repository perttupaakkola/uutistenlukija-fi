import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import validate_articles as validator


ARTICLE = """---
title: "Testiuutinen"
date: "2026-06-15T12:00:00Z"
categories:
  - "Kotimaa"
tags:
  - "testi"
image: "/images/test.jpg"
---

Tämä on ensimmäinen kappale, josta voidaan muodostaa hakukonekuvaus ilman ulkoisia palveluita.
"""

ARTICLE_WITH_QUOTES = """---
title: "Sitaattiuutinen"
date: "2026-06-15T12:00:00Z"
categories:
  - "Ulkomaat"
tags:
  - "testi"
image: "/images/test.jpg"
---

Ministeri sanoi, että "hauras sopu" kestää vain, jos kaikki osapuolet noudattavat ehtoja rauhallisesti.
"""


class ValidateArticlesDryRunTest(unittest.TestCase):
    def test_fix_descriptions_dry_run_does_not_modify_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content_dir = Path(tmp)
            article_path = content_dir / "test.md"
            article_path.write_text(ARTICLE, encoding="utf-8")

            with patch.object(validator, "CONTENT_DIR", content_dir):
                result = validator.validate_articles(fix_descriptions=True, dry_run=True)

            self.assertEqual(article_path.read_text(encoding="utf-8"), ARTICLE)
            self.assertEqual(result["fixed_descriptions"], 1)
            self.assertEqual(result["counts"].get(validator.CHECK_DESCRIPTION, 0), 0)

    def test_fix_descriptions_live_mode_modifies_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content_dir = Path(tmp)
            article_path = content_dir / "test.md"
            article_path.write_text(ARTICLE, encoding="utf-8")

            with patch.object(validator, "CONTENT_DIR", content_dir):
                result = validator.validate_articles(fix_descriptions=True, dry_run=False)

            updated = article_path.read_text(encoding="utf-8")
            self.assertIn('description: "Tämä on ensimmäinen kappale', updated)
            self.assertEqual(result["fixed_descriptions"], 1)
            self.assertEqual(result["counts"].get(validator.CHECK_DESCRIPTION, 0), 0)

    def test_fix_descriptions_escapes_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content_dir = Path(tmp)
            article_path = content_dir / "test.md"
            article_path.write_text(ARTICLE_WITH_QUOTES, encoding="utf-8")

            with patch.object(validator, "CONTENT_DIR", content_dir):
                result = validator.validate_articles(fix_descriptions=True, dry_run=False)

            updated = article_path.read_text(encoding="utf-8")
            self.assertIn('\\"hauras sopu\\"', updated)
            self.assertEqual(result["fixed_descriptions"], 1)
            self.assertEqual(result["counts"].get(validator.CHECK_DESCRIPTION, 0), 0)


if __name__ == "__main__":
    unittest.main()
