"""Owner rule (10 Oct 2026): no disclaimer/meta clutter on reader pages.

Readers do not need notes about how search works, that the site is automated,
or that a link "is not an Uutistenlukija news story". Production facts live on
the About page only. Required image credits/licences and AI-image labels stay.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["news_mvp/site.py", "news_mvp/frontpage.py", "news_mvp/utility_guides.py",
           "news_mvp/holiday_reference.py"]
BANNED = ["ei Uutistenlukijan", "uutisjuttu", "Haku näyttää", "header-search-note",
          "ei reaaliaikainen", "HÄIRIÖILMOITUS", "Varoitukset voivat muuttua",
          "kyse ei ole uudesta päätöksestä", "savutestiohje", "Puuttuva tieto ei ole lupaus",
          "Ilman JavaScriptiä lomake", "tarkista näkyvä julkaisuaika",
          "Uutistenlukija · automaattisesti tuotettu"]


class NoDisclaimerClutter(unittest.TestCase):
    def test_reader_templates_have_no_disclaimer_phrases(self):
        found = []
        for rel in SOURCES:
            text = (ROOT / rel).read_text()
            found += [f"{rel}: {phrase}" for phrase in BANNED if phrase in text]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
