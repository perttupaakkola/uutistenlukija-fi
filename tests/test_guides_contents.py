import unittest
from news_mvp import site

class GuideContents(unittest.TestCase):
    def test_links_require_exact_rendered_section_ids(self):
        body = ('<h2 id="oppaat-talvirenkaat-title">Renkaat</h2>'
                '<h2 id="oppaat-heijastin-title">Heijastin</h2>'
                '<h2 id="oppaat-junamatka-title">Juna</h2>')
        nav = site.guides_contents_html(body)
        self.assertEqual(nav.count('<li>'), 3)
        self.assertIn('aria-label="Oppaiden sisältö"', nav)
        self.assertLess(nav.index('#oppaat-talvirenkaat-title'), nav.index('#oppaat-heijastin-title'))
        self.assertLess(nav.index('#oppaat-heijastin-title'), nav.index('#oppaat-junamatka-title'))

    def test_retired_rail_section_has_no_contents_link(self):
        body = ('<h2 id="oppaat-talvirenkaat-title">Renkaat</h2>'
                '<h2 id="oppaat-heijastin-title">Heijastin</h2>')
        nav = site.guides_contents_html(body)
        self.assertEqual(nav.count('<li>'), 2)
        self.assertNotIn('junamatka', nav)
        self.assertNotIn('Junamatka', nav)

    def test_empty_or_near_match_ids_do_not_create_dead_links(self):
        for body in ('', '<h2 id="oppaat-talvirenkaat-title-other">x</h2>',
                     '<h2 id="prefix-oppaat-heijastin-title">x</h2>'):
            with self.subTest(body=body):
                self.assertEqual(site.guides_contents_html(body), '')

    def test_helper_does_not_rewrite_original_body(self):
        body = '<h2 id="oppaat-heijastin-title">Heijastin: näy pimeällä</h2><p>Alkuperäinen ohje.</p>'
        before = body.encode('utf-8')
        site.guides_contents_html(body)
        self.assertEqual(body.encode('utf-8'), before)

if __name__ == '__main__':
    unittest.main()
