"""Scoped reviewed-edge exclusions: no ranking change or fourth-slot refill."""
import ast
from pathlib import Path
import unittest
from news_mvp import site

class ReviewedRelatedEdges(unittest.TestCase):
    def test_five_exact_directed_removals(self):
        self.assertEqual(len(site._REVIEWED_RELATED_EXCLUSIONS), 5)
        for origin, destination in site._REVIEWED_RELATED_EXCLUSIONS:
            with self.subTest(origin=origin, destination=destination):
                picks = [({'id': destination}, {'title': 'Captured unrelated story'})]
                self.assertEqual(site.reviewed_related_picks({'id': origin}, picks), [])
                self.assertEqual(site.reviewed_related_picks({'id': 'other-origin'}, picks), picks)
    def test_removed_top_three_never_refills_fourth(self):
        origin = '81f29c83f79538d5fd9b01f974a798f551b47e58a0dff7cbce29db5efbb8bc7c'
        destinations = sorted(b for a,b in site._REVIEWED_RELATED_EXCLUSIONS if a == origin)
        self.assertEqual(len(destinations), 3)
        ranked = [({'id': key}, {'title': 'Reviewed unrelated story'}) for key in destinations]
        fourth = ({'id': 'unreviewed-fourth'}, {'title': 'Unreviewed filler'})
        ranked.append(fourth)
        self.assertEqual(len(ranked[:3]), 3)
        self.assertEqual(site.reviewed_related_picks({'id': origin}, ranked[:3]), [])
    def test_other_links_order_and_input_unchanged(self):
        origin,destination=next(iter(site._REVIEWED_RELATED_EXCLUSIONS))
        one=({'id':'positive-one'},{'title':'Supported continuation'})
        two=({'id':'positive-two'},{'title':'Supported continuation two'})
        picks=[one,({'id':destination},{'title':'Unrelated'}),two]
        before=list(picks)
        self.assertEqual(site.reviewed_related_picks({'id':origin},picks),[one,two])
        self.assertEqual(picks,before)
    def test_actual_renderer_filters_original_selected_list(self):
        tree=ast.parse(Path(site.__file__).read_text())
        render=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='render_site')
        calls=[n for n in ast.walk(render) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='picks' for t in n.targets)]
        self.assertEqual(len(calls),1)
        self.assertEqual(ast.unparse(calls[0]),"picks = reviewed_related_picks(job, related_for[job['id']])")
        # No changes to the selector; only the already-ranked top-three is filtered.
        limits=[n for n in ast.walk(render) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id=='scored']
        self.assertTrue(any(isinstance(n.slice,ast.Slice) and isinstance(n.slice.upper,ast.Constant) and n.slice.upper.value==3 for n in limits))
