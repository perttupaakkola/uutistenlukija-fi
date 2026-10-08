"""Owner contract: article-only white surfaces and concise reader notices."""
import copy
import unittest
from pathlib import Path
from news_mvp import site
from test_article_category import ArticleAndCategoryRendering


class OwnerCleanup(ArticleAndCategoryRendering):
    def test_article_shell_and_disclosures(self):
        jobs, output, _ = self.render([('Kulttuuri', 'owner')])
        html = self.article_text(output, jobs[0])
        self.assertIn('<html lang="fi" class="reader-page">', html)
        self.assertIn('<body class="reader-page">', html)
        for old in ('article-production', 'Tuotantotiedot', 'Teksti on tuotettu tekoälyn',
                    'automaattisesti tuotettu suomenkielinen uutispalvelu.'):
            self.assertNotIn(old, html)
        self.assertIn(site.ABOUT_PATH, html)
        self.assertIn('AI-generoitu kuva', html)
        self.assertIn('id="lahde-1"', html)
        self.assertIn('href="#lahde-1"', html)
        for route in ('index.html', 'categories/kulttuuri/index.html'):
            self.assertNotIn('class="reader-page"', (output / route).read_text())
        self.assertIn('automatisoitu', site.about_page_body())
        self.assertIn('ihmisen ennakkotarkastamia', site.about_page_body())

    def test_minimal_reuse_keeps_attribution_notice_and_records(self):
        sources = copy.deepcopy(self.packet['sources'])
        reuse = sources[0]['reuse']
        reuse.update(license='Long permission prose', license_url='https://creativecommons.org/licenses/by/4.0/',
                     changes='Long modification permission paragraph', notice='Required copyright notice')
        before = copy.deepcopy(sources)
        html = site.reuse_rights_html(sources)
        for old in ('Jakelu ja tekstin käyttöehdot', 'Nämä tiedot kuvaavat', reuse['license'], reuse['changes']):
            self.assertNotIn(old, html)
        for retained in (sources[0]['publisher'], reuse['url'], reuse['license_url'], reuse['notice'], 'CC BY 4.0', 'Muokattu'):
            self.assertIn(retained, html)
        self.assertEqual(sources, before)

    def test_white_rule_is_light_only_and_scoped(self):
        css = (Path(site.__file__).parents[1] / 'static/style.css').read_text()
        self.assertIn(':root.reader-page:not([data-theme="dark"]){--bg:#fff;--portal-bg:#fff;background:#fff}', css)
        self.assertIn(':root.reader-page:not([data-theme="dark"]) body.reader-page', css)
        self.assertIn(':root.reader-page:not([data-theme="dark"]) .single-article{background:#fff}', css)
        self.assertIn('--bg:#f7f5f0;', css)
        self.assertIn(':root[data-theme="dark"]{\n  --bg:#101a1e;', css)


if __name__ == '__main__':
    unittest.main()
