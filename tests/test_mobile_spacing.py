import hashlib
import struct
import unittest
from pathlib import Path

from test_portal_shell import css_rules, declarations_for


ROOT = Path(__file__).resolve().parents[1]
COMPATIBILITY_STYLE = ROOT / "static/style.css"
LOGO = ROOT / "static/images/logo.png"
MOBILE_SCOPE = ("@media(max-width:600px)",)
LEAD_SELECTOR = ".portal-lead .portal-lead__body"
HERO_SELECTOR = ".single-article .article-hero"
HERO_IMAGE_SELECTOR = ".single-article .article-hero img"
CAPTION_SELECTOR = ".single-article .article-hero-caption"
FOOTER_LOGO_SELECTOR = ".site-footer-brand__image"


def media_scopes_for(rules, selector):
    return list(dict.fromkeys(
        media
        for rule_selector, declarations, media in rules
        if selector in rule_selector.split(",")
    ))


def declarations_in_scope(rules, selector, media):
    scoped_rules = [rule for rule in rules if rule[2] == media]
    return {
        property_name: value
        for declaration in declarations_for(scoped_rules, selector)
        for property_name, value in declaration.items()
    }


class MobileSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = css_rules(COMPATIBILITY_STYLE.read_text(encoding="utf-8"))

    def test_mobile_lead_sizes_are_scoped_important_and_full_width(self):
        self.assertEqual(
            declarations_in_scope(self.rules, LEAD_SELECTOR, MOBILE_SCOPE),
            {
                "inline-size": "100%!important",
                "max-inline-size": "100%!important",
                "width": "100%!important",
                "max-width": "100%!important",
            },
        )
        self.assertEqual(media_scopes_for(self.rules, LEAD_SELECTOR), [MOBILE_SCOPE])

    def test_mobile_hero_expands_with_retained_negative_margins(self):
        self.assertEqual(
            declarations_in_scope(self.rules, HERO_SELECTOR, MOBILE_SCOPE),
            {"width": "calc(100% + 1.5rem)", "margin-inline": "-.75rem"},
        )
        self.assertEqual(media_scopes_for(self.rules, HERO_SELECTOR), [(), MOBILE_SCOPE])

    def test_mobile_caption_padding_matches_each_hero_gutter(self):
        self.assertEqual(
            declarations_in_scope(self.rules, CAPTION_SELECTOR, MOBILE_SCOPE),
            {"padding-inline": ".75rem"},
        )
        self.assertEqual(
            media_scopes_for(self.rules, CAPTION_SELECTOR), [(), MOBILE_SCOPE]
        )

    def test_footer_logo_disables_filter_outside_media_queries(self):
        self.assertEqual(
            declarations_in_scope(self.rules, FOOTER_LOGO_SELECTOR, ()),
            {
                "display": "block",
                "width": "min(220px,100%)",
                "height": "auto",
                "filter": "none",
                "opacity": ".94",
            },
        )
        self.assertEqual(media_scopes_for(self.rules, FOOTER_LOGO_SELECTOR), [()])

    def test_logo_asset_bytes_and_proportions_are_unchanged(self):
        logo_bytes = LOGO.read_bytes()
        self.assertEqual(
            hashlib.sha256(logo_bytes).hexdigest(),
            "84682691e23f4f6ae0accbcc5e41649c9e7cdd53107f676fe43320b4358619b6",
        )
        self.assertEqual(struct.unpack(">II", logo_bytes[16:24]), (977, 191))

    def test_desktop_hero_declarations_remain_intact(self):
        self.assertEqual(
            declarations_in_scope(self.rules, HERO_SELECTOR, ()),
            {"margin": "0 0 1.5rem"},
        )
        self.assertEqual(
            declarations_in_scope(self.rules, HERO_IMAGE_SELECTOR, ()),
            {"display": "block", "width": "100%", "height": "auto", "border-radius": "6px"},
        )
        self.assertNotIn((), media_scopes_for(self.rules, LEAD_SELECTOR))
