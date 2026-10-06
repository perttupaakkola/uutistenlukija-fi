"""Exact renderer action contract, with no credential or provider imports."""
import ast,html,unittest
from pathlib import Path

def actions():
    path=Path(__file__).resolve().parents[1]/'news_mvp/site.py'
    tree=ast.parse(path.read_text())
    names={'esc','article_actions_html','category_page_slug','category_route','category_display'}
    constants={'SITE_URL','ABOUT_PATH','CATEGORY_PAGES','CATEGORY_ALIASES','LATEST_PATH'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
    env={'html':html};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env);return env['article_actions_html']
class LatestContinuation(unittest.TestCase):
    def test_public_has_one_explicit_latest_action(self):
        text=actions()('/uutiset/example/','kulttuuri',True)
        self.assertEqual(text.count('class="article-latest-return"'),1)
        self.assertIn('href="/tuoreimmat/">Lue seuraavaksi tuoreimmat uutiset</a>',text)
    def test_private_has_no_new_public_call_to_action(self):
        self.assertNotIn('article-latest-return',actions()('/uutiset/example/','kulttuuri',False))
    def test_existing_category_correction_share_unchanged(self):
        text=actions()('/uutiset/example/','kulttuuri',True)
        for value in ['Osaston uutiset: Kulttuuri','/categories/kulttuuri/','Korjauskäytäntö','Jaa tai kopioi linkki','https://uutistenlukija.fi/uutiset/example/']:self.assertIn(value,text)
    def test_no_tracking_or_script_added(self):
        text=actions()('/uutiset/example/','kulttuuri',True)
        self.assertNotIn('<script',text);self.assertNotIn('utm_',text);self.assertNotIn('onclick',text)
if __name__=='__main__':unittest.main()
