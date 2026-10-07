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

    def test_received_receipt_is_redacted_and_utc(self):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        from news_mvp import indexing
        receipts = []
        response = MagicMock()
        response.__enter__.return_value.status = 200
        urls = ['https://uutistenlukija.fi/uutiset/x/']
        with patch('urllib.request.urlopen', return_value=response) as opened:
            self.assertTrue(indexing.ping(urls, result_callback=receipts.append))
        opened.assert_called_once()
        self.assertEqual(opened.call_args.kwargs['timeout'], 15)
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertEqual(set(receipt), {'timestamp_utc', 'canonical_urls', 'http_status', 'result_class'})
        self.assertEqual(receipt['canonical_urls'], urls)
        self.assertEqual(receipt['http_status'], 200)
        self.assertEqual(receipt['result_class'], 'received200')
        self.assertEqual(datetime.fromisoformat(receipt['timestamp_utc']).tzinfo, timezone.utc)

    def test_receipt_outcomes_and_callback_failure_do_not_retry(self):
        from unittest.mock import MagicMock
        from urllib.error import HTTPError
        from news_mvp import indexing
        cases = [(202, 'validation_pending202', True, None),
                 (204, 'other2xx', True, None),
                 (403, 'rejected', False, None),
                 (HTTPError('https://redacted.invalid', 403, 'private text', {}, None),
                  'rejected', False, 'HTTPError'),
                 (TimeoutError('private text'), 'unknown', False, 'TimeoutError')]
        for outcome, classification, success, error_class in cases:
            for write_failure in (False, True):
                with self.subTest(outcome=classification, write_failure=write_failure):
                    receipts = []
                    def callback(receipt):
                        receipts.append(receipt)
                        if write_failure:
                            raise OSError('private storage failure')
                    response = MagicMock()
                    if isinstance(outcome, int):
                        response.__enter__.return_value.status = outcome
                    with patch('urllib.request.urlopen', return_value=response,
                               side_effect=outcome if isinstance(outcome, Exception) else None) as opened:
                        self.assertEqual(indexing.ping(['https://uutistenlukija.fi/'], result_callback=callback), success)
                    opened.assert_called_once()
                    self.assertEqual(len(receipts), 1)
                    receipt = receipts[0]
                    self.assertEqual(receipt['result_class'], classification)
                    self.assertEqual(receipt['http_status'], outcome if isinstance(outcome, int) else (403 if isinstance(outcome, HTTPError) else None))
                    self.assertEqual(receipt.get('error_class'), error_class)
                    expected = {'timestamp_utc', 'canonical_urls', 'http_status', 'result_class'}
                    if error_class:
                        expected.add('error_class')
                    self.assertEqual(set(receipt), expected)
                    self.assertNotIn('private', json.dumps(receipt))

    def test_no_eligible_urls_emits_one_skipped_receipt_without_request(self):
        from news_mvp import indexing
        receipts = []
        with patch('urllib.request.urlopen') as opened:
            self.assertFalse(indexing.ping([None, 'https://example.com/', 'http://uutistenlukija.fi/'],
                                           result_callback=receipts.append))
        opened.assert_not_called()
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['result_class'], 'skipped')
        self.assertEqual(receipts[0]['canonical_urls'], [])
        self.assertIsNone(receipts[0]['http_status'])

    def test_publish_callsite_writes_only_private_receipt_best_effort(self):
        # Exercise the existing small callsite directly without importing publisher
        # dependencies, deployment state, credentials, or any external operations.
        import ast
        from pathlib import Path
        from unittest.mock import Mock, MagicMock
        from news_mvp import indexing
        source = (Path(__file__).parents[1] / 'news_mvp' / 'publish.py').read_text()
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'ping']
        self.assertEqual(len(calls), 1)
        statement = max((node for node in ast.walk(tree) if isinstance(node, ast.Try)
                         and any(child is calls[0] for child in ast.walk(node))),
                        key=lambda node: node.lineno)
        code = compile(ast.Module(body=[statement], type_ignores=[]), '<publish-callsite>', 'exec')
        directory = Path('/private/existing/deployments/123')
        url = 'https://uutistenlukija.fi/uutiset/x/'
        for storage_failure in (False, True):
            writer = Mock(side_effect=OSError('private') if storage_failure else None)
            response = MagicMock()
            response.__enter__.return_value.status = 200
            with patch('urllib.request.urlopen', return_value=response) as opened:
                exec(code, {'__package__': 'news_mvp', 'url': url, 'receipt_dir': directory,
                            'atomic_write': writer, 'json': json})
            opened.assert_called_once()
            writer.assert_called_once()
            target, content = writer.call_args.args
            self.assertEqual(target, directory / 'indexnow-notification.json')
            self.assertEqual(json.loads(content)['canonical_urls'], [url, 'https://uutistenlukija.fi/'])
            self.assertEqual(json.loads(content)['result_class'], 'received200')
            self.assertNotIn(indexing.INDEXNOW_KEY, content)

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
