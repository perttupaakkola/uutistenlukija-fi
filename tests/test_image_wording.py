"""Current records and exact live readback refuse obsolete image metadata."""
from copy import deepcopy
import unittest

from news_mvp.image_wording import (AI_ALT_PREFIX, AI_CAPTION, AI_CREDIT,
    AI_TERMS_URL, RETIRED_IMAGE_STEM, validate_generated_wording, migrate_generated_metadata)
from news_mvp.release_contract import check_article
import test_article_category as article_cases
from news_mvp.editorial import digest
from image_helpers import approved_pixel_review
from test_cdn_email_contract import GENERATED_IMAGE


class GeneratedWording(unittest.TestCase):
    def test_metadata_migration_preserves_original_pixels_and_prompt_and_binds_history(self):
        import hashlib
        case = article_cases.GeneratedCreditContract()
        draft = {**case._draft(), 'category':'Kotimaa'}
        raw=b'synthetic immutable pixels'
        image=deepcopy(draft['image'])
        image.update(sha256=hashlib.sha256(raw).hexdigest(),alt=RETIRED_IMAGE_STEM+'a: vanha kuva',
            source_url='https://uutistenlukija.fi/'+RETIRED_IMAGE_STEM+'at/',
            classifier_output={'depictable_scene':RETIRED_IMAGE_STEM+'a metsän puista'})
        original=deepcopy(image)
        review=approved_pixel_review(raw,draft,True)
        review['alt_fi']='Vihreitä puita aurinkoisessa metsässä.'
        migrated=migrate_generated_metadata(image,review,draft)
        self.assertEqual(image,original)
        self.assertEqual(migrated['sha256'],image['sha256'])
        self.assertEqual(migrated['prompt_sha256'],image['prompt_sha256'])
        self.assertEqual(migrated['alt'],AI_ALT_PREFIX+review['alt_fi'])
        self.assertEqual(migrated['wording_migration']['previous_image_record_sha256'],digest(original))
        validate_generated_wording(migrated)
        with self.assertRaisesRegex(ValueError,'do not replay'):
            migrate_generated_metadata(migrated,review,draft)
        for mutation in ({**review,'image_sha256':'f'*64},{**review,'approved':False},
                         {**review,'alt_fi':RETIRED_IMAGE_STEM+'a metsästä'},
                         {**review,'no_people':False}):
            with self.subTest(review=mutation),self.assertRaises(ValueError):
                migrate_generated_metadata(image,mutation,draft)

    def test_current_complete_accessibility_record_passes(self):
        image = deepcopy(GENERATED_IMAGE)
        validate_generated_wording(image)
        self.assertEqual(image['caption'], AI_CAPTION)

    def test_all_current_metadata_and_old_terms_are_rejected(self):
        for field, value in [
            ('alt', AI_ALT_PREFIX),
            ('alt', 'Kirjoja kirjaston hyllyillä.'),
            ('caption', 'Tekoälyn tekemä kuva.'),
            ('credit', AI_CREDIT + ' (model-name)'),
            ('license_url', 'https://example.org/old-terms/'),
            ('source_url', 'https://example.org/old-terms/'),
            ('review_note', RETIRED_IMAGE_STEM.upper() + 'A'),
            ('classifier_output', {'depictable_scene': RETIRED_IMAGE_STEM + 'a: kirjoja'}),
        ]:
            with self.subTest(field=field):
                image = {**deepcopy(GENERATED_IMAGE), field: value}
                with self.assertRaises(ValueError):
                    validate_generated_wording(image)

    def test_exact_live_readback_refuses_missing_or_changed_alt(self):
        case = article_cases.GeneratedCreditContract()
        html = case._html(AI_CREDIT)
        check_article(html, case._packet_for(), case._draft())
        for changed in [html.replace(GENERATED_IMAGE['alt'], AI_ALT_PREFIX),
                        html.replace('alt="', 'data-previous-alt="'),
                        html.replace('</body>', RETIRED_IMAGE_STEM + 'a</body>')]:
            with self.subTest(html=changed):
                with self.assertRaises(ValueError):
                    check_article(changed, case._packet_for(), case._draft())


if __name__ == '__main__':
    unittest.main()
