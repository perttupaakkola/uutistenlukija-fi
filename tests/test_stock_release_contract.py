"""Isolated stock-image release contract tests."""
import copy
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
import unittest
from unittest.mock import patch

import test_release_v2 as base
from test_stock_imagery import _checkerboard_bytes

from cutover.check_release import check
from news_mvp import imagery
from news_mvp.editorial import digest
from news_mvp.publish import public_bundle, publish
from news_mvp.release_contract import (check_article, media, receipt_media, stock_binding,
                                       verify_intake)
from news_mvp.site import article_path
from news_mvp.store import database


CAPTION = 'Arkistokuva. Kuva ei esitä uutisen tapahtumaa.'
UTM = 'utm_source=uutistenlukija&utm_medium=referral'


class _ProviderResponse:
    def __init__(self, url, body):
        self._url = url
        self._body = body
        self.status = 200
        self.headers = {}

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def read(self, amount=-1):
        return self._body if amount is None or amount < 0 else self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _ProviderOpener:
    def __init__(self, serve):
        self.serve = serve

    def open(self, request, timeout=None):
        return self.serve(request.full_url, request)


class StockReleaseContract(unittest.TestCase):
    setUp = base.ReleaseV2.setUp
    source_fetch = base.ReleaseV2.source_fetch

    def unsplash_image(self):
        photo_id = 'stock-photo-123'
        photo_url = f'https://unsplash.com/photos/{photo_id}?{UTM}'
        provenance = {
            'provider': 'unsplash',
            'photo_id': photo_id,
            'photographer': 'Test Photographer',
            'photographer_url': f'https://unsplash.com/@test-photographer?{UTM}',
            'photo_url': photo_url,
            'query': 'Helsinki library',
            'retrieved_at': '2026-09-11T15:00:00Z',
            'image_url': 'https://images.unsplash.com/photo-stock-123?w=1200',
            'download_tracking': {
                'url': f'https://api.unsplash.com/photos/{photo_id}/download',
                'successful': True,
            },
        }
        return {
            'generated': False,
            'url': provenance['image_url'],
            'source_url': photo_url,
            'stock_provenance': provenance,
            'stock_provenance_sha256': digest(provenance),
            'alt': 'Arkistokuva Helsingistä',
            'caption': CAPTION,
            'credit': 'Photo by Test Photographer on Unsplash',
            'license': 'Unsplash License',
            'license_url': 'https://unsplash.com/license',
            'pixels': {
                'width': 1200,
                'height': 800,
                'mode': 'RGB',
                'variance': [120.0, 80.0, 160.0],
            },
            'depicted': None,
            'hotlink': True,
        }

    def pexels_image(self):
        photo_id = 54321
        photo_url = f'https://www.pexels.com/photo/test-library-photo-{photo_id}/'
        raw_sha = 'a' * 64
        provenance = {
            'provider': 'pexels',
            'photo_id': photo_id,
            'photographer': 'Test Photographer',
            'photographer_url': 'https://www.pexels.com/@test-photographer',
            'photo_url': photo_url,
            'query': 'Helsinki library',
            'retrieved_at': '2026-09-11T15:00:00+00:00',
            'image_url': 'https://images.pexels.com/photos/54321/pexels-photo-54321.jpeg',
        }
        return {
            'generated': False,
            'url': f'https://uutistenlukija.fi/media/{raw_sha}.jpg',
            'source_url': photo_url,
            'stock_provenance': provenance,
            'stock_provenance_sha256': digest(provenance),
            'alt': 'Arkistokuva Helsingistä',
            'caption': CAPTION,
            'credit': 'Photo by Test Photographer on Pexels',
            'license': 'Pexels License',
            'license_url': 'https://www.pexels.com/license/',
            'pixels': {
                'width': 1200,
                'height': 800,
                'mode': 'RGB',
                'variance': [120.0, 80.0, 160.0],
            },
            'depicted': 'a library interior',
            'local_path': f'media/{raw_sha}.jpg',
            'sha256': raw_sha,
            'hotlink': False,
        }

    def _fetch_provider_image(self, provider):
        query = imagery.stock_query(self.draft)
        self.assertEqual(query, 'book')
        raster = _checkerboard_bytes()
        unsplash_item = {
            'id': 'library123',
            'alt_description': 'a library interior with a book',
            'urls': {'raw': 'https://images.unsplash.com/photo-library123?ixid=stock'},
            'links': {
                'html': 'https://unsplash.com/photos/library123',
                'download_location': 'https://api.unsplash.com/photos/library123/download',
            },
            'user': {
                'name': 'Test Photographer',
                'links': {'html': 'https://unsplash.com/@test-photographer'},
            },
        }
        pexels_item = {
            'id': 54321,
            'url': 'https://www.pexels.com/photo/test-library-photo-54321/',
            'photographer': 'Test Photographer',
            'photographer_url': 'https://www.pexels.com/@test-photographer',
            'alt': 'a library interior with a book',
            'src': {
                'large': (
                    'https://images.pexels.com/photos/54321/'
                    'pexels-photo-54321.jpeg?auto=compress&cs=tinysrgb&w=940'
                ),
                'large2x': (
                    'https://images.pexels.com/photos/54321/'
                    'pexels-photo-54321.jpeg?auto=compress&cs=tinysrgb&w=1880'
                ),
                'original': 'https://images.pexels.com/photos/54321/pexels-photo-54321.jpeg',
            },
        }

        def serve(url, _request):
            parsed = urllib.parse.urlsplit(url)
            if parsed.hostname == imagery.UNSPLASH_API_HOST:
                if parsed.path == '/search/photos' and provider == 'unsplash':
                    self.assertEqual(urllib.parse.parse_qs(parsed.query)['query'], [query])
                    return _ProviderResponse(url, json.dumps({'results': [unsplash_item]}).encode())
                if parsed.path == '/photos/library123/download' and provider == 'unsplash':
                    return _ProviderResponse(url, b'{}')
            if parsed.hostname == imagery.PEXELS_API_HOST and parsed.path == '/v1/search' and provider == 'pexels':
                self.assertEqual(urllib.parse.parse_qs(parsed.query)['query'], [query])
                return _ProviderResponse(url, json.dumps({'photos': [pexels_item]}).encode())
            if parsed.hostname == imagery.UNSPLASH_IMAGE_HOST and provider == 'unsplash':
                return _ProviderResponse(url, raster)
            if parsed.hostname == imagery.PEXELS_IMAGE_HOST and provider == 'pexels':
                self.assertEqual(url, pexels_item['src']['large'])
                return _ProviderResponse(url, raster)
            raise AssertionError(f'unexpected mocked provider URL: {url}')

        opener = lambda *_handlers: _ProviderOpener(serve)
        env = {
            'UNSPLASH_ACCESS_KEY': 'mock-unsplash-key',
            'PEXELS_API_KEY': 'mock-pexels-key',
            'PEXELS_CACHE_DIR': str(self.state / 'pexels-cache'),
        }
        with patch.dict(os.environ, env), \
                patch.object(imagery, 'describe', return_value='a library interior'), \
                patch.object(urllib.request, 'build_opener', side_effect=opener):
            image = (imagery.fetch_unsplash(self.draft) if provider == 'unsplash' else
                     imagery.fetch_pexels(self.draft, self.state))
        self.assertIsNotNone(image)
        self.assertEqual(image['stock_provenance']['query'], query)
        if provider == 'pexels':
            self.assertEqual(image['stock_provenance']['image_url'], pexels_item['src']['large'])
        self.assertEqual(image['pixels']['width'], 900)
        self.assertEqual(image['pixels']['height'], 600)
        return image

    def helper_unsplash_image(self):
        return self._fetch_provider_image('unsplash')

    def helper_pexels_image(self):
        return self._fetch_provider_image('pexels')

    def official_with(self, image):
        packet = copy.deepcopy(self.packet)
        packet.pop('image_note', None)
        packet['image'] = copy.deepcopy(image)
        draft = copy.deepcopy(self.draft)
        draft['image'] = copy.deepcopy(image)
        return packet, draft

    def receipt_for(self, packet, draft):
        binding = media(packet, draft)
        receipt = {
            'schema_version': 2,
            'packet': packet,
            'draft': draft,
            'review': {
                'approved': True,
                'draft_sha256': digest(draft),
                'reasons': ['Stock contract fixture'],
            },
            'packet_sha256': digest(packet),
            'draft_sha256': digest(draft),
            'image_sha256': binding['image_sha256'],
        }
        for field in ('text_only', 'stock_image'):
            if field in binding:
                receipt[field] = binding[field]
        return receipt

    def render_public_stock(self, image):
        packet, draft = self.official_with(image)
        verify_intake(packet, self.state)
        job = base.ReleaseV2.ready(self, packet, draft)
        with database(self.state) as store, patch('news_mvp.publish.cmd', return_value=base.COMMIT):
            site, receipt = public_bundle(store, job, self.state)
        check(site, receipt)
        article = (site / article_path(job) / 'index.html').read_text()
        home = (site / 'index.html').read_text()
        return packet, draft, job, site, receipt, article, home

    def assert_positive_publish_readback(self, job, expected_image):
        calls = []
        shell = base.ReleaseV2.shell(self, calls)
        with database(self.state) as store, patch('news_mvp.publish.cmd', side_effect=shell), \
                patch('news_mvp.publish.api', return_value={'object': {'sha': base.REMOTE}}), \
                patch('news_mvp.publish.make_commit', return_value=base.REMOTE), \
                patch('news_mvp.publish.matching_runs', return_value=[]):
            self.assertEqual(publish(store, job, self.state, self.cfg)['status'], 'dispatched')
        receipt = json.loads((self.state / 'release.json').read_text())
        record = base.ReleaseV2.workflow(self, receipt)
        self.assertEqual(record['stock_image'], expected_image)
        deployment = self.state / 'deployments' / '123'
        deployment.mkdir(parents=True, exist_ok=True)
        (deployment / 'live-deployment.json').write_text(json.dumps(record))

        def read(request, **_kwargs):
            url = request.full_url
            relative = url.removeprefix('https://uutistenlukija.fi/')
            path = self.state / 'live-site' / relative
            if url.endswith('/'):
                path /= 'index.html'
            return io.BytesIO(path.read_bytes())

        with database(self.state) as store, patch('news_mvp.publish.cmd', side_effect=shell), \
                patch('news_mvp.publish.api', return_value={'object': {'sha': base.REMOTE}}), \
                patch('news_mvp.publish.matching_runs',
                      return_value=[{'databaseId': 123, 'status': 'completed',
                                     'conclusion': 'success'}]), \
                patch('urllib.request.urlopen', side_effect=read):
            self.assertEqual(publish(store, job, self.state, self.cfg)['status'], 'deployed')
        readback = json.loads((deployment / 'live-readback.json').read_text())
        self.assertEqual(readback['stock_image'], expected_image)
        self.assertEqual(readback['live_image_sha256'],
                         receipt_media(receipt)['image_sha256'])

    def test_valid_unsplash_media_and_receipt_binding(self):
        packet, draft = self.official_with(self.unsplash_image())
        binding = media(packet, draft)
        self.assertIsNone(binding['image_sha256'])
        self.assertEqual(binding['stock_image'], draft['image'])
        self.assertEqual(receipt_media(self.receipt_for(packet, draft))['stock_image'], draft['image'])

    def test_valid_pexels_media_keeps_local_sha_and_receipt_binding(self):
        packet, draft = self.official_with(self.pexels_image())
        binding = media(packet, draft)
        self.assertEqual(binding['image_sha256'], draft['image']['sha256'])
        self.assertEqual(binding['stock_image'], draft['image'])
        self.assertEqual(receipt_media(self.receipt_for(packet, draft)), binding)

    def test_commons_work_title_and_jpeg_notice_survive_bundle_and_readback(self):
        local = self.helper_pexels_image()
        decision = {'subject':self.draft['title'], 'depictable_scene':'Library book shelves',
            'must_show':['book'], 'must_avoid':['people'],
            'search_queries':['library book','reading book','book shelves'],
            'category':self.draft['category']}
        candidate = {'photo_id':'wikimedia-1234','photo_page':'https://commons.wikimedia.org/wiki/File:Library.jpg',
            'profile':'https://commons.wikimedia.org/wiki/User:Photographer','name':'Test Photographer',
            'image_url':'https://upload.wikimedia.org/wikipedia/commons/a/ab/Library.jpg',
            'title':'Library shelves (archive)', 'license':'CC BY-SA 3.0',
            'attribution_credit':'Helsingin kaupunginmuseo',
            'license_url':'https://creativecommons.org/licenses/by-sa/3.0/'}
        image = imagery._open_source_record('wikimedia',candidate,'library book',self.state,
            local['pixels'],local['sha256'],local['local_path'],'Library book shelves',decision,
            imagery.relevance_check('Library book shelves',decision),'2026-09-26T00:00:00Z')
        packet,draft,job,root,receipt,article,home = self.render_public_stock(image)
        notice = image['stock_provenance']['attribution']
        self.assertIn(notice['title'],article)
        self.assertIn(notice['changes'],article)
        self.assertIn(notice['source_credit'],article)
        self.assertNotIn(notice['changes'],home)
        for field in ('title','changes','source_credit'):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'title/change notice'):
                    check_article(article.replace(notice[field],''),packet,draft)
                if field in ('title','changes'):
                    changed=copy.deepcopy(image)
                    del changed['stock_provenance']['attribution'][field]
                    changed['stock_provenance_sha256']=digest(changed['stock_provenance'])
                    with self.assertRaisesRegex(ValueError,'attribution notice'):stock_binding(changed)

    def test_mocked_provider_output_renders_full_unsplash_release_and_readback(self):
        image = self.helper_unsplash_image()
        packet, draft, job, site, receipt, article, home = self.render_public_stock(image)
        escaped_url = image['url'].replace('&', '&amp;')
        self.assertEqual(receipt_media(receipt)['stock_image'], image)
        self.assertIn(f'<img src="{escaped_url}"', article)
        self.assertIn(f'<meta property="og:image" content="{escaped_url}">', article)
        self.assertIn(f'<img src="{escaped_url}"', home)
        self.assertIn(f'<meta property="og:image" content="{escaped_url}">', home)
        self.assertEqual(article.count('>Arkistokuva</span>'), 1)
        self.assertIn('image-rights', article)
        self.assertNotIn('<figcaption', article)
        record = base.ReleaseV2.workflow(self, receipt)
        self.assertEqual(record['stock_image'], image)
        check_article(article, packet, draft, canonical='https://uutistenlukija.fi/' + article_path(job))
        self.assert_positive_publish_readback(job, image)

    def test_mocked_pexels_output_copies_verified_local_bytes_and_rejects_corruption(self):
        image = self.helper_pexels_image()
        _packet, _draft, _job, site, receipt, article, home = self.render_public_stock(image)
        self.assertEqual(receipt['image_sha256'], image['sha256'])
        self.assertIn(f'<img src="/mvp-assets/{image["sha256"]}.jpg"', article)
        self.assertIn(f'<img src="/mvp-assets/{image["sha256"]}.jpg"', home)
        self.assertNotIn('images.pexels.com', article)
        stored = (site / f'mvp-assets/{image["sha256"]}.jpg').read_bytes()
        self.assertTrue(stored.startswith(b'\xff\xd8'))
        self.assertEqual(hashlib.sha256(stored).hexdigest(), image['sha256'])
        self.assert_positive_publish_readback(_job, image)
        (self.state / image['local_path']).write_bytes(b'corrupted-local-copy')
        with database(self.state) as store, patch('news_mvp.publish.cmd', return_value=base.COMMIT):
            with self.assertRaises(ValueError):
                public_bundle(store, _job, self.state)

    def test_stock_markup_mutations_and_missing_binding_are_rejected(self):
        image = self.helper_unsplash_image()
        packet, draft, job, _site, _receipt, article, _home = self.render_public_stock(image)
        mutations = {
            'missing stock binding': (
                article,
                {**draft, 'image': {key: value for key, value in draft['image'].items()
                                   if key not in ('stock_provenance', 'stock_provenance_sha256')}},
            ),
            'foreign image URL': (
                article.replace(f'src="{image["url"].replace("&", "&amp;")}"',
                                'src="https://evil.example/foreign.jpg"', 1),
                draft,
            ),
            'tracking URL mutation': (
                article.replace('utm_source=uutistenlukija&amp;utm_medium=referral',
                                'utm_source=wrong&amp;utm_medium=referral', 1),
                draft,
            ),
            'license URL mutation': (
                article.replace('href="https://unsplash.com/license"',
                                'href="https://evil.example/license"', 1),
                draft,
            ),
            'duplicate image attribute': (
                article.replace(f'<img src="{image["url"].replace("&", "&amp;")}"',
                                f'<img src="{image["url"].replace("&", "&amp;")}" '
                                f'src="{image["url"].replace("&", "&amp;")}"', 1),
                draft,
            ),
            'hidden credit attribute': (
                article.replace('<span class="portal-lead__credit">',
                                '<span class="portal-lead__credit" hidden>', 1),
                draft,
            ),
            'hidden label style': (
                article.replace('<span class="portal-lead__image-label">',
                                '<span class="portal-lead__image-label" style="display:none">', 1),
                draft,
            ),
            'hidden rights section': (
                article.replace('<section class="image-rights">',
                                '<section class="image-rights" hidden>', 1),
                draft,
            ),
            'hidden credit ancestor': (
                article.replace('<span class="portal-lead__credit">',
                                '<span aria-hidden="true"><span class="portal-lead__credit">', 1)
                .replace('</span></figure>', '</span></span></figure>', 1),
                draft,
            ),
            'visually hidden label': (
                article.replace('<span class="portal-lead__image-label">',
                                '<span class="portal-lead__image-label visually-hidden">', 1),
                draft,
            ),
            'collapsed credit': (
                article.replace('<span class="portal-lead__credit">',
                                '<span class="portal-lead__credit" style="visibility:collapse">', 1),
                draft,
            ),
        }
        profile = image['stock_provenance']['photographer_url'].replace('&', '&amp;')
        wrong_profile = article.replace(f'href="{profile}"',
                                        'href="https://example.org/wrong"', 1)
        mutations['wrong visible credit plus empty expected link'] = (
            wrong_profile.replace('</figure>', f'<a href="{profile}"></a></figure>', 1), draft)
        for label, (html, candidate) in mutations.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                check_article(html, packet, candidate,
                              canonical='https://uutistenlukija.fi/' + article_path(job))

        nested_label = article.replace(
            '<span class="portal-lead__image-label">Arkistokuva</span>',
            '<span class="portal-lead__image-label"><span><span>Arkistokuva</span></span></span>',
            1)
        check_article(nested_label, packet, draft,
                      canonical='https://uutistenlukija.fi/' + article_path(job))

    def test_captured_source_tamper_full_manifest_and_compatibility_paths(self):
        packet, draft, _job, site, receipt, _article, _home = self.render_public_stock(
            self.helper_unsplash_image())
        self.assertTrue(receipt['files'])
        self.assertEqual(receipt_media(receipt)['stock_image'], draft['image'])
        source_path = self.state / 'intake' / digest(self.packet) / 'source.html'
        source_path.write_bytes(source_path.read_bytes() + b'tampered')
        with self.assertRaises(ValueError):
            verify_intake(packet, self.state)
        source_path.write_bytes(self.raw)

        compatibility = base.ReleaseV2()
        compatibility.setUp()
        self.addCleanup(compatibility.doCleanups)
        text_job = base.ReleaseV2.ready(compatibility)
        with database(compatibility.state) as store, patch('news_mvp.publish.cmd', return_value=base.COMMIT):
            text_site, text_receipt = public_bundle(store, text_job, compatibility.state)
        check(text_site, text_receipt)
        self.assertNotIn('stock_image', text_receipt)

        generated = {
            'url': '', 'source_url': 'https://uutistenlukija.fi/ai-kuvat/',
            'license_url': 'https://uutistenlukija.fi/ai-kuvat/',
            'license': 'AI-generated illustration', 'alt': 'AI-generoitu kuva: Kirjoja kirjaston hyllyillä.',
            'caption': 'AI-generoitu kuva. Ei valokuva tapahtumasta.',
            'credit': 'AI-kuvitus', 'sha256': '', 'local_path': '',
            'generated': True, 'model': 'gpt-image-1-mini', 'prompt_sha256': 'b' * 64,
            'prompt_version': 'imagery-v1', 'subject': 'Esimerkki',
        }
        raw = b'generated-fallback-bytes'
        generated['sha256'] = hashlib.sha256(raw).hexdigest()
        generated['url'] = 'https://uutistenlukija.fi/media/' + generated['sha256'] + '.jpg'
        generated['local_path'] = 'media/' + generated['sha256'] + '.jpg'
        generated_case = base.ReleaseV2()
        generated_case.setUp()
        self.addCleanup(generated_case.doCleanups)
        generated_packet = copy.deepcopy(generated_case.packet)
        generated_packet.pop('image_note', None)
        generated_packet['image'] = copy.deepcopy(generated)
        generated_draft = copy.deepcopy(generated_case.draft)
        generated_draft['image'] = copy.deepcopy(generated)
        generated_job = base.ReleaseV2.ready(generated_case, generated_packet, generated_draft)
        path = generated_case.state / generated['local_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        with database(generated_case.state) as store, patch('news_mvp.publish.cmd', return_value=base.COMMIT):
            generated_site, generated_receipt = public_bundle(store, generated_job, generated_case.state)
        check(generated_site, generated_receipt)

    def test_publish_readback_rejects_missing_or_unexpected_stock_binding(self):
        for mutation in ('missing', 'unexpected'):
            with self.subTest(mutation=mutation):
                case = base.ReleaseV2()
                case.setUp()
                self.addCleanup(case.doCleanups)
                image = self.helper_unsplash_image()
                packet, draft = StockReleaseContract.official_with(case, image)
                job = base.ReleaseV2.ready(case, packet, draft)
                calls = []
                shell = base.ReleaseV2.shell(case, calls)
                with database(case.state) as store, patch('news_mvp.publish.cmd', side_effect=shell), \
                        patch('news_mvp.publish.api', return_value={'object': {'sha': base.REMOTE}}), \
                        patch('news_mvp.publish.make_commit', return_value=base.REMOTE), \
                        patch('news_mvp.publish.matching_runs', return_value=[]):
                    self.assertEqual(publish(store, job, case.state, case.cfg)['status'], 'dispatched')
                receipt = json.loads((case.state / 'release.json').read_text())
                record = base.ReleaseV2.workflow(case, receipt)
                if mutation == 'missing':
                    record.pop('stock_image')
                else:
                    record['stock_image'] = None
                deployment = case.state / 'deployments' / '123'
                deployment.mkdir(parents=True, exist_ok=True)
                (deployment / 'live-deployment.json').write_text(json.dumps(record))

                def read(request, **_kwargs):
                    url = request.full_url
                    relative = url.removeprefix('https://uutistenlukija.fi/')
                    path = case.state / 'live-site' / relative
                    return io.BytesIO((path / 'index.html').read_bytes() if url.endswith('/')
                                      else path.read_bytes())

                with database(case.state) as store, patch('news_mvp.publish.cmd', side_effect=shell), \
                        patch('news_mvp.publish.api', return_value={'object': {'sha': base.REMOTE}}), \
                        patch('news_mvp.publish.matching_runs',
                              return_value=[{'databaseId': 123, 'status': 'completed',
                                             'conclusion': 'success'}]), \
                        patch('urllib.request.urlopen', side_effect=read):
                    with self.assertRaises(ValueError):
                        publish(store, job, case.state, case.cfg)

    def test_publish_readback_rejects_unexpected_stock_image_on_text_release(self):
        case = base.ReleaseV2()
        case.setUp()
        self.addCleanup(case.doCleanups)
        job = base.ReleaseV2.ready(case)
        calls = []
        shell = base.ReleaseV2.shell(case, calls)
        with database(case.state) as store, patch('news_mvp.publish.cmd', side_effect=shell), \
                patch('news_mvp.publish.api', return_value={'object': {'sha': base.REMOTE}}), \
                patch('news_mvp.publish.make_commit', return_value=base.REMOTE), \
                patch('news_mvp.publish.matching_runs', return_value=[]):
            self.assertEqual(publish(store, job, case.state, case.cfg)['status'], 'dispatched')
        receipt = json.loads((case.state / 'release.json').read_text())
        record = base.ReleaseV2.workflow(case, receipt)
        record['stock_image'] = self.unsplash_image()
        deployment = case.state / 'deployments' / '123'
        deployment.mkdir(parents=True, exist_ok=True)
        (deployment / 'live-deployment.json').write_text(json.dumps(record))
        with database(case.state) as store, patch('news_mvp.publish.cmd', side_effect=shell), \
                patch('news_mvp.publish.api', return_value={'object': {'sha': base.REMOTE}}), \
                patch('news_mvp.publish.matching_runs',
                      return_value=[{'databaseId': 123, 'status': 'completed',
                                     'conclusion': 'success'}]):
            with self.assertRaises(ValueError):
                publish(store, job, case.state, case.cfg)

    def test_nonstock_official_photo_is_rejected(self):
        image = self.pexels_image()
        image.pop('stock_provenance')
        image.pop('stock_provenance_sha256')
        packet, draft = self.official_with(image)
        with self.assertRaises(ValueError):
            media(packet, draft)

    def test_stock_binding_rejects_schema_identity_tracking_and_rights_mutations(self):
        mutations = []

        image = self.unsplash_image()
        bad = copy.deepcopy(image)
        bad['stock_provenance']['photographer_url'] = 'https://evil.example/@test?' + UTM
        mutations.append(('host', bad))

        bad = copy.deepcopy(image)
        bad['stock_provenance'].pop('download_tracking')
        mutations.append(('tracking', bad))

        bad = copy.deepcopy(image)
        bad['stock_provenance']['photo_id'] = 'other-photo'
        mutations.append(('identity', bad))

        bad = copy.deepcopy(image)
        bad['stock_provenance_sha256'] = '0' * 64
        mutations.append(('hash', bad))

        bad = copy.deepcopy(image)
        bad['credit'] = 'Photo by Someone Else on Unsplash'
        mutations.append(('credit', bad))

        bad = copy.deepcopy(image)
        bad['source_url'] = 'https://unsplash.com/photos/other-photo?' + UTM
        mutations.append(('url', bad))

        bad = copy.deepcopy(image)
        bad['license'] = 'Unknown license'
        mutations.append(('license', bad))

        bad = copy.deepcopy(image)
        bad.pop('pixels')
        bad['width'] = 1200
        bad['height'] = 800
        mutations.append(('top-level dimensions', bad))

        bad = copy.deepcopy(image)
        bad['pixels']['width'] = True
        mutations.append(('malformed pixels', bad))

        bad = copy.deepcopy(image)
        bad['stock_provenance']['photo_id'] = 'short'
        mutations.append(('malformed photo id', bad))

        bad = copy.deepcopy(image)
        bad['stock_provenance']['photographer_url'] = (
            'https://unsplash.com/@test-photographer?'
            'utm_source=uutistenlukija&utm_source=uutistenlukija&utm_medium=referral'
        )
        mutations.append(('duplicate UTM', bad))

        for label, candidate in mutations:
            with self.subTest(label=label), self.assertRaises(ValueError):
                stock_binding(candidate)

    def test_pexels_local_file_binding_and_receipt_downgrade_are_rejected(self):
        image = self.pexels_image()
        bad = copy.deepcopy(image)
        bad['local_path'] = 'media/' + 'b' * 64 + '.jpg'
        with self.assertRaises(ValueError):
            stock_binding(bad)

        packet, draft = self.official_with(image)
        receipt = self.receipt_for(packet, draft)
        receipt.pop('stock_image')
        with self.assertRaises(ValueError):
            receipt_media(receipt)

        receipt = self.receipt_for(packet, draft)
        receipt['stock_image']['provider'] = 'foreign'
        with self.assertRaises(ValueError):
            receipt_media(receipt)

    def test_stock_original_intake_projection_rejects_changed_text_and_rights(self):
        packet, _ = self.official_with(self.unsplash_image())
        verify_intake(packet, self.state)

        changed_text = copy.deepcopy(packet)
        changed_text['sources'][0]['text'] += ' changed'
        with self.assertRaises(ValueError):
            verify_intake(changed_text, self.state)

        changed_rights = copy.deepcopy(packet)
        changed_rights['supporting_documents'][0]['text'] += ' changed'
        with self.assertRaises(ValueError):
            verify_intake(changed_rights, self.state)


if __name__ == '__main__':
    unittest.main()
