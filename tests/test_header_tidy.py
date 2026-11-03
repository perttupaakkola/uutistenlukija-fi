"""Focused contracts for the approved tidy header."""

import unittest
from datetime import datetime, timezone

from news_mvp import site


class HeaderTidyTests(unittest.TestCase):
    def test_header_has_no_saved_stories_or_source_shortcuts(self):
        now = datetime.now(timezone.utc)
        snapshot = {"helsinki": {
            "updated_at": now.isoformat(),
            "hours": [{"time": now.isoformat(), "temperature": 7, "wind": 3}],
        }}
        rendered = site.page("Etusivu", "<p>Uutiset</p>", "/", snapshot=snapshot)
        header = rendered.split("</header>", 1)[0]
        self.assertNotIn("Tallennetut", rendered)
        self.assertNotIn("Tallenna", rendered)
        self.assertNotIn(">Lähde<", header)
        self.assertNotIn("ennuste</small>", header)
        self.assertIn("Ilmatieteen laitos, CC BY 4.0", header)
        self.assertIn("Säätiedot: Ilmatieteen laitos (CC BY 4.0)", rendered)

    def test_missing_weather_is_hidden_and_search_uses_wide_class(self):
        rendered = site.page("Etusivu", "<p>Uutiset</p>", "/", snapshot={})
        header = rendered.split("</header>", 1)[0]
        self.assertNotIn("portal-weather", header)
        self.assertIn("portal-search--wide", header)
        css = (site.ROOT / "static/css/portal-overhaul.css").read_text()
        self.assertIn(".portal-search--wide { width: 100%; max-width: 560px; }", css)


if __name__ == "__main__":
    unittest.main()
