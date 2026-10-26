import unittest
from datetime import datetime, timezone
from news_mvp import calendar_feed, utility_guides


class CalendarFeedTest(unittest.TestCase):
    def test_feed_is_valid_and_links_guides(self):
        text = calendar_feed.ics(datetime(2026, 10, 26, tzinfo=timezone.utc))
        self.assertTrue(text.startswith('BEGIN:VCALENDAR\r\n'))
        self.assertTrue(text.endswith('END:VCALENDAR\r\n'))
        self.assertEqual(text.count('BEGIN:VEVENT'), len(calendar_feed.EVENTS))
        for line in text.split('\r\n'):
            self.assertLessEqual(len(line.encode('utf-8')), 75)
        uids = [l for l in text.split('\r\n') if l.startswith('UID:')]
        self.assertEqual(len(uids), len(set(uids)))
        paths = set(utility_guides.GUIDE_PATHS)
        for _, _, path in calendar_feed.EVENTS:
            self.assertIn(path, paths)


if __name__ == '__main__':
    unittest.main()
