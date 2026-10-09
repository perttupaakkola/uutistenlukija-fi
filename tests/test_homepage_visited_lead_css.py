"""Focused declaration/scope regression; real-pixel acceptance lives in private review."""
import pathlib,re,unittest
CSS=pathlib.Path(__file__).resolve().parents[1]/'static/style-readability.css'
class VisitedPhotoLeadCSS(unittest.TestCase):
    def test_scoped_to_desktop_photo_lead(self):
        css=CSS.read_text()
        rule=re.search(r'@media \(min-width: 901px\) \{\s*(\.portal-front-grid:not\(\.portal-front-grid--image-free-lead\) \.portal-lead__body a:visited) \{\s*color: inherit;\s*\}\s*\}',css)
        self.assertIsNotNone(rule)
    def test_no_global_visited_override(self):
        css=CSS.read_text()
        self.assertEqual(css.count(':visited'),1)
        self.assertNotRegex(css,r'(?m)^\s*a:visited')
    def test_original_anchor_and_compound_rules_preserved(self):
        css=CSS.read_text()
        for rule in ('[id]{scroll-margin-top:5rem}', '.sources li{scroll-margin-top:6rem}', '.story-body,.lead{overflow-wrap:break-word;hyphens:auto;-webkit-hyphens:auto}'):
            self.assertIn(rule,css)
