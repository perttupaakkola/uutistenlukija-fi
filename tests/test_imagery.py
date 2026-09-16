"""Article imagery: generation from verified fact, and independent raster verification.

The design rule under test: an image is constructed from a fact the reviewed draft already
states, so correspondence holds by construction and there is no post-hoc "is this stock photo
relevant?" judgement to get wrong. The predecessor system searched stock providers by keyword
and retrofitted a justification; the canonical failure (commit 9318ea23c) illustrated a story
about cocaine in Finnish wastewater with "scenic aerial view of snowy Finnish landscape",
accepted because "metadata matches finnish, landscape".

These tests cover the two properties that made the old approach unsafe: (1) no image is
produced for subjects that would invite depicting real people, tragedy or violence, and
(2) a provider payload is never trusted as evidence of what it depicts.
"""

import io
import unittest


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


class FailClosed(unittest.TestCase):
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

    def test_build_image_returns_none_for_unsafe_subject(self):
        import news_mvp.imagery as imagery
        draft = {'title': 'Onnettomuudessa kuoli kaksi ihmistä',
                 'paragraphs': [{'text': 'Turma vaati uhreja.', 'source_ids': ['A']}]}
        self.assertIsNone(imagery.build_image(draft, '/tmp'))


if __name__ == '__main__':
    unittest.main()
