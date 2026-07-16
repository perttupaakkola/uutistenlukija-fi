#!/usr/bin/env python3
"""Regression checks for the passive advertiser trust surface."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdvertiserTrustSurfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frontmatter = (ROOT / "content/mainosta/_index.md").read_text(encoding="utf-8")
        self.mainosta = (ROOT / "layouts/_default/mainosta.html").read_text(encoding="utf-8")
        self.homepage = (ROOT / "layouts/index.html").read_text(encoding="utf-8")
        self.digest = (ROOT / "layouts/_default/digest-page.html").read_text(encoding="utf-8")
        self.category = (ROOT / "layouts/taxonomy/category.html").read_text(encoding="utf-8")
        self.article = (ROOT / "layouts/_default/page.html").read_text(encoding="utf-8")
        self.cta = (ROOT / "layouts/partials/advertiser-cta.html").read_text(encoding="utf-8")
        self.founding_sponsor = (ROOT / "layouts/_default/perustajakumppanuus.html").read_text(encoding="utf-8")
        self.founding_sponsor_frontmatter = (ROOT / "content/perustajakumppanuus/_index.md").read_text(encoding="utf-8")
        self.tracking = (ROOT / "layouts/partials/event-tracking.html").read_text(encoding="utf-8")
        self.critical_css = (ROOT / "layouts/partials/critical-css.html").read_text(encoding="utf-8")
        self.style_css = (ROOT / "themes/uutistenlukija/static/css/style.css").read_text(
            encoding="utf-8"
        )
        self.mainosta_css = (ROOT / "assets/css/mainosta.css").read_text(encoding="utf-8")

    def test_mainosta_primary_cta_contrast_is_aa_in_both_themes(self) -> None:
        dark_rule = re.search(
            r':root:not\(\[data-theme="light"\]\) \.mainosta-signal__btn\s*\{([^}]*)\}',
            self.mainosta_css,
        )
        self.assertIsNotNone(dark_rule)
        declarations = dark_rule.group(1).lower()
        self.assertIn("background: #c0392b", declarations)
        self.assertIn("color: #fff", declarations)

        def luminance(hex_color: str) -> float:
            channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        white = luminance("#ffffff")
        portal_red = luminance("#c0392b")
        contrast = (white + 0.05) / (portal_red + 0.05)
        self.assertGreaterEqual(contrast, 4.5)
        self.assertIn(":focus-visible{outline:3px solid var(--accent)", self.critical_css)

    def test_public_copy_has_no_unsupported_or_internal_claims(self) -> None:
        public_copy = self.frontmatter + self.mainosta + self.cta
        forbidden = (
            "10 000+",
            "25 000+",
            "3 min+",
            "25–55",
            "Kaupunkilaiset, koulutetut",
            "käy sivustolla päivittäin",
            "Merkittävä mobiiliyleisö",
            "monetization_signal",
            "Sponsoroitu sisältö",
            "journalistiseen muotoon",
            "pilottikampanja",
            "49 €",
        )
        for claim in forbidden:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, public_copy)

        self.assertIn("Näkyvyyttä, klikkauksia tai myyntiä ei taata", public_copy)
        self.assertIn("mainostaja ei osallistu", public_copy)

    def test_existing_passive_lead_telemetry_is_preserved(self) -> None:
        for template in (self.mainosta, self.cta):
            self.assertIn('data-track="advertise_cta_click"', template)

        self.assertIn('data-monetization-signal="advertise_email_click"', self.mainosta)
        self.assertIn("advertise_email_click", self.cta)
        self.assertIn("advertise_page_click", self.cta)
        self.assertIn("_gtag('event', 'monetization_signal'", self.tracking)
        self.assertIn("[data-monetization-signal]", self.tracking)

    def test_mailto_analytics_never_include_recipient_or_message_content(self) -> None:
        self.assertIn("/^(mailto|tel)$/i.test(schemeMatch[1])", self.tracking)
        self.assertIn("return schemeMatch[1].toLowerCase() + ':'", self.tracking)
        self.assertIn("link_url: safeLinkUrl(el)", self.tracking)
        self.assertNotIn("link_url: el.href", self.tracking)

    def test_article_bottom_uses_approved_founding_sponsor_contract(self) -> None:
        approved_copy = (
            "Yrityksille · Perustajakumppanuus",
            "Kiinnostaisiko näkyvyys Uutistenlukijan perustajakumppanina?",
            "Kumppani ei vaikuta uutisaiheiden valintaan, juttujen sisältöön, "
            "lähteisiin, julkaisemiseen tai järjestykseen.",
            "Kiinnostuksen ilmaiseminen ei sido kampanjaan.",
            "Näkyvyyttä, klikkauksia tai myyntiä ei taata.",
            "Tutustu mainonnan periaatteisiin",
            "Ilmaise kiinnostuksesi",
        )
        for copy in approved_copy:
            with self.subTest(copy=copy):
                self.assertIn(copy, self.cta)

        self.assertIn('eq $placement "article-bottom"', self.cta)
        self.assertIn("founding_sponsor_page_click", self.cta)
        self.assertIn("founding_sponsor_interest_click", self.cta)
        self.assertIn("article-bottom-founding-sponsor-v1", self.cta)
        self.assertIn("Kiinnostus%20Uutistenlukijan%20perustajakumppanuuteen", self.cta)

    def test_homepage_uses_approved_founding_sponsor_contract_after_lead_package(self) -> None:
        partial_call = '{{ partial "advertiser-cta.html" (dict "placement" "homepage" "page" .) }}'
        self.assertEqual(self.homepage.count(partial_call), 1)
        self.assertLess(self.homepage.index('</section>\n  {{ end }}\n\n  ' + partial_call), self.homepage.index('{{ $topicCats :='))

        self.assertIn('(eq $placement "homepage")', self.cta)
        self.assertIn('"homepage-founding-sponsor-v1"', self.cta)
        self.assertIn('data-monetization-view="founding_sponsor_cta_view"', self.cta)
        self.assertIn('data-track="advertise_cta_click"', self.cta)
        self.assertIn("founding_sponsor_page_click", self.cta)
        self.assertIn("founding_sponsor_interest_click", self.cta)
        self.assertIn('/perustajakumppanuus/', self.cta)
        self.assertIn('/perustajakumppanuus/#yhteydenotto', self.cta)

    def test_founding_sponsor_page_is_non_binding_and_privacy_safe(self) -> None:
        public_copy = self.founding_sponsor + self.founding_sponsor_frontmatter
        for expected in (
            'url: "/perustajakumppanuus/"',
            'id="yhteydenotto"',
            "Kiinnostuksen ilmaiseminen ei ole tilaus",
            "Sivulla ei tehdä tilausta, maksua tai laskutussopimusta.",
            "Älä lähetä maksutietoja tai muita arkaluonteisia henkilötietoja.",
            "Viesti ei sido kampanjaan.",
            'href="/tietosuojaseloste/"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, public_copy)

        self.assertIn('data-monetization-signal="founding_sponsor_interest_click"', public_copy)
        self.assertNotRegex(public_copy, r"\b\d+[,.]?\d*\s*€")

    def test_digest_footer_uses_approved_on_site_founding_sponsor_contract(self) -> None:
        partial_call = '{{ partial "advertiser-cta.html" (dict "placement" "daily-digest-footer" "page" .) }}'
        newsletter_call = '{{ partial "newsletter-cta.html" . }}'
        self.assertEqual(self.digest.count(partial_call), 1)
        self.assertLess(self.digest.index('{{ end }}\n\n' + partial_call), self.digest.index(newsletter_call))

        self.assertIn('eq $placement "daily-digest-footer"', self.cta)
        self.assertIn('"daily-digest-footer-founding-sponsor-v1"', self.cta)
        self.assertIn('$usesFoundingSponsorPage', self.cta)
        self.assertIn('/perustajakumppanuus/', self.cta)
        self.assertIn('/perustajakumppanuus/#yhteydenotto', self.cta)
        self.assertIn('data-monetization-view="founding_sponsor_cta_view"', self.cta)
        self.assertIn('founding_sponsor_page_click', self.cta)
        self.assertIn('founding_sponsor_interest_click', self.cta)

    def test_digest_dark_contrast_fix_is_scoped_and_preserves_existing_variants(self) -> None:
        digest_eyebrow = '.advertiser-cta--daily-digest-footer .advertiser-cta__eyebrow'
        digest_primary = '.advertiser-cta--daily-digest-footer .advertiser-cta__button--primary:focus-visible'
        for stylesheet in (self.critical_css, self.style_css):
            with self.subTest(stylesheet=stylesheet[:24]):
                self.assertIn(digest_eyebrow, stylesheet)
                self.assertIn(digest_primary, stylesheet)
                self.assertIn('#f06b5d', stylesheet.lower())
                self.assertIn('#c0392b', stylesheet.lower())

        self.assertIn('"homepage-founding-sponsor-v1"', self.cta)
        self.assertIn('"article-bottom-founding-sponsor-v1"', self.cta)
        self.assertNotIn('.advertiser-cta--article-bottom .advertiser-cta__eyebrow{color:#f06b5d', self.critical_css)

    def test_talous_category_uses_bounded_on_site_founding_sponsor_contract(self) -> None:
        partial_call = '{{ partial "advertiser-cta.html" (dict "placement" "talous-category" "page" .) }}'
        self.assertEqual(self.category.count(partial_call), 1)
        talous_gate = '{{ if eq $termSlug "talous" }}'
        gate_start = self.category.index(talous_gate)
        gate_end = self.category.index('{{ end }}\n  </header>', gate_start)
        self.assertIn(partial_call, self.category[gate_start:gate_end])
        self.assertLess(self.category.index('</section>\n    ' + partial_call), self.category.index('{{ $latestTalous :='))

        self.assertIn('eq $placement "talous-category"', self.cta)
        self.assertIn('"talous-category-founding-sponsor-v1"', self.cta)
        self.assertIn('/perustajakumppanuus/', self.cta)
        self.assertIn('/perustajakumppanuus/#yhteydenotto', self.cta)
        self.assertIn('founding_sponsor_page_click', self.cta)
        self.assertIn('founding_sponsor_interest_click', self.cta)

    def test_talous_category_dark_contrast_scope_preserves_other_variants(self) -> None:
        eyebrow = '.advertiser-cta--talous-category .advertiser-cta__eyebrow'
        primary = '.advertiser-cta--talous-category .advertiser-cta__button--primary:focus-visible'
        for stylesheet in (self.critical_css, self.style_css):
            with self.subTest(stylesheet=stylesheet[:24]):
                self.assertIn(eyebrow, stylesheet)
                self.assertIn(primary, stylesheet)
                self.assertIn('#f06b5d', stylesheet.lower())
                self.assertIn('#c0392b', stylesheet.lower())

        for placement in (
            'homepage-founding-sponsor-v1',
            'daily-digest-footer-founding-sponsor-v1',
            'article-bottom-founding-sponsor-v1',
        ):
            self.assertIn(placement, self.cta)

    def test_talous_article_cta_is_category_gated_and_uses_on_site_contract(self) -> None:
        partial_call = '{{ partial "advertiser-cta.html" (dict "placement" (cond $hasTalousCategory "talous-article" "article-bottom") "page" .) }}'
        self.assertEqual(self.article.count(partial_call), 1)
        self.assertIn('if eq (lower .) "talous"', self.article)
        self.assertLess(self.article.index('{{ partial "related-articles.html" . }}'), self.article.index(partial_call))
        self.assertLess(self.article.index(partial_call), self.article.index('{{ partial "more-from-category.html" . }}'))

        self.assertIn('eq $placement "talous-article"', self.cta)
        self.assertIn('"talous-article-founding-sponsor-v1"', self.cta)
        self.assertIn('/perustajakumppanuus/', self.cta)
        self.assertIn('/perustajakumppanuus/#yhteydenotto', self.cta)
        self.assertIn('founding_sponsor_page_click', self.cta)
        self.assertIn('founding_sponsor_interest_click', self.cta)

    def test_talous_article_dark_contrast_scope_preserves_existing_variants(self) -> None:
        eyebrow = '.advertiser-cta--talous-article .advertiser-cta__eyebrow'
        primary = '.advertiser-cta--talous-article .advertiser-cta__button--primary:focus-visible'
        for stylesheet in (self.critical_css, self.style_css):
            with self.subTest(stylesheet=stylesheet[:24]):
                self.assertIn(eyebrow, stylesheet)
                self.assertIn(primary, stylesheet)
                self.assertIn('#f06b5d', stylesheet.lower())
                self.assertIn('#c0392b', stylesheet.lower())

        for placement in (
            'homepage-founding-sponsor-v1',
            'daily-digest-footer-founding-sponsor-v1',
            'talous-category-founding-sponsor-v1',
            'article-bottom-founding-sponsor-v1',
        ):
            self.assertIn(placement, self.cta)

    def test_homepage_dark_contrast_fix_is_scoped_and_preserves_focus_outline(self) -> None:
        eyebrow = ':root:not([data-theme="light"]) .advertiser-cta--homepage .advertiser-cta__eyebrow'
        primary = ':root:not([data-theme="light"]) .advertiser-cta--homepage .advertiser-cta__button--primary:focus-visible'
        for stylesheet in (self.critical_css, self.style_css):
            with self.subTest(stylesheet=stylesheet[:24]):
                self.assertIn(eyebrow, stylesheet)
                self.assertIn("#f06b5d", stylesheet.lower())
                self.assertIn(primary, stylesheet)
                self.assertIn("#c0392b", stylesheet.lower())

        self.assertIn(":focus-visible{outline:3px solid var(--accent)", self.critical_css)
        self.assertNotIn(".advertiser-cta--article-bottom .advertiser-cta__eyebrow{color:#f06b5d", self.critical_css)

    def test_founding_sponsor_view_requires_half_visibility_for_one_second(self) -> None:
        self.assertIn('data-monetization-view="founding_sponsor_cta_view"', self.cta)
        self.assertIn("entry.intersectionRatio < 0.5", self.tracking)
        self.assertIn("}, 1000);", self.tracking)
        self.assertIn("_gtag('event', kind", self.tracking)
        self.assertIn("viewFired = true", self.tracking)

    def test_founding_sponsor_click_events_are_named_and_privacy_safe(self) -> None:
        helper = re.search(
            r"function recordNamedFoundingSponsorClick\(.*?\n    \}",
            self.tracking,
            re.DOTALL,
        )
        self.assertIsNotNone(helper)
        block = helper.group(0)

        allowed = set(
            re.findall(
                r"(founding_sponsor_(?:page|contact|interest)_click): true",
                block,
            )
        )
        self.assertEqual(
            allowed,
            {
                "founding_sponsor_page_click",
                "founding_sponsor_contact_click",
                "founding_sponsor_interest_click",
            },
        )

        event_params = re.search(
            r"_gtag\('event', kind, \{(.*?)\}\);",
            block,
            re.DOTALL,
        )
        self.assertIsNotNone(event_params)
        self.assertEqual(
            re.findall(r"^\s*([a-z_]+):", event_params.group(1), re.MULTILINE),
            ["placement", "page_path"],
        )
        for forbidden in (
            "href",
            "mailto",
            "query",
            "subject",
            "body",
            "email",
            "article",
            "link_url",
            "link_text",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, block.lower())

        self.assertIn(
            "recordNamedFoundingSponsorClick("
            "kind, state.last_placement, state.last_path);",
            self.tracking,
        )

    def test_founding_sponsor_contact_and_interest_stages_are_separate(self) -> None:
        self.assertIn(
            'data-monetization-signal="{{ if $usesFoundingSponsorPage }}'
            'founding_sponsor_contact_click{{ else if $isFoundingSponsor }}'
            'founding_sponsor_interest_click',
            self.cta,
        )
        self.assertIn(
            'data-monetization-signal="founding_sponsor_interest_click"',
            self.founding_sponsor,
        )

    def test_article_bottom_cta_uses_full_width_copy_row(self) -> None:
        selector = ".advertiser-cta--article-bottom .advertiser-cta__inner"
        for stylesheet in (self.critical_css, self.style_css):
            with self.subTest(stylesheet=stylesheet[:24]):
                start = stylesheet.find(selector)
                self.assertNotEqual(-1, start)
                rule = stylesheet[start : start + 180]
                self.assertIn("grid-template-columns", rule)
                self.assertIn("minmax(0, 1fr)", rule)


if __name__ == "__main__":
    unittest.main()
