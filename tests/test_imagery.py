"""Article imagery: provider chain, generation fallback, and independent raster verification.

Stock candidates are independently relevant and verified before generation is attempted; the
generation fallback is still constructed from a fact the reviewed draft already states. The
canonical predecessor failure (commit 9318ea23c) illustrated a story about cocaine in Finnish
wastewater with "scenic aerial view of snowy Finnish landscape", accepted because "metadata
matches finnish, landscape".

These tests cover the two properties that made the old approach unsafe: (1) no image is
produced for subjects that would invite depicting real people, tragedy or violence, and
(2) a provider payload is never trusted as evidence of what it depicts.
"""

import io
import tempfile
import unittest
from unittest import mock


class SubjectDerivation(unittest.TestCase):
    def _subject(self, title, body='Lähde kertoo asiasta.'):
        from news_mvp.imagery import subject_from_draft
        return subject_from_draft({'title': title, 'paragraphs': [{'text': body, 'source_ids': ['A']}]})

    def test_ordinary_civic_story_is_illustratable(self):
        self.assertIsNotNone(self._subject('Kuopio kokeili koulunkäyntiä väestönsuojassa'))

    def test_named_person_is_refused(self):
        """A generated photograph of a real, named individual is not ours to produce."""
        self.assertIsNone(self._subject('Presidentti Stubb vierailee Saksassa'))

    def test_minister_is_refused(self):
        self.assertIsNone(self._subject('Ministeri Tavio vierailee Virossa'))

    def test_tragedy_is_refused_for_every_inflection(self):
        """Finnish inflects heavily: matching only nominative forms let tragedy through."""
        for title in ('Onnettomuudessa kuoli kaksi ihmistä',
                      'Kaksi kuoli rajussa turmassa',
                      'Turma vaati kaksi uhria',
                      'Mies menehtyi sairauskohtauksen jälkeen',
                      'Mies tuomittiin murhasta'):
            with self.subTest(title=title):
                self.assertIsNone(self._subject(title))

    def test_ordinary_words_do_not_trip_the_safety_filter(self):
        """Over-blocking silently removes images from legitimate stories."""
        for title in ('Kuntaliitto julkaisi materiaalipaketin häiriötilanteisiin',
                      'Uusi päällikkö Münchenin konsulaattiin',
                      'Etelä-Koivurinteeseen suunnitellaan uusia asuntoja'):
            with self.subTest(title=title):
                self.assertIsNotNone(self._subject(title))

    def test_empty_title_is_refused(self):
        self.assertIsNone(self._subject(''))


class PromptConstruction(unittest.TestCase):
    def test_prompt_forbids_text_and_identifiable_people(self):
        from news_mvp.imagery import _prompt_for
        prompt = _prompt_for('Koulunkäyntiä väestönsuojassa', 'Kotimaa').lower()
        self.assertIn('no text', prompt)
        self.assertIn('no watermarks', prompt)
        self.assertIn('no recognisable faces', prompt)

    def test_prompt_avoids_invented_context_props(self):
        """A face mask appeared in a school-shelter generation, asserting a pandemic the
        article never mentioned."""
        from news_mvp.imagery import _prompt_for
        prompt = _prompt_for('Koulunkäyntiä väestönsuojassa', 'Kotimaa').lower()
        self.assertIn('avoid face masks', prompt)
        self.assertIn('era-specific', prompt)

    def test_prompt_is_bounded(self):
        from news_mvp.imagery import _prompt_for, MAX_PROMPT_CHARS
        self.assertLessEqual(len(_prompt_for('x' * 5000)), MAX_PROMPT_CHARS)


