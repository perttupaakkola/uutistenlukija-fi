import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from news_mvp import site

class HolidayContext(unittest.TestCase):
    def context(self, job_id):
        return site.article_context_html({"id": job_id}, {"category": "Kulttuuri"}, [])

    def test_exact_reviewed_stories_link_to_guide_without_news_timestamp(self):
        for job_id in site.GUIDES_JOB_IDS:
            body = self.context(job_id)
            self.assertEqual(body.count('href="/syysloma-2026/"'), 1)
            self.assertIn("Syysloman opas", body)
            self.assertIn("Helsinki, Vantaa ja Kuopio", body)
            self.assertNotIn("<time", body)

    def test_unrelated_and_prefix_stories_have_no_promotion(self):
        for job_id in ["unrelated", *[i + "-other" for i in site.GUIDES_JOB_IDS]]:
            self.assertEqual(self.context(job_id), "")

    def test_expired_comparison_is_truthfully_labelled_archive(self):
        with patch("news_mvp.site.ClockDateTime") as clock:
            clock.now.return_value = datetime(2026, 10, 19, tzinfo=timezone.utc)
            body = self.context(next(iter(site.GUIDES_JOB_IDS)))
        self.assertIn("maksuttoman tekemisen arkisto", body)
        self.assertNotIn("vertaile kuutta", body)

    def test_existing_section_routes_remain_on_ordinary_stories(self):
        job = {"id": "other", "created_at": "2026-10-10T00:00:00+00:00",
               "draft": '{"title":"Testi"}'}
        row = (job, {}, {"category": "Kulttuuri", "title": "Testi"}, {})
        body = site.article_context_html({"id":"unrelated"}, {"category":"Kulttuuri"}, [row])
        self.assertIn("Samasta osastosta", body)
        self.assertNotIn("/syysloma-2026/", body)
