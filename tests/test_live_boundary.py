import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp.editorial import ROOT, FixtureModel, HermesModel, parse_hermes_output
from news_mvp.intake import ArticleHTML, collect
from news_mvp.history import preserve_article


class LiveBoundary(unittest.TestCase):
    def test_quiet_json_and_session_wrapper_without_ambiguous_substring_extraction(self):
        for response in ('{"ok":true}', '```json\n{"ok":true}\n```', '\x1b[0m{"ok":true}\n'):
            self.assertEqual(parse_hermes_output(response)[0], {"ok": True})
        self.assertEqual(parse_hermes_output('{"ok":true}\nsession_id: 20260912_abc'), ({"ok": True}, '20260912_abc'))
        for value in ('log: {"ok":true}', '{"ok":true}\n{"another":true}', '[]', '{"ok":true}\nunknown wrapper'):
            with self.assertRaises(ValueError):
                parse_hermes_output(value)

    def test_fixture_and_live_adapters_refuse_crossing_the_boundary(self):
        with patch('news_mvp.editorial.subprocess.run') as run:
            with self.assertRaises(ValueError):
                HermesModel('/must-not-run').call('writer', {"fixture": True})
            run.assert_not_called()
        with self.assertRaises(ValueError):
            FixtureModel().call('writer', {"fixture": False})

    def test_html_intake_uses_published_metadata_and_binds_real_image_bytes(self):
        recipe = json.loads((ROOT/'sources/nasa-artemis.json').read_text())
        page = ('<meta property="og:title" content="Source title"><meta property="article:published_time" content="2026-09-11T10:00:00Z">'
                '<meta property="og:image" content="' + recipe['image']['url'] + '"><nav>Not article content</nav>'
                '<div class="entry-content"><p>' + 'Public source evidence. '*20 + '</p></div><footer>Not article content</footer>').encode()
        image = b'\xff\xd8\xfffixture-jpeg-bytes'
        with tempfile.TemporaryDirectory(prefix='.test-intake-', dir=ROOT) as temp:
            rights = ('<div class="entry-content">' + 'Example permission statement. '*20 + '</div>').encode()
            with patch('news_mvp.intake.fetch', side_effect=[(page,'text/html',recipe['url']), (image,'image/jpeg',recipe['image']['url']), (rights,'text/html',recipe['image']['license_url'])]):
                packet, receipt = collect(recipe,temp,datetime(2026,9,12,tzinfo=timezone.utc))
            self.assertFalse(packet['fixture'])
            self.assertNotIn('Not article content',packet['sources'][0]['text'])
            self.assertEqual(packet['sources'][0]['published_at'],'2026-09-11T10:00:00Z')
            self.assertEqual(packet['image']['sha256'],hashlib.sha256(image).hexdigest())
            self.assertEqual((Path(temp)/packet['image']['local_path']).read_bytes(),image)
            self.assertEqual(receipt['image_bytes'],len(image))

    def test_selective_history_preserves_body_url_rights_and_excludes_internal_notes(self):
        raw='---\ntitle: Historic title\ndraft: false\ncontent_type: article\nimage_credit: Original credit\njournalist_note: Internal process note\n---\nPublic article body.\n'
        with tempfile.TemporaryDirectory(prefix='.test-history-',dir=ROOT) as temp:
            source=Path(temp)/'article.md';source.write_text(raw)
            with patch('news_mvp.history.fetch',return_value=(b'<h1>Historic title</h1>','text/html','https://example.invalid/article/')):
                result=preserve_article(source,'https://example.invalid/article/',Path(temp)/'state')
            record=json.loads(Path(result['record_path']).read_text())
            self.assertEqual(source.read_text(),raw)
            self.assertEqual(record['body_markdown'],'Public article body.')
            self.assertEqual(record['metadata']['image_credit'],'Original credit')
            self.assertNotIn('journalist_note',record['metadata'])
            self.assertFalse(record['republication_approved'])
            self.assertEqual(result['queue_imports'],0)
