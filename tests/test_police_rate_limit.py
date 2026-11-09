import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from news_mvp import official

FEED = b'<rss><channel></channel></rss>'
# Real failure seen 9 Nov 2026 on the Länsi-Uusimaa feed: third police request in a tick.
LANSI = 'https://poliisi.fi/lansi-uudenmaan-poliisilaitos/-/asset_publisher/NbhxOTjN3wK9/rss'


def too_many(url):
    return HTTPError(url, 429, 'Too Many Requests', {'cf-mitigated': 'challenge'}, io.BytesIO(b''))


class PoliceRateLimit(unittest.TestCase):
    def setUp(self):
        official._last_host_fetch.clear()

    def test_429_retried_once_after_pause(self):
        calls = []
        def fetch(url, hosts):
            calls.append(url)
            if len(calls) == 1:
                raise too_many(url)
            return FEED, 'application/rss+xml', url
        with patch.object(official, 'fetch', side_effect=fetch), \
                patch('time.sleep') as sleep:
            self.assertEqual(official.response(LANSI, ['poliisi.fi']), FEED)
        self.assertEqual(len(calls), 2)
        self.assertIn(official.RATE_LIMIT_RETRY_SECONDS, [c.args[0] for c in sleep.call_args_list])

    def test_second_429_is_not_a_loop(self):
        calls = []
        def fetch(url, hosts):
            calls.append(url); raise too_many(url)
        with patch.object(official, 'fetch', side_effect=fetch), patch('time.sleep'):
            with self.assertRaises(HTTPError):
                official.response(LANSI, ['poliisi.fi'])
        self.assertEqual(len(calls), 2, 'exactly one bounded retry')

    def test_police_feeds_spaced_not_burst(self):
        now = [1000.0]
        slept = []
        def sleep(s):
            slept.append(s); now[0] += s
        spec = official.policy()['providers']
        with patch.object(official, 'fetch', side_effect=lambda u, h: (FEED, 'application/rss+xml', u)), \
                patch('time.monotonic', side_effect=lambda: now[0]), patch('time.sleep', side_effect=sleep):
            for p in official.POLICE_PROVIDERS[:3]:
                official.response(spec[p]['index'], spec[p]['hosts'])
        self.assertEqual(len(slept), 2)
        self.assertTrue(all(s >= official.HOST_SPACING_SECONDS['poliisi.fi'] - 0.01 for s in slept))

    def test_other_hosts_unaffected(self):
        with patch.object(official, 'fetch', side_effect=lambda u, h: (FEED, 'application/rss+xml', u)), \
                patch('time.sleep') as sleep:
            official.response('https://www.hel.fi/fi/uutiset/rss', ['www.hel.fi'])
            official.response('https://www.hel.fi/fi/uutiset/rss', ['www.hel.fi'])
        sleep.assert_not_called()
        with patch.object(official, 'fetch', side_effect=too_many('x')), patch('time.sleep'):
            with self.assertRaises(HTTPError):
                official.response('https://www.hel.fi/fi/uutiset/rss', ['www.hel.fi'])


if __name__ == '__main__':
    unittest.main()
