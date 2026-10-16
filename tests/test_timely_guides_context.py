import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from news_mvp import site


def row():
    job = {"id": "other", "created_at": "2026-10-10T00:00:00+00:00", "slug": "testi"}
    return (job, {}, {"category": "Kulttuuri", "title": "Testi"}, {})


class TimelyGuidesContext(unittest.TestCase):
    def render(self, when):
        with patch("news_mvp.site.ClockDateTime") as clock:
            clock.now.return_value = when
            return site.article_context_html({"id": "x"}, {"category": "Kulttuuri"}, [row()])

    def test_article_pages_link_next_dated_guides(self):
        body = self.render(datetime(2026, 10, 16, 12, tzinfo=timezone.utc))
        self.assertIn("Ajankohtaiset oppaat", body)
        self.assertIn('href="/oppaat/kellojen-siirto-2026/"', body)
        self.assertEqual(body.count('href="/oppaat/'), 4)

    def test_past_events_drop_out(self):
        body = self.render(datetime(2026, 10, 26, 12, tzinfo=timezone.utc))
        self.assertNotIn("kellojen-siirto", body)
        self.assertIn('href="/oppaat/isanpaiva-2026/"', body)

    def test_no_guides_block_without_other_context(self):
        with patch("news_mvp.site.ClockDateTime") as clock:
            clock.now.return_value = datetime(2026, 10, 16, tzinfo=timezone.utc)
            self.assertEqual(site.article_context_html({"id": "x"}, {"category": "Kulttuuri"}, []), "")


if __name__ == "__main__":
    unittest.main()