class RasterVerification(unittest.TestCase):
    """The provider payload is never evidence. Only the decoded raster is."""

    def _png(self, size=(800, 600), colour=(120, 140, 160), pattern=False):
        from PIL import Image
        image = Image.new('RGB', size, colour)
        if pattern:
            # A realistic pattern: large blocks of contrasting colour survive the 32x32
            # downscale that the blank-image check performs.
            for index, x in enumerate(range(0, size[0], size[0] // 4)):
                for y in range(0, size[1], size[1] // 4):
                    shade = (40, 90, 200) if (index + y) % 2 else (230, 210, 120)
                    for dx in range(size[0] // 4):
                        for dy in range(size[1] // 4):
                            image.putpixel(((x + dx) % size[0], (y + dy) % size[1]), shade)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

    def test_blank_raster_is_rejected(self):
        """A flat image carries no illustration; publishing it would be worse than no image."""
        from news_mvp.imagery import verify, GenerationError
        with self.assertRaises(GenerationError):
            verify(self._png())

    def test_structured_raster_is_accepted(self):
        from news_mvp.imagery import verify
        facts = verify(self._png(pattern=True))
        self.assertEqual((facts['width'], facts['height']), (800, 600))

    def test_tiny_raster_is_rejected(self):
        from news_mvp.imagery import verify, GenerationError
        with self.assertRaises(GenerationError):
            verify(self._png(size=(120, 90), pattern=True))

    def test_wrong_aspect_ratio_is_rejected(self):
        from news_mvp.imagery import verify, GenerationError
        with self.assertRaises(GenerationError):
            verify(self._png(size=(1200, 400), pattern=True), expect_ratio=1.5)

    def test_undecodable_payload_is_rejected(self):
        from news_mvp.imagery import verify, GenerationError
        with self.assertRaises(GenerationError):
            verify(b'not an image at all')


class LegibleTextRejection(unittest.TestCase):
    """Observed on a police story: the model wrote 'POLIIISI' across an officer's back, and on
    another attempt put legible lettering on a police car. The prompt forbids text; the model
    still produces it, so the output is checked."""

    def setUp(self):
        # Generation behavior is isolated from optional stock providers. Dedicated stock tests
        # mock their transports explicitly, so these tests never read runtime credentials.
        self._unsplash = mock.patch('news_mvp.imagery.fetch_unsplash', return_value=None)
        self._pexels = mock.patch('news_mvp.imagery.fetch_pexels', return_value=None)
        self._unsplash.start()
        self._pexels.start()
        self.addCleanup(self._unsplash.stop)
        self.addCleanup(self._pexels.stop)

    def test_reported_text_is_flagged(self):
        from news_mvp.imagery import has_legible_text
        for description in ('The image shows a police car with legible text on the door.',
                            'A street with visible text on a sign.',
                            'An officer with lettering on the back of his jacket.',
                            'The sign reads POLIISI.',
                            'The image contains a logo on the wall.'):
            with self.subTest(description=description):
                self.assertTrue(has_legible_text(description))

    def test_quoted_word_is_flagged(self):
        """Real phrasing that slipped past a first version matching only 'legible text'."""
        from news_mvp.imagery import has_legible_text
        self.assertTrue(has_legible_text(
            'The image shows a police officer in a uniform with the word "POLIISI" on the back, '
            'standing on a street with a drone in front of him.'))

    def test_explicit_absence_of_text_is_not_flagged(self):
        from news_mvp.imagery import has_legible_text
        for description in ('The image shows a police officer standing on a street. '
                            'There is no legible text or identifiable person.',
                            'A drone hovers above an empty street with no text visible.'):
            with self.subTest(description=description):
                self.assertFalse(has_legible_text(description))

    def test_missing_description_is_not_flagged(self):
        """The checker is best effort; a missing description must not block an image."""
        from news_mvp.imagery import has_legible_text
        self.assertFalse(has_legible_text(None))
        self.assertFalse(has_legible_text(''))

    def test_build_image_retries_past_a_texty_candidate(self):
        import news_mvp.imagery as imagery
        draft = {'title': 'Hallitus esittää poliisille laajempia valtuuksia',
                 'paragraphs': [{'text': 'Lakiesitys laajentaisi valtuuksia.', 'source_ids': ['A']}]}
        good = _structured_png()
        calls = {'n': 0}

        def fake_generate(*args, **kwargs):
            calls['n'] += 1
            return good, 'prompt', 'fake-model'

        descriptions = iter(['The image shows legible text on a police car.', 'A street.'])

        original_generate = imagery.generate
        original_describe = imagery.describe
        imagery.generate = fake_generate
        imagery.describe = lambda raw: next(descriptions)
        try:
            import tempfile
            result = imagery.build_image(draft, tempfile.mkdtemp())
        finally:
            imagery.generate = original_generate
            imagery.describe = original_describe
        self.assertIsNotNone(result, 'a clean retry must be accepted')
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(calls['n'], 2)

    def test_build_image_gives_up_when_every_candidate_has_text(self):
        import news_mvp.imagery as imagery
        draft = {'title': 'Hallitus esittää poliisille laajempia valtuuksia',
                 'paragraphs': [{'text': 'Lakiesitys laajentaisi valtuuksia.', 'source_ids': ['A']}]}
        good = _structured_png()

        original_generate = imagery.generate
        original_describe = imagery.describe
        imagery.generate = lambda *a, **k: (good, 'prompt', 'fake-model')
        imagery.describe = lambda raw: 'The image shows legible text on a police car.'
        try:
            import tempfile
            result = imagery.build_image(draft, tempfile.mkdtemp(), attempts=2)
        finally:
            imagery.generate = original_generate
            imagery.describe = original_describe
        self.assertIsNone(result, 'text must never ship, even at the cost of no image')


def _structured_png(size=(800, 600)):
    """A non-blank raster that passes verify()."""
    from PIL import Image
    image = Image.new('RGB', size, (120, 140, 160))
    for index, x in enumerate(range(0, size[0], size[0] // 4)):
        for y in range(0, size[1], size[1] // 4):
            shade = (40, 90, 200) if (index + y) % 2 else (230, 210, 120)
            for dx in range(size[0] // 4):
                for dy in range(size[1] // 4):
                    image.putpixel(((x + dx) % size[0], (y + dy) % size[1]), shade)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


class ReleaseContractIntegration(unittest.TestCase):
    """An image record must satisfy validate_draft, validate_packet and media() together.

    Found the hard way: build_image set `url` to a relative /media/<sha>.jpg, which
    validate_draft rejects because web_url() requires an absolute HTTPS URL. The renderer
    substitutes the local path itself, so the record only ever needs the public URL.
    """

    def _record(self):
        import hashlib
        from news_mvp.imagery import PUBLIC_BASE
        sha = 'a' * 64
        return {
            'url': f'{PUBLIC_BASE}/media/{sha}.jpg',
            'local_path': f'media/{sha}.jpg',
            'sha256': sha,
            'alt': 'Kuvituskuva: esimerkki',
            'caption': 'Kuvituskuva. Kuva on luotu tekoälyllä, ei valokuva tapahtumasta.',
            'credit': 'AI-kuvitus (gpt-image-1-mini)',
            'license': 'AI-generated illustration',
            'license_url': f'{PUBLIC_BASE}/kuvituskuvat/',
            'source_url': f'{PUBLIC_BASE}/kuvituskuvat/',
            'generated': True,
            'model': 'gpt-image-1-mini',
            'prompt_sha256': 'b' * 64,
            'prompt_version': 'imagery-v1',
            'subject': 'Esimerkki',
        }

    def test_url_fields_are_absolute_https(self):
        from news_mvp.editorial import web_url
        record = self._record()
        for field in ('url', 'source_url', 'license_url'):
            web_url(record[field])   # raises if not an absolute https URL

    def test_relative_url_is_rejected(self):
        """The exact regression: a relative media path cannot pass the contract."""
        from news_mvp.editorial import web_url
        with self.assertRaises(ValueError):
            web_url('/media/' + 'a' * 64 + '.jpg')

    def test_generated_record_requires_ai_credit_and_illustration_caption(self):
        import json
        from news_mvp.editorial import validate_draft
        record = self._record()

        def draft_with(image):
            return {'title': 'Esimerkki uutinen', 'summary': 'Yhteenveto.', 'category': 'Kotimaa',
                    'paragraphs': [{'text': 'Ensimmäinen kappale.', 'source_ids': ['A']},
                                   {'text': 'Toinen kappale.', 'source_ids': ['A']}],
                    'image': image}

        packet = {'story_key': 'url:https://www.hel.fi/fi/uutiset/esimerkki',
                  'fixture': False, 'image': record,
                  'sources': [{'id': 'A', 'url': 'https://www.hel.fi/fi/uutiset/esimerkki',
                               'publisher': 'Helsingin kaupunki', 'title': 'Esimerkki',
                               'text': 'x' * 400,
                               'published_at': '2026-09-16T10:00:00+03:00'}],
                  'supporting_documents': [{'id': 'RIGHTS'}]}
        validate_draft(draft_with(record), packet)

        no_credit = {**record, 'credit': 'Kuvitus'}
        with self.assertRaises(ValueError):
            validate_draft(draft_with(no_credit), packet)

        no_caption_mark = {**record, 'caption': 'Tekoälyn tuottama kuva.'}
        with self.assertRaises(ValueError):
            validate_draft(draft_with(no_caption_mark), packet)


class FailClosed(unittest.TestCase):
    def setUp(self):
        # This class tests generation fallback and safety gates, not provider availability.
        self._unsplash = mock.patch('news_mvp.imagery.fetch_unsplash', return_value=None)
        self._pexels = mock.patch('news_mvp.imagery.fetch_pexels', return_value=None)
        self._unsplash.start()
        self._pexels.start()
        self.addCleanup(self._unsplash.stop)
        self.addCleanup(self._pexels.stop)

    def test_build_image_returns_none_when_generation_fails(self):
        """No image is always acceptable; a wrong or unverifiable image never is."""
        import news_mvp.imagery as imagery
        draft = {'title': 'Kuopio kokeili koulunkäyntiä väestönsuojassa',
                 'paragraphs': [{'text': 'Oppilaat osallistuivat harjoitukseen.', 'source_ids': ['A']}]}
        original = imagery.generate

        def boom(*args, **kwargs):
            raise imagery.GenerationError('provider unavailable')

        imagery.generate = boom
        try:
            self.assertIsNone(imagery.build_image(draft, '/tmp'))
        finally:
            imagery.generate = original


class ProviderChainIntegration(unittest.TestCase):
    DRAFT = {
        'title': 'Hallitus esittää poliisille laajempia valtuuksia',
        'paragraphs': [{'text': 'Lakiesitys laajentaisi valtuuksia.', 'source_ids': ['A']}],
    }

    def test_provider_order_and_pexels_short_circuit_generation(self):
        import news_mvp.imagery as imagery
        unsplash = {'generated': False, 'provider': 'unsplash'}
        pexels = {'generated': False, 'provider': 'pexels'}
        calls = []
        with tempfile.TemporaryDirectory() as state, \
             mock.patch.object(imagery, 'fetch_unsplash',
                               side_effect=lambda draft: calls.append('unsplash') or None), \
             mock.patch.object(imagery, 'fetch_pexels',
                               side_effect=lambda draft, state_dir: calls.append('pexels') or pexels), \
             mock.patch.object(imagery, 'generate', side_effect=AssertionError('generation')):
            result = imagery.build_image(self.DRAFT, state)
        self.assertIs(result, pexels)
        self.assertEqual(calls, ['pexels'])

        calls.clear()
        with tempfile.TemporaryDirectory() as state, \
             mock.patch.object(imagery, 'fetch_unsplash',
                               side_effect=lambda draft: calls.append('unsplash') or unsplash), \
             mock.patch.object(imagery, 'fetch_pexels',
                               side_effect=lambda draft, state_dir: calls.append('pexels') or None), \
             mock.patch.object(imagery, 'generate', side_effect=AssertionError('generation')):
            result = imagery.build_image(self.DRAFT, state)
        self.assertIs(result, unsplash)
        self.assertEqual(calls, ['pexels', 'unsplash'])

    def test_absent_stock_providers_fall_back_to_ai_and_keep_model_provenance(self):
        import news_mvp.imagery as imagery
        with tempfile.TemporaryDirectory() as state, \
             mock.patch.object(imagery, 'fetch_unsplash', return_value=None), \
             mock.patch.object(imagery, 'fetch_pexels', return_value=None), \
             mock.patch.object(imagery, 'generate',
                               return_value=(_structured_png(), 'prompt', 'test-model')), \
             mock.patch.object(imagery, 'describe', return_value=None):
            result = imagery.build_image(self.DRAFT, state)
        self.assertIsNotNone(result)
        self.assertTrue(result['generated'])
        self.assertEqual(result['credit'], 'AI-kuvitus')
        self.assertEqual(result['model'], 'test-model')

    def test_unsafe_subject_remains_text_only_before_provider_chain(self):
        import news_mvp.imagery as imagery
        with tempfile.TemporaryDirectory() as state, \
             mock.patch.object(imagery, 'fetch_unsplash') as unsplash, \
             mock.patch.object(imagery, 'fetch_pexels') as pexels, \
             mock.patch.object(imagery, 'generate') as generate:
            result = imagery.build_image({
                'title': 'Onnettomuudessa kuoli kaksi ihmistä',
                'paragraphs': [{'text': 'Turma vaati uhreja.', 'source_ids': ['A']}],
            }, state)
        self.assertIsNone(result)
        unsplash.assert_not_called()
        pexels.assert_not_called()
        generate.assert_not_called()

    def test_build_image_returns_none_for_unsafe_subject(self):
        import news_mvp.imagery as imagery
        draft = {'title': 'Onnettomuudessa kuoli kaksi ihmistä',
                 'paragraphs': [{'text': 'Turma vaati uhreja.', 'source_ids': ['A']}]}
        self.assertIsNone(imagery.build_image(draft, '/tmp'))


if __name__ == '__main__':
    unittest.main()
