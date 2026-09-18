"""IndexNow contracts: key hosted at the root, submission strictly best-effort."""
import json
import unittest
from unittest.mock import patch


class IndexNow(unittest.TestCase):
    def test_key_is_hex_and_served_from_the_site_root(self):
        from news_mvp import indexing
        self.assertRegex(indexing.INDEXNOW_KEY, r'^[0-9a-f]{32}$')
        self.assertEqual(indexing.key_name(), indexing.INDEXNOW_KEY + '.txt')

    def test_ping_posts_the_documented_payload(self):
        from news_mvp import indexing
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            captured['url'] = request.full_url
            captured['body'] = json.loads(request.data.decode())
            return Response()

        with patch('urllib.request.urlopen', fake_urlopen):
            self.assertTrue(indexing.ping(['https://uutistenlukija.fi/uutiset/x/']))
        self.assertEqual(captured['url'], indexing.ENDPOINT)
        self.assertEqual(captured['body']['host'], 'uutistenlukija.fi')
        self.assertEqual(captured['body']['key'], indexing.INDEXNOW_KEY)
        self.assertEqual(captured['body']['urlList'], ['https://uutistenlukija.fi/uutiset/x/'])

    def test_ping_never_raises_and_filters_foreign_urls(self):
        from news_mvp import indexing

        def boom(*args, **kwargs):
            raise OSError('offline network')

        with patch('urllib.request.urlopen', boom):
            self.assertFalse(indexing.ping(['https://uutistenlukija.fi/uutiset/x/']))
            self.assertFalse(indexing.ping(['https://example.com/other']))
            self.assertFalse(indexing.ping([]))


if __name__ == "__main__":
    unittest.main()
