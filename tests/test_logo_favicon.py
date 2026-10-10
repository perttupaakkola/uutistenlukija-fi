import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from news_mvp import site


ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "static/images"


class EmptyStore:
    def articles(self):
        return []

    def mark_rendered(self, ids):
        pass


class LogoFaviconTests(unittest.TestCase):
    def test_theme_logos_are_full_size_transparent_assets(self):
        with Image.open(IMAGES / "logo.png") as source, \
                Image.open(IMAGES / "logo-light.png") as light, \
                Image.open(IMAGES / "logo-dark.png") as dark:
            self.assertEqual(source.size, (977, 191))
            self.assertEqual(light.size, source.size)
            self.assertEqual(dark.size, source.size)
            self.assertEqual(light.mode, "RGBA")
            self.assertEqual(dark.mode, "RGBA")
            corners = ((0, 0), (976, 0), (0, 190), (976, 190))
            self.assertTrue(all(light.getpixel(point)[3] == 0 for point in corners))
            self.assertTrue(all(dark.getpixel(point)[3] == 0 for point in corners))
            self.assertLess(light.getchannel("A").getextrema()[0], 255)
            self.assertGreater(light.getchannel("A").histogram()[128], 0)

            # Re-compositing the un-matted logo on white reproduces the supplied art,
            # including partially transparent antialiased edges, without a white halo.
            white = Image.new("RGBA", source.size, "white")
            recomposited = Image.alpha_composite(white, light).convert("RGB")
            difference = ImageChops.difference(source.convert("RGB"), recomposited)
            self.assertLessEqual(max(channel[1] for channel in difference.getextrema()), 5)

    def test_dark_logo_uses_light_ink_and_a_readable_red_rule(self):
        with Image.open(IMAGES / "logo-dark.png") as dark:
            opaque_text = {
                dark.getpixel((x, y))[:3]
                for y in range(0, 112)
                for x in range(dark.width)
                if dark.getpixel((x, y))[3] >= 240
            }
            opaque_rule = {
                dark.getpixel((x, y))[:3]
                for y in range(112, 131)
                for x in range(dark.width)
                if dark.getpixel((x, y))[3] >= 240
            }
            self.assertEqual(opaque_text, {(243, 241, 233)})
            self.assertEqual(opaque_rule, {(224, 96, 74)})

    def test_favicon_set_has_expected_sizes_and_opaque_apple_icon(self):
        favicon = ROOT / "static/favicon.ico"
        self.assertTrue(favicon.is_file())
        with Image.open(favicon) as icon:
            self.assertEqual(icon.ico.sizes(), {(16, 16), (32, 32), (48, 48)})
        with Image.open(IMAGES / "favicon-32.png") as icon:
            self.assertEqual(icon.size, (32, 32))
        with Image.open(IMAGES / "apple-touch-icon.png") as icon:
            self.assertEqual(icon.size, (180, 180))
            self.assertEqual(icon.mode, "RGB")

    def test_home_and_article_heads_contain_all_icon_links(self):
        pages = (
            site.page("Etusivu", "<p>x</p>", "/"),
            site.page("Juttu", "<article>x</article>", "/uutiset/juttu/", article_page=True),
        )
        for html in pages:
            with self.subTest(article='class="reader-page"' in html):
                head = html.split("</head>", 1)[0]
                self.assertIn('<link rel="icon" href="/favicon.ico" sizes="any">', head)
                self.assertIn('rel="icon" type="image/png" sizes="32x32"', head)
                self.assertIn('href="/mvp-assets/images/favicon-32.png"', head)
                self.assertIn('rel="apple-touch-icon" sizes="180x180"', head)
                self.assertIn('href="/mvp-assets/images/apple-touch-icon.png"', head)

    def test_header_and_footer_have_both_variants_and_one_nonempty_alt(self):
        html = site.page("Etusivu", "<p>x</p>", "/")
        for class_name in ("portal-logo", "site-footer-brand"):
            fragment = re.search(
                rf'<a class="{class_name}"[^>]*>(.*?)</a>', html, re.S
            ).group(1)
            images = re.findall(r"<img\s+([^>]+)>", fragment)
            self.assertEqual(len(images), 2)
            self.assertIn("logo-light.png", images[0])
            self.assertIn("logo-dark.png", images[1])
            alts = re.findall(r'alt="([^"]*)"', fragment)
            self.assertEqual([alt for alt in alts if alt], ["Uutistenlukija"])
            self.assertIn('alt="" aria-hidden="true"', images[1])

    def test_build_copies_root_favicon(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            site.render_site(EmptyStore(), output, public=True)
            self.assertEqual(
                (output / "favicon.ico").read_bytes(),
                (ROOT / "static/favicon.ico").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
