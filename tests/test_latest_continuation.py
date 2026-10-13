"""Exact renderer action contract, with no credential or provider imports."""
import ast,html,unittest
from pathlib import Path

def helpers():
    path=Path(__file__).resolve().parents[1]/'news_mvp/site.py'
    tree=ast.parse(path.read_text())
    names={'esc','article_actions_html','article_correction_html','category_page_slug','category_route','category_display'}
    constants={'SITE_URL','ABOUT_PATH','CATEGORY_PAGES','CATEGORY_ALIASES','LATEST_PATH'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
    env={'html':html};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env);return env['article_actions_html'],env['article_correction_html']
class LatestContinuation(unittest.TestCase):
    def test_public_actions_are_only_save_and_share(self):
        actions,_=helpers();text=actions('/uutiset/example/','kulttuuri',True)
        self.assertIn('Tallenna',text);self.assertIn('Jaa tai kopioi linkki',text)
        self.assertNotIn('article-latest-return',text);self.assertNotIn('article-section-return',text)
        self.assertNotIn('Korjauskäytäntö',text)
    def test_private_has_no_public_reader_actions(self):
        actions,_=helpers();self.assertEqual(actions('/uutiset/example/','kulttuuri',False),'')
    def test_correction_link_is_a_separate_evidence_link(self):
        actions,correction=helpers();text=actions('/uutiset/example/','kulttuuri',True)
        self.assertIn('https://uutistenlukija.fi/uutiset/example/',text)
        self.assertEqual(correction(),'<a class="article-corrections" href="/tietoja/#korjaukset">Korjauskäytäntö</a>')
    def test_no_tracking_or_script_added(self):
        actions,_=helpers();text=actions('/uutiset/example/','kulttuuri',True)
        self.assertNotIn('<script',text);self.assertNotIn('utm_',text);self.assertNotIn('onclick',text)
if __name__=='__main__':unittest.main()
