"""Owner contract: article-only white surfaces and concise reader notices."""
import copy
import json
import unittest
from html import escape
from pathlib import Path
from news_mvp import site
from news_mvp.release_contract import check_article
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

    def test_minimal_reuse_keeps_only_publisher_licence_and_cc_changes(self):
        sources = copy.deepcopy(self.packet['sources'])
        reuse = sources[0]['reuse']
        reuse.update(license='Long permission prose', license_url='https://creativecommons.org/licenses/by/4.0/',
                     changes='Long modification permission paragraph', notice='Required copyright notice')
        before = copy.deepcopy(sources)
        html = site.reuse_rights_html(sources)
        for old in ('Jakelu ja tekstin käyttöehdot', 'Nämä tiedot kuvaavat', reuse['license'],
                    reuse['changes'], reuse['url'], reuse['notice'], '>Lähde</a>'):
            self.assertNotIn(old, html)
        for retained in (sources[0]['publisher'], reuse['license_url'], 'CC BY 4.0',
                         'Muokattu ja tiivistetty.'):
            self.assertIn(retained, html)
        self.assertEqual(sources, before)

    def test_readback_requires_exact_new_reuse_rendering(self):
        jobs, output, _ = self.render([('Kulttuuri', 'reuse-readback')])
        packet = json.loads(jobs[0]['packet'])
        draft = json.loads(jobs[0]['draft'])
        notice = 'Lähde: Poliisi. Vain tekstiaineistoa; poliisin kuvia ei käytetä.'
        packet['sources'][0]['reuse']['notice'] = notice
        html = self.article_text(output, jobs[0])
        check_article(html, packet, draft)

        reuse = packet['sources'][0]['reuse']
        rendered = site.reuse_rights_html(packet['sources'])
        licence = (f'<a href="{escape(reuse["license_url"], quote=True)}">'
                   f'{site.short_license_label(reuse["license_url"])}</a>')
        legacy_link = f'<a href="{escape(reuse["url"], quote=True)}">Lähde</a> · '
        old_renderings = (
            rendered.replace(licence, legacy_link + licence, 1),
            rendered.replace('</li>', f' · {escape(notice)}</li>', 1),
        )
        for old in old_renderings:
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'reuse attribution'):
                check_article(html.replace(rendered, old, 1), packet, draft)

    def test_white_rule_is_light_only_and_scoped(self):
        css = (Path(site.__file__).parents[1] / 'static/style.css').read_text()
        self.assertIn(':root.reader-page:not([data-theme="dark"]){--bg:#fff;--portal-bg:#fff;background:#fff}', css)
        self.assertIn(':root.reader-page:not([data-theme="dark"]) body.reader-page', css)
        self.assertIn(':root.reader-page:not([data-theme="dark"]) .single-article{background:#fff}', css)
        self.assertNotIn('--bg:#f7f5f0;', css)  # owner rule: site stays white
        portal_css = (Path(site.__file__).parents[1] / 'static/css/portal-overhaul.css').read_text()
        self.assertIn('[data-theme="dark"] {\n  --portal-bg: #101214;', portal_css)


if __name__ == '__main__':
    unittest.main()
