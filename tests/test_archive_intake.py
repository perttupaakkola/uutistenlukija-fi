"""Historical extraction may survive an image-only correction, never new intake."""
import unittest

from news_mvp.release_contract import _archived_source_matches
from news_mvp.related import strip_navigation
import test_stock_release_contract as stock_tests
from news_mvp.release_contract import stock_binding


class ArchiveIntake(unittest.TestCase):
    def test_exact_old_source_with_navigation_is_recognised(self):
        text = 'An article sentence with substantive source text.\n' + '\n'.join(['Tag one','Tag two','Tag three','Tag four','Tag five','Tag six'])
        raw = ('<div class="journal-content-article">'+text+'</div>').encode()
        source = {'id':'A','title':'Original title','published_at':'2026-09-15T10:00:00Z','text':text}
        parsed = {**source,'text':strip_navigation(text)}
        self.assertNotEqual(source['text'],parsed['text'])
        self.assertTrue(_archived_source_matches(raw,'valtioneuvosto',source,parsed))
        for field in ('title','published_at','text'):
            bad = {**source,field:source[field]+' changed'}
            self.assertFalse(_archived_source_matches(raw,'valtioneuvosto',bad,parsed))
        self.assertFalse(_archived_source_matches(raw,'helsinki',source,parsed))
        self.assertFalse(_archived_source_matches(raw.replace(b'substantive',b'changed'),'valtioneuvosto',source,parsed))

    def test_explicit_non_event_location_caption_is_still_bound(self):
        image = stock_tests.StockReleaseContract().unsplash_image()
        image['caption']='Arkistokuva artikkelin aiheesta. Kuva ei esitä uutisen tapahtumapaikkaa.'
        stock_binding(image)
        image['caption']='Valokuva uutisen tapahtumapaikalta.'
        with self.assertRaisesRegex(ValueError,'caption is invalid'):
            stock_binding(image)
