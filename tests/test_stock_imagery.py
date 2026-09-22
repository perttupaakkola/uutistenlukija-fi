"""Offline tests for the Unsplash/Pexels stock helpers in news_mvp/imagery.py.

Everything here is offline: HTTP is a fake opener that records the URLs and headers it was
called with, the credential loader is pointed at a temporary root, and describe() is stubbed
except where a test deliberately makes it fail. One test verifies a real checkerboard raster,
so the blank-image check in verify() is exercised against actual pixels rather than a stub.
Generation tests mock both stock helpers; provider-chain integration tests below mock every
transport and use a temporary quota cache/state directory.
"""
import importlib
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from email.utils import formatdate
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from news_mvp import editorial, imagery

KEY = 'test-access-key-value'
SECRET_MARKER = 'KEY-MUST-NOT-APPEAR'

DRAFT = {
    'title': 'Poliisi tutkii rikosta',
    'paragraphs': [{'text': 'Talous kasvaa hitaasti.'}],
}


def _checkerboard_bytes(width=900, height=600, block=100):
    """A genuinely non-blank raster: alternating filled blocks, not thin drawn lines.

    verify() has a blank-image guard (expressed on 32x32 tiles), so a raster whose only marks
    are three single-pixel lines can be rejected as effectively empty. Real blocks cannot.
    """
    colors = ((18, 24, 32), (236, 240, 246))
    raster = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(raster)
    for top in range(0, height, block):
        for left in range(0, width, block):
            draw.rectangle(
                [left, top, min(left + block - 1, width - 1), min(top + block - 1, height - 1)],
                fill=colors[(left // block + top // block) % 2])
    buffer = io.BytesIO()
    raster.save(buffer, format='PNG')
    return buffer.getvalue()


def _rgba_checkerboard_bytes():
    with Image.open(io.BytesIO(_checkerboard_bytes())) as source:
        raster = source.convert('RGBA')
    buffer = io.BytesIO()
    raster.save(buffer, format='PNG')
    return buffer.getvalue()


def _photo(photo_id='ABC123xyz', urls=None, links=None, user=None, description=None):
    item = {
        'id': photo_id,
        'alt_description': description if description is not None else 'a police car in snow',
        'urls': urls if urls is not None else {
            'raw': 'https://images.unsplash.com/photo-1?ixid=abc&w=1080&fm=jpeg&fit=clip',
            'regular': 'https://images.unsplash.com/photo-1?w=1080',
        },
        # Both links must name this photo: the download path is validated against the photo id.
        'links': links if links is not None else {
            'html': f'https://unsplash.com/photos/{photo_id}',
            'download_location': f'https://api.unsplash.com/photos/{photo_id}/download',
        },
        'user': user if user is not None else {
            'name': 'Matti Meikalainen',
            'links': {'html': 'https://unsplash.com/@photographer'},
        },
    }
    if description is None:
        item.pop('description', None)
    return item


def _pexels_photo(photo_id=123456, photo_url=None, profile_url=None, image_url=None,
                  large_url=None, large2x_url=None, original_url=None,
                  alt='a police car in snow', photographer='Matti Meikalainen'):
    photo_id = str(photo_id)
    image_base = f'https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg'
    return {
        'id': int(photo_id) if photo_id.isdigit() else photo_id,
        'url': photo_url or f'https://www.pexels.com/photo/police-car-in-snow-{photo_id}/',
        'photographer': photographer,
        'photographer_url': profile_url or 'https://www.pexels.com/@photographer',
        'alt': alt,
        'src': {
            'large': large_url or image_url or image_base + '?auto=compress&cs=tinysrgb&w=940',
            'large2x': large2x_url or image_base + '?auto=compress&cs=tinysrgb&w=1880',
            'original': original_url or image_base,
        },
    }


class FakeResponse:
    def __init__(self, url, body=b'', status=200, headers=None):
        self._url = url
        self._body = body
        self.status = status
        self.headers = headers or {}

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def read(self, amount=-1):
        return self._body if amount is None or amount < 0 else self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RedirectTo(Exception):
    """The fake transport hands a redirect back to the registered handler."""

    def __init__(self, target):
        super().__init__(target)
        self.target = target


class FakeOpener:
    def __init__(self, state):
        self.state = state

    def open(self, request, timeout=None):
        self.state['calls'].append((request.full_url, dict(request.headers)))
        serve = self.state['serve']
        if serve is None:
            raise AssertionError('HTTP must not be attempted without a credential')
        try:
            return serve(request.full_url, request)
        except RedirectTo as redirect:
            handler = self.state['handler']
            decided = handler.redirect_request(
                request, None, 302, 'Found', {}, redirect.target)
            if decided is None:
                raise urllib.error.HTTPError(
                    request.full_url, 302, 'Found', {}, None) from None
            raise AssertionError('same-host redirect should be followed by urllib itself')


class StockImageryTests(unittest.TestCase):
    """Base case: offline transport, temporary credential root, stubbed describe()."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._temporary.name)
        self.state = {'calls': [], 'serve': None, 'handler': None, 'handlers': []}
        self.addCleanup(self._temporary.cleanup)

        def build_opener(*handlers):
            for handler in handlers:
                self.state['handlers'].append(handler)
                if isinstance(handler, urllib.request.HTTPRedirectHandler):
                    self.state['handler'] = handler
            return FakeOpener(self.state)

        env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        env_patcher.start()
        os.environ.pop('UNSPLASH_ACCESS_KEY', None)
        os.environ.pop('PEXELS_API_KEY', None)
        os.environ['XDG_CACHE_HOME'] = str(self.tmp_path / 'cache')
        self.addCleanup(env_patcher.stop)

        for patcher in (
            mock.patch.object(urllib.request, 'build_opener', build_opener),
            mock.patch.object(imagery, 'describe',
                              lambda raw: 'a police car parked in the snow'),
            mock.patch.object(imagery, 'DEFAULT_CREDENTIAL_ROOT',
                              str(self.tmp_path)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # Never look at the machine's real credential tree: the temporary root is the only one
        # the default lookup can see, and it stays empty until _credentials() writes into it.

    def _serve(self, search='ok', image='ok', download='ok', results=None):
        payload = {'total': 1, 'results': results if results is not None else [_photo()]}

        def serve(url, request):
            host = urllib.parse.urlsplit(url).hostname
            path = urllib.parse.urlsplit(url).path
            if host == imagery.UNSPLASH_API_HOST and path == '/search/photos':
                if search == 'http-error':
                    raise urllib.error.HTTPError(url, 503, 'unavailable', {}, None)
                if search == 'malformed':
                    return FakeResponse(url, b'not json at all')
                if search == 'redirect-off-host':
                    raise RedirectTo('https://evil.example/steal')
                if search == 'redirect-same-host':
                    raise RedirectTo('https://api.unsplash.com/search/photos?query=other')
                return FakeResponse(url, json.dumps(payload).encode('utf-8'))
            if host == imagery.UNSPLASH_IMAGE_HOST:
                if image == 'not-an-image':
                    return FakeResponse(url, b'not an image at all')
                if image == 'redirect-off-host':
                    raise RedirectTo('https://evil.example/steal')
                return FakeResponse(url, _checkerboard_bytes())
            if host == imagery.UNSPLASH_API_HOST and path.endswith('/download'):
                if download == 'http-error':
                    raise urllib.error.HTTPError(url, 403, 'forbidden', {}, None)
                if download == 'redirect-off-host':
                    raise RedirectTo('https://evil.example/steal')
                if download == 'redirect-same-host':
                    raise RedirectTo('https://api.unsplash.com/photos/ABC123xyz/download2')
                return FakeResponse(url, b'{}')
            raise AssertionError(f'unexpected URL {url}')

        self.state['serve'] = serve

    def _serve_pexels(self, search='ok', image='ok', results=None, headers=None,
                      image_bytes=None):
        payload = {'total_results': 1,
                   'photos': results if results is not None else [_pexels_photo()]}

        def serve(url, request):
            host = urllib.parse.urlsplit(url).hostname
            path = urllib.parse.urlsplit(url).path
            if host == imagery.PEXELS_API_HOST and path == '/v1/search':
                if search == 'http-error':
                    raise urllib.error.HTTPError(url, 503, 'unavailable', {}, None)
                if search == '429-error':
                    raise urllib.error.HTTPError(url, 429, 'rate limited', headers or {}, None)
                if search == '429-response':
                    return FakeResponse(url, b'', 429, headers=headers)
                if search == 'malformed':
                    return FakeResponse(url, b'not json at all')
                if search == 'redirect-off-host':
                    raise RedirectTo('https://evil.example/steal')
                if search == 'redirect-same-host':
                    raise RedirectTo('https://api.pexels.com/v1/search?query=other')
                return FakeResponse(url, json.dumps(payload).encode('utf-8'))
            if host == imagery.PEXELS_IMAGE_HOST:
                if image == 'not-an-image':
                    return FakeResponse(url, b'not an image at all')
                if image == 'redirect-off-host':
                    raise RedirectTo('https://evil.example/steal')
                return FakeResponse(url, image_bytes if image_bytes is not None
                                     else _checkerboard_bytes())
            raise AssertionError(f'unexpected URL {url}')

        self.state['serve'] = serve

    def _credentials(self, value=KEY, slug='uutistenlukija'):
        folder = self.tmp_path / slug / 'projects' / 'uutistenlukija'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / '.env').write_text(
            f'# comment line\nOPENAI_API_KEY=other\nUNSPLASH_ACCESS_KEY="{value}"\n',
            encoding='utf-8')
        return self.tmp_path

    def _urls(self):
        return [url for url, _ in self.state['calls']]

    # -- credentials -----------------------------------------------------

    def test_missing_key_returns_none_without_http(self):
        self._serve()
        self.assertIsNone(imagery.provider_key('unsplash', credential_root='/nonexistent-root'))
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertEqual(self.state['calls'], [])

    def test_provider_key_reads_temporary_root_at_call_time(self):
        self.assertIsNone(imagery.provider_key('unsplash', credential_root=self.tmp_path))
        root = self._credentials()
        self.assertEqual(imagery.provider_key('unsplash', credential_root=root), KEY)
        self.assertEqual(imagery.provider_key('unsplash'), KEY)
        empty = self.tmp_path / 'empty-root'
        empty.mkdir()
        self.assertIsNone(imagery.provider_key('unsplash', credential_root=empty))

    def test_provider_key_prefers_environment(self):
        self._credentials()
        with mock.patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': 'from-environment'}):
            self.assertEqual(imagery.provider_key('unsplash', credential_root=self.tmp_path),
                             'from-environment')

    # -- selection -------------------------------------------------------

    def test_successful_selection_is_a_hotlink_record_without_files(self):
        root = self._credentials()
        before = sorted(str(path) for path in root.rglob('*'))
        self._serve()

        record = imagery.fetch_unsplash(DRAFT)
        self.assertIsNotNone(record)

        hotlink = ('https://images.unsplash.com/photo-1'
                   '?ixid=abc&w=1536&q=80&fm=jpg&fit=crop')
        utm = 'utm_source=uutistenlukija&utm_medium=referral'
        page = f'https://unsplash.com/photos/ABC123xyz?{utm}'
        profile = f'https://unsplash.com/@photographer?{utm}'

        self.assertEqual(record['url'], hotlink)
        self.assertIs(record['generated'], False)
        self.assertIs(record['hotlink'], True)
        self.assertEqual(record['license'], 'Unsplash License')
        self.assertEqual(record['license_url'], 'https://unsplash.com/license')
        self.assertEqual(record['caption'], 'Arkistokuva. Kuva ei esitä uutisen tapahtumaa.')
        self.assertEqual(record['credit'], 'Photo by Matti Meikalainen on Unsplash')
        self.assertEqual(record['alt'], 'Arkistokuva: a police car parked in the snow')
        self.assertEqual(record['depicted'], 'a police car parked in the snow')
        self.assertEqual(record['source_url'], page)
        # The raster behind the hotlink is a real checkerboard and really went through verify().
        self.assertEqual(record['pixels']['width'], 900)
        self.assertEqual(record['pixels']['height'], 600)

        provenance = record['stock_provenance']
        self.assertEqual(provenance, {
            'provider': 'unsplash',
            'photo_id': 'ABC123xyz',
            'photographer': 'Matti Meikalainen',
            'photographer_url': profile,
            'photo_url': page,
            'query': 'police crime economy',
            'retrieved_at': provenance['retrieved_at'],
            'image_url': hotlink,
            'download_tracking': {
                'url': 'https://api.unsplash.com/photos/ABC123xyz/download',
                'successful': True,
            },
        })
        self.assertTrue(provenance['retrieved_at'].endswith('Z'))
        self.assertEqual(provenance['retrieved_at'][4], '-')
        self.assertEqual(record['stock_provenance_sha256'], editorial.digest(provenance))

        # A hotlink record carries no stored file and no provider secret.
        self.assertNotIn('local_path', record)
        self.assertNotIn('sha256', record)
        self.assertNotIn(SECRET_MARKER, json.dumps(record))
        self.assertNotIn(KEY, json.dumps(record))
        self.assertEqual(sorted(str(path) for path in root.rglob('*')), before)

        urls = self._urls()
        self.assertTrue(urls[0].startswith('https://api.unsplash.com/search/photos?'))
        self.assertIn('orientation=landscape', urls[0])
        self.assertIn('query=police+crime+economy', urls[0])
        self.assertEqual(urls[1], hotlink)
        self.assertEqual(urls[2], 'https://api.unsplash.com/photos/ABC123xyz/download')
        self.assertEqual(self.state['calls'][0][1]['Authorization'], 'Client-ID ' + KEY)
        self.assertEqual(self.state['calls'][0][1]['User-agent'], imagery.STOCK_USER_AGENT)
        self.assertEqual(self.state['calls'][1][1]['User-agent'], imagery.STOCK_USER_AGENT)
        self.assertNotIn('Authorization', self.state['calls'][1][1])

        # Redirect policy is a property of the credential, not of the host: the two API calls
        # refused all redirects, and only the uncredentialed image fetch could follow one.
        policies = self.state['handlers']
        self.assertEqual(len(policies), 3)
        self.assertIsInstance(policies[0], imagery._NoRedirects)
        self.assertIsInstance(policies[1], imagery._ExactHostRedirects)
        self.assertEqual(policies[1].host, imagery.UNSPLASH_IMAGE_HOST)
        self.assertIsInstance(policies[2], imagery._NoRedirects)
        self.assertEqual(policies[2].max_redirections, 0)

    def test_checkerboard_raster_verifies(self):
        facts = imagery.verify(_checkerboard_bytes())
        self.assertEqual(facts['width'], 900)
        self.assertEqual(facts['height'], 600)

    def test_repeat_selection_tracks_download_every_time(self):
        self._credentials()
        self._serve()
        first = imagery.fetch_unsplash(DRAFT)
        second = imagery.fetch_unsplash(DRAFT)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        tracking = [url for url in self._urls() if url.endswith('/download')]
        self.assertEqual(len(tracking), 2)
        self.assertIs(first['stock_provenance']['download_tracking']['successful'], True)
        self.assertIs(second['stock_provenance']['download_tracking']['successful'], True)

    def test_unrelated_photo_returns_none_and_grounded_subject_succeeds(self):
        self._credentials()

        # The historical failure: a place name alone must not justify a scenic photograph.
        self._serve(results=[_photo(description='snowy finnish landscape with pine trees')])
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertEqual(len(self._urls()), 1)

        # Metadata with no overlap at all is not relevance either.
        self._serve(results=[_photo(description='beach volleyball tournament at sunset')])
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

        # A grounded subject term still selects, and an unrelated photo cannot shadow it.
        self._serve(results=[
            _photo(description='snowy finnish landscape with pine trees'),
            _photo(photo_id='GOOD123xyz', description='a police car parked in the snow'),
        ])
        record = imagery.fetch_unsplash(DRAFT)
        self.assertIsNotNone(record)
        self.assertEqual(record['stock_provenance']['photo_id'], 'GOOD123xyz')

        subject_record = imagery.fetch_unsplash(DRAFT, subject='police patrol')
        self.assertIsNotNone(subject_record)
        self.assertEqual(subject_record['stock_provenance']['query'], 'police patrol')

    def test_describe_failure_keeps_verified_candidate(self):
        self._credentials()
        self._serve()
        with mock.patch.object(imagery, 'describe', side_effect=RuntimeError('vision down')):
            record = imagery.fetch_unsplash(DRAFT)
        self.assertIsNotNone(record)
        self.assertIsNone(record['depicted'])
        self.assertEqual(record['alt'], 'Arkistokuva aiheesta police crime economy')
        self.assertIs(record['stock_provenance']['download_tracking']['successful'], True)

    # -- Pexels ----------------------------------------------------------

    def _pexels_key(self):
        return mock.patch.dict(os.environ, {'PEXELS_API_KEY': KEY})

    def _pexels_quota_file(self):
        return self.tmp_path / 'cache' / 'uutistenlukija' / imagery.PEXELS_QUOTA_FILENAME

    def test_pexels_downloads_jpeg_and_records_content_hash(self):
        self._serve_pexels(image_bytes=_rgba_checkerboard_bytes())
        state_dir = self.tmp_path / 'news-state'
        with self._pexels_key():
            record = imagery.fetch_pexels(DRAFT, state_dir)

        self.assertIsNotNone(record)
        stored = state_dir / record['local_path']
        self.assertTrue(stored.is_file())
        content = stored.read_bytes()
        self.assertTrue(content.startswith(b'\xff\xd8'))
        self.assertEqual(record['sha256'], __import__('hashlib').sha256(content).hexdigest())
        self.assertEqual(record['url'], f'https://uutistenlukija.fi/{record["local_path"]}')
        self.assertEqual(record['caption'], imagery.STOCK_CAPTION)
        self.assertEqual(record['credit'], 'Photo by Matti Meikalainen on Pexels')
        self.assertEqual(record['license'], 'Pexels License')
        self.assertEqual(record['license_url'], 'https://www.pexels.com/license/')
        self.assertEqual(record['source_url'],
                         'https://www.pexels.com/photo/police-car-in-snow-123456/')
        self.assertIs(record['generated'], False)
        self.assertIs(record['hotlink'], False)
        self.assertNotIn('width', record)
        self.assertNotIn('height', record)
        self.assertEqual(record['pixels']['width'], 900)
        self.assertEqual(record['pixels']['height'], 600)
        self.assertEqual(record['pixels']['mode'], 'RGB')
        self.assertEqual(record['pixels'], imagery.verify(content))
        self.assertEqual(record['depicted'], 'a police car parked in the snow')

        provenance = record['stock_provenance']
        self.assertEqual(provenance, {
            'provider': 'pexels',
            'photo_id': '123456',
            'photographer': 'Matti Meikalainen',
            'photographer_url': 'https://www.pexels.com/@photographer',
            'photo_url': 'https://www.pexels.com/photo/police-car-in-snow-123456/',
            'query': 'police crime economy',
            'retrieved_at': provenance['retrieved_at'],
            'image_url': 'https://images.pexels.com/photos/123456/pexels-photo-123456.jpeg'
                         '?auto=compress&cs=tinysrgb&w=940',
        })
        self.assertEqual(record['stock_provenance_sha256'], editorial.digest(provenance))
        self.assertNotIn('download_tracking', provenance)
        self.assertNotIn(KEY, json.dumps(record))
        self.assertNotIn(SECRET_MARKER, json.dumps(record))

        urls = self._urls()
        self.assertTrue(urls[0].startswith('https://api.pexels.com/v1/search?'))
        self.assertIn('query=police+crime+economy', urls[0])
        self.assertIn('per_page=80', urls[0])
        self.assertIn('orientation=landscape', urls[0])
        self.assertEqual(urls[1], provenance['image_url'])
        self.assertNotIn('https://images.pexels.com/photos/123456/pexels-photo-123456.jpeg', urls)
        self.assertEqual(self.state['calls'][0][1]['Authorization'], KEY)
        self.assertEqual(self.state['calls'][0][1]['User-agent'], imagery.STOCK_USER_AGENT)
        self.assertEqual(self.state['calls'][1][1]['User-agent'], imagery.STOCK_USER_AGENT)
        self.assertNotIn('Authorization', self.state['calls'][1][1])

        quota = json.loads(self._pexels_quota_file().read_text(encoding='utf-8'))
        self.assertEqual(quota['version'], 1)
        self.assertEqual(len(quota['requests']), 1)
        self.assertNotIn(KEY, json.dumps(quota))

    def test_pexels_uses_large2x_when_large_is_absent(self):
        photo = _pexels_photo()
        photo['src'].pop('large')
        self._serve_pexels(results=[photo])
        state_dir = self.tmp_path / 'news-state'
        with self._pexels_key():
            record = imagery.fetch_pexels(DRAFT, state_dir)

        chosen = photo['src']['large2x']
        self.assertIsNotNone(record)
        self.assertEqual(record['stock_provenance']['image_url'], chosen)
        self.assertEqual(self._urls()[1:], [chosen])
        self.assertNotIn(photo['src']['original'], self._urls())

    def test_pexels_missing_large_variants_fails_closed(self):
        photo = _pexels_photo()
        photo['src'].pop('large')
        photo['src'].pop('large2x')
        self._serve_pexels(results=[photo])
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(len(self._urls()), 1)

    def test_pexels_wrong_host_on_chosen_large_url_is_refused(self):
        photo = _pexels_photo(
            large_url='https://images.pexels.com.evil.example/photos/123456/large.jpeg')
        self._serve_pexels(results=[photo])
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(len(self._urls()), 1)

    def test_pexels_empty_results_and_place_only_results_return_none(self):
        self._serve_pexels(results=[])
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(len(self._urls()), 1)

        self.state['calls'].clear()
        self._serve_pexels(results=[_pexels_photo(alt='snowy Finnish landscape with pine trees')])
        country_draft = {'title': 'Suomi', 'paragraphs': [{'text': 'Suomi.', 'source_ids': ['A']}]}
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(country_draft, self.tmp_path / 'state'))
        self.assertEqual(len(self._urls()), 1)

    def test_pexels_malformed_id_profile_photo_and_image_urls_are_refused(self):
        bad_items = [
            _pexels_photo(photo_id=0),
            _pexels_photo(photo_url='https://www.pexels.com/photos/police-car-123456/'),
            _pexels_photo(profile_url='https://www.pexels.com/photographer'),
            _pexels_photo(image_url='https://images.pexels.com.evil.example/photo.jpg'),
        ]
        for bad in bad_items:
            with self.subTest(bad=bad):
                self.state['calls'].clear()
                self._serve_pexels(results=[bad])
                with self._pexels_key():
                    self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
                self.assertEqual(len(self._urls()), 1)

    def test_pexels_quota_counts_failures_and_persists_across_calls(self):
        self._serve_pexels(search='http-error')
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self._serve_pexels(search='http-error')
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        quota = json.loads(self._pexels_quota_file().read_text(encoding='utf-8'))
        self.assertEqual(len(quota['requests']), 2)

        quota['requests'] = [time.time()] * imagery.PEXELS_QUOTA_LIMIT
        self._pexels_quota_file().write_text(json.dumps(quota), encoding='utf-8')
        self.state['calls'].clear()
        self._serve_pexels()
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(self._urls(), [])

    def test_pexels_quota_requires_exact_version_and_finite_times(self):
        valid = {'version': 1, 'requests': [100.0], 'blocked_until': 200.0}
        self.assertIsNotNone(imagery._quota_state(valid))
        malformed = [
            {'version': True, 'requests': [], 'blocked_until': 0.0},
            {'version': 1, 'requests': [], 'blocked_until': float('nan')},
            {'version': 1, 'requests': [], 'blocked_until': float('inf')},
            {'version': 1, 'requests': [], 'blocked_until': -1.0},
            {'version': 1, 'requests': [float('nan')], 'blocked_until': 0.0},
            {'version': 1, 'requests': [float('-inf')], 'blocked_until': 0.0},
            {'version': 1, 'requests': [-1.0], 'blocked_until': 0.0},
        ]
        for state in malformed:
            with self.subTest(state=state):
                self.assertIsNone(imagery._quota_state(state))

    def test_pexels_reservation_cap_persists_across_reservations(self):
        now = 1_700_000_000.0
        with mock.patch.object(imagery.time, 'time', return_value=now):
            reservations = [imagery._reserve_pexels_request()
                            for _ in range(imagery.PEXELS_QUOTA_LIMIT + 1)]
        self.assertEqual(sum(reservations), imagery.PEXELS_QUOTA_LIMIT)
        quota = json.loads(self._pexels_quota_file().read_text(encoding='utf-8'))
        self.assertEqual(len(quota['requests']), imagery.PEXELS_QUOTA_LIMIT)
        self.assertFalse(reservations[-1])

    def test_pexels_retry_after_http_date_is_honored(self):
        now = 1_700_000_000.0
        retry_at = now + 90
        with mock.patch.object(imagery.time, 'time', return_value=now):
            self.assertEqual(
                imagery._pexels_backoff_until({'Retry-After': formatdate(retry_at, usegmt=True)}),
                retry_at)

    def test_pexels_expired_reset_stays_an_expired_absolute_epoch(self):
        now = 1_700_000_000.0
        expired = now - 10
        with mock.patch.object(imagery.time, 'time', return_value=now):
            self.assertEqual(
                imagery._pexels_backoff_until({'X-Ratelimit-Reset': str(expired)}), expired)
            imagery._honor_pexels_429({'X-Ratelimit-Reset': str(expired)})
        quota = json.loads(self._pexels_quota_file().read_text(encoding='utf-8'))
        self.assertLessEqual(quota['blocked_until'], now)

    def test_pexels_bare_429_blocks_for_one_quota_window(self):
        now = 1_700_000_000.0
        self._serve_pexels(search='429-response', headers={})
        with mock.patch.object(imagery.time, 'time', return_value=now):
            with self._pexels_key():
                self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        quota = json.loads(self._pexels_quota_file().read_text(encoding='utf-8'))
        self.assertEqual(quota['blocked_until'], now + imagery.PEXELS_QUOTA_WINDOW)
        first_call_count = len(self._urls())

        self._serve_pexels()
        with mock.patch.object(imagery.time, 'time', return_value=now + 1):
            with self._pexels_key():
                self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(len(self._urls()), first_call_count)

    def test_pexels_429_retry_after_and_malformed_ledger_fail_closed(self):
        self._serve_pexels(search='429-response', headers={'Retry-After': '3600'})
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        first_call_count = len(self._urls())
        self._serve_pexels()
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(len(self._urls()), first_call_count)

        self._pexels_quota_file().write_text('{broken', encoding='utf-8')
        self.state['calls'].clear()
        with self._pexels_key():
            self.assertIsNone(imagery.fetch_pexels(DRAFT, self.tmp_path / 'state'))
        self.assertEqual(self._urls(), [])

    # -- failure paths ---------------------------------------------------

    def test_download_tracking_failure_returns_none(self):
        self._credentials()
        self._serve(download='http-error')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertEqual(len([url for url in self._urls() if url.endswith('/download')]), 1)

    def test_unusable_raster_returns_none(self):
        self._credentials()
        self._serve(image='not-an-image')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertFalse([url for url in self._urls() if url.endswith('/download')])

    def test_resizing_preserves_ixid_and_sets_one_cdn_size(self):
        self.assertEqual(
            imagery._hotlink(
                'https://images.unsplash.com/photo-1?w=4000&ixid=tracking-token&q=10&fm=webp'),
            'https://images.unsplash.com/photo-1?ixid=tracking-token&w=1536&q=80&fm=jpg&fit=crop')
        self.assertEqual(
            imagery._with_utm('https://unsplash.com/photos/ABC123xyz?foo=bar', 'unsplash.com'),
            'https://unsplash.com/photos/ABC123xyz'
            '?foo=bar&utm_source=uutistenlukija&utm_medium=referral')

    def test_malformed_or_malicious_payloads_return_none(self):
        self._credentials()
        self._serve(results=[
            _photo(urls={'raw': 'https://images.unsplash.com.evil.example/x.jpg'}),
            _photo(links={'html': 'https://unsplash.com.evil.example/photos/a',
                          'download_location': 'https://evil.example/download'}),
        ])
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

        self._serve(results=[_photo(links={'html': 'https://unsplash.com/photos/ABC123xyz',
                                           'download_location': 'https://evil.example/x'})])
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

        self._serve(results=['not a photo'])
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

        self._serve(results='not a list')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

    def test_credentialed_redirects_are_refused(self):
        self._credentials()

        # A same-host redirect is refused exactly like a foreign one: the Authorization header
        # would be replayed at whatever URL the response named.
        self._serve(search='redirect-same-host')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertEqual(len(self._urls()), 1)

        self._serve(search='redirect-off-host')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

        # The download-tracking GET is credentialed too, so it must refuse as well.
        self._serve(download='redirect-same-host')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertEqual(len([url for url in self._urls() if url.endswith('/download')]), 1)

        request = urllib.request.Request(
            'https://api.unsplash.com/photos/ABC123xyz/download',
            headers={'Authorization': 'Client-ID ' + KEY})
        refusal = imagery._NoRedirects()
        self.assertEqual(refusal.max_redirections, 0)
        self.assertIsNone(refusal.redirect_request(
            request, None, 302, 'Found', {}, 'https://api.unsplash.com/other'))
        self.assertIsNone(refusal.redirect_request(
            request, None, 302, 'Found', {}, 'https://api.unsplash.com/photos/ABC123xyz/download'))
        self.assertIsNone(refusal.redirect_request(
            request, None, 302, 'Found', {}, 'https://evil.example/steal'))

    def test_uncredentialed_image_redirect_allows_only_exact_cdn_host(self):
        # The image GET carries no credential, so a same-CDN redirect may be followed - but
        # still only to the exact provider image host.
        self._credentials()
        self._serve(image='redirect-off-host')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self.assertFalse([url for url in self._urls() if url.endswith('/download')])

        handler = imagery._ExactHostRedirects(imagery.UNSPLASH_IMAGE_HOST)
        request = urllib.request.Request('https://images.unsplash.com/photo-1?w=1080')
        followed = handler.redirect_request(
            request, None, 302, 'Found', {}, 'https://images.unsplash.com/photo-2?w=1080')
        self.assertIsNotNone(followed)
        self.assertEqual(urllib.parse.urlsplit(followed.full_url).hostname,
                         imagery.UNSPLASH_IMAGE_HOST)
        self.assertIsNone(handler.redirect_request(
            request, None, 302, 'Found', {}, 'https://images.unsplash.com.evil.example/x'))
        self.assertIsNone(handler.redirect_request(
            request, None, 302, 'Found', {}, 'https://evil.example/steal'))
        self.assertIsNone(handler.redirect_request(
            request, None, 302, 'Found', {}, 'http://images.unsplash.com/photo-2'))

    def test_non_dict_json_and_empty_results_return_none(self):
        self._credentials()
        self._serve(search='malformed')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self._serve(results=[])
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

    def test_credential_and_http_failures_are_silent(self):
        self._credentials(value=SECRET_MARKER)
        self._serve(search='http-error')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))
        self._serve(search='malformed')
        self.assertIsNone(imagery.fetch_unsplash(DRAFT))

    # -- query shaping and import safety ---------------------------------

    def test_stock_query_is_conservative(self):
        self.assertEqual(imagery.stock_query(DRAFT), 'police crime economy')
        self.assertEqual(imagery.stock_query({'title': 'Harvinaisia sanoja', 'paragraphs': []}), '')
        self.assertEqual(imagery.stock_query({}), '')
        self.assertEqual(imagery.stock_query(None), '')
        self.assertEqual(imagery.stock_query({'title': 'Suomi ja energia'}), 'finland energy')

    def test_no_key_at_import_time(self):
        self.assertIsNone(os.environ.get('UNSPLASH_ACCESS_KEY'))
        reloaded = importlib.reload(imagery)
        try:
            self.assertIsNone(reloaded.provider_key('unsplash', credential_root=self.tmp_path))
        finally:
            importlib.reload(imagery)


if __name__ == '__main__':
    unittest.main()
