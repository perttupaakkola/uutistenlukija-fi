#!/usr/bin/env python3
"""Consent copy, persistence, revocation, and dormant-ad safety contracts."""
from __future__ import annotations

import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = Path(os.environ["OPE351_PUBLIC_DIR"]) if os.environ.get("OPE351_PUBLIC_DIR") else None


class ConsentPrivacySourceContractTests(unittest.TestCase):
    def test_banner_uses_approved_truthful_copy_and_canonical_link(self) -> None:
        banner = (ROOT / "layouts/partials/cookie-banner.html").read_text(encoding="utf-8")
        expected = [
            "Suostumuksellasi käytämme analytiikkaevästeitä sivuston kehittämiseen. Mainosverkostot ja kohdennettu mainonta eivät ole tällä hetkellä käytössä.",
            'href="/tietosuojaseloste/" class="cb-link">Tietosuoja- ja evästetiedot</a>',
            "Paikallinen tallennustila",
            "Käytössä sivustolla",
            "Teema- ja evästeasetusten lisäksi sivusto käyttää joillakin sivuilla selaimen paikallista tallennustilaa paikalliseen lukuhistoriaan, lukemisen edistymiseen ja mainontakiinnostusta koskevien toimintojen anonyymiin paikalliseen laskentaan. Tarkemmat tarkoitukset ja säilytysajat on kuvattu evästekäytännössä.",
            "Mainonta (ei käytössä)",
            'aria-label="Mainontaa koskeva asetus"',
            "Sivustolla ei tällä hetkellä ladata Google AdSensea tai muita mainosverkostoja eikä näytetä kohdennettua mainontaa. Mainontavalinta tallentuu osana evästeasetuksia selaimesi paikalliseen tallennustilaan. Se ei nykytilassa lataa mainoksia, aseta mainosverkostojen evästeitä tai välitä tietoja mainosverkostoille. Sivuston malleissa on käyttämätön tekninen valmius mainosverkoston lisäämiseen. Mahdollinen käyttöönotto tarkastetaan erikseen, ja tiedot päivitetään ennen käyttöönottoa.",
        ]
        for text in expected:
            self.assertIn(text, banner)
        self.assertNotIn('href="/tietosuoja/"', banner)

    def test_cookie_policy_contains_complete_approved_local_storage_inventory(self) -> None:
        policy = (ROOT / "content/evasteet.md").read_text(encoding="utf-8")
        self.assertIn("lastmod: 2026-07-10", policy)
        self.assertIn("**Päivitetty:** 10.7.2026", policy)
        expected = [
            "## Evästeet ja selaimen paikallinen tallennustila",
            "Alla oleva taulukko kuvaa sivuston nykyisiä localStorage-tallennuksia. Niitä ei ryhmitellä tässä välttämättömiksi tallennuksiksi.",
            "| `theme` | Tallentaa valitsemasi tumman tai vaalean teeman.",
            "| `cookie_consent_v2` | Tallentaa samaan evästeasetusobjektiin välttämättömiä toimintoja, analytiikkaa ja mainontaa koskevat valinnat.",
            "| `ul_views_v1` | Tallentaa selaimeen paikallisen artikkelikohtaisen katseluhistorian:",
            "| `ul_progress_v1` | Tallentaa selaimeen artikkelikohtaisen lukemisprosentin, otsikon, osoitteen, kuvan ja aikaleiman Jatka lukemista -toimintoa varten.",
            "| `uutistenlukija_monetization_signal_v1` | Tallentaa selaimeen mainontakiinnostusta koskevien toimintojen paikalliset laskurit",
            "### Analytiikkaevästeet",
            "### Mainonta (ei käytössä)",
            "Voit muuttaa analytiikkaa ja mahdollista tulevaa mainontaa koskevia valintoja sivuston evästeasetuksissa.",
            "Paikallisen tallennustilan tyhjentäminen poistaa selaimesta teema- ja evästeasetukset, paikallisen lukuhistorian, lukemisen edistymisen ja paikalliset toimintolaskurit.",
        ]
        for text in expected:
            self.assertIn(text, policy)
        self.assertNotIn("### 1. Välttämättömät evästeet", policy)

    def test_privacy_statement_contains_approved_storage_ad_and_recipient_truth(self) -> None:
        privacy = (ROOT / "content/tietosuojaseloste.md").read_text(encoding="utf-8")
        self.assertIn("lastmod: 2026-07-10", privacy)
        self.assertIn("**Päivitetty:** 10.7.2026", privacy)
        expected = [
            "### Evästeet ja selaimen paikallinen tallennustila",
            "Uutistenlukija.fi käyttää selaimen paikallista tallennustilaa teema- ja evästeasetuksiin sekä joillakin sivuilla paikalliseen lukuhistoriaan, lukemisen edistymiseen ja mainontakiinnostusta koskevien toimintojen anonyymiin paikalliseen laskentaan. Tallennettavat tiedot, niiden tarkoitukset ja nykyinen säilytys kuvataan [evästekäytännössä](/evasteet/).",
            "### Mainosverkostot ja kohdennettu mainonta (ei käytössä)",
            "Uutistenlukija.fi ei tällä hetkellä lataa Google AdSensea tai muuta mainosverkostoa eikä näytä kohdennettua mainontaa.",
            "Google AdSensea tai muuta mainosverkostoa ei tällä hetkellä käytetä.",
            "Mahdolliset tulevat mainosverkoston vastaanottaja- ja siirtotiedot lisätään tähän selosteeseen ennen käyttöönottoa.",
        ]
        for text in expected:
            self.assertIn(text, privacy)

    def test_canonical_source_and_worker_redirect_replace_competing_privacy_page(self) -> None:
        self.assertFalse((ROOT / "content/tietosuoja/_index.md").exists())
        worker = (ROOT / "static/_worker.js").read_text(encoding="utf-8")
        self.assertIn("url.pathname = '/tietosuojaseloste/'", worker)
        self.assertIn("return Response.redirect(url.toString(), 308)", worker)
        self.assertLess(worker.index("const privacySurfaceRedirect"), worker.index("return env.ASSETS.fetch(request)"))

    def test_dormant_config_and_all_layout_paths_use_the_central_gate(self) -> None:
        config = (ROOT / "hugo.toml").read_text(encoding="utf-8")
        self.assertIn("ads_enabled = false", config)
        self.assertIn('adsense_id = ""', config)
        self.assertIn("ads_consent_revision = 2", config)
        self.assertIn("ads_activation_revision = 3", config)

        ad_config = (ROOT / "layouts/partials/ad-config.html").read_text(encoding="utf-8")
        for token in (
            "ads_enabled",
            "adsense_id",
            "ads_consent_revision",
            "ads_activation_revision",
            "immutableActivationFloor",
            "activationFloorValid",
            "configuredConsentRevision",
            "serverEligible",
            "findRE `^-?[0-9]+$`",
        ):
            self.assertIn(token, ad_config)

        layout_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (ROOT / "layouts").rglob("*.html")
        )
        self.assertNotIn("pagead2.googlesyndication.com", layout_text)
        self.assertNotIn("cookie_consent_v3", layout_text)
        self.assertIn('partial "ad-config.html"', layout_text)

    def test_cookie_controls_preserve_contrast_and_mobile_touch_targets(self) -> None:
        critical = (ROOT / "layouts/partials/critical-css.html").read_text(encoding="utf-8")
        style = (ROOT / "themes/uutistenlukija/static/css/style.css").read_text(encoding="utf-8")
        portal_static = (ROOT / "static/css/portal-overhaul.css").read_text(encoding="utf-8")
        portal_asset = (ROOT / "assets/css/portal-overhaul.css").read_text(encoding="utf-8")
        compact = critical.replace(" ", "")
        self.assertIn("#cookie-banner.cb-btn{min-height:44px", compact)
        self.assertIn("#cookie-banner.cb-text{font-size:.85rem;line-height:1.35}", compact)
        self.assertIn("#cookie-banner.cb-btn{min-width:0;min-height:44px", compact)
        self.assertIn("#cookie-banner.cb-btn{min-height:44px!important", compact)
        self.assertNotIn("#cookie-banner .cb-btn{min-height:38px", critical)
        self.assertNotIn("#cookie-banner .cb-btn{min-width:0;min-height:34px", critical)
        self.assertIn('[data-theme="dark"] #cookie-banner .cb-btn--primary', style)
        self.assertIn("background: #c0392b", style)
        self.assertIn(".cm-box .cb-btn--ghost", style)
        self.assertIn("color: var(--text-secondary, #555)", style)
        self.assertEqual(portal_static, portal_asset)
        self.assertEqual(portal_static.count("min-height: 44px !important"), 2)
        self.assertIn("font-size: 0.85rem !important", portal_static)
        self.assertIn("line-height: 1.35 !important", portal_static)
        self.assertNotIn("min-height: 32px !important", portal_static)
        self.assertNotIn("min-height: 38px !important", portal_static)

    def test_persistent_settings_and_ga_revocation_contract(self) -> None:
        footer = (ROOT / "layouts/partials/footer.html").read_text(encoding="utf-8")
        banner = (ROOT / "layouts/partials/cookie-banner.html").read_text(encoding="utf-8")
        critical = (ROOT / "layouts/partials/critical-css.html").read_text(encoding="utf-8")
        style = (ROOT / "themes/uutistenlukija/static/css/style.css").read_text(encoding="utf-8")

        for token in (
            'id="cookie-settings"',
            'type="button"',
            'aria-haspopup="dialog"',
            'aria-controls="cookie-modal"',
            ">Evästeasetukset</button>",
        ):
            self.assertIn(token, footer)

        for token in (
            "window['ga-disable-' + GA_ID] = !!disabled",
            "clearFirstPartyGACookies",
            "cookiePaths",
            "cookieDomains",
            "document.cookie",
            "window.location.reload()",
            "bindConsentUI",
            "cookie-settings",
        ):
            self.assertIn(token, banner)
        self.assertNotIn("return; // already consented", banner)
        self.assertIn("/^_ga(?:_|$)/", banner)
        self.assertIn(".site-footer-consent-button", critical)
        self.assertIn(".site-footer-consent-button", style)


@unittest.skipUnless(PUBLIC_DIR, "set OPE351_PUBLIC_DIR to test rendered Hugo output")
class ConsentPrivacyRenderedContractTests(unittest.TestCase):
    def read_public(self, relative: str) -> str:
        assert PUBLIC_DIR is not None
        return (PUBLIC_DIR / relative).read_text(encoding="utf-8", errors="replace")

    def test_canonical_privacy_and_cookie_pages_render_without_competing_source(self) -> None:
        assert PUBLIC_DIR is not None
        self.assertTrue((PUBLIC_DIR / "tietosuojaseloste/index.html").is_file())
        self.assertTrue((PUBLIC_DIR / "evasteet/index.html").is_file())
        self.assertFalse((PUBLIC_DIR / "tietosuoja/index.html").exists())
        sitemap = self.read_public("sitemap.xml")
        self.assertIn("/tietosuojaseloste/", sitemap)
        self.assertNotIn("/tietosuoja/", sitemap)

    def test_dormant_build_contains_no_provider_network_or_slot_surface(self) -> None:
        homepage = self.read_public("index.html")
        for forbidden in (
            "pagead2.googlesyndication.com",
            "adsbygoogle",
            "data-ul-ad-runtime",
            "data-ul-ad-slot-intent",
            "cookie_consent_v3",
        ):
            self.assertNotIn(forbidden, homepage)
        self.assertIn("cookie_consent_v", homepage)

    def test_rendered_privacy_pages_have_one_heading_and_scrollable_mobile_tables(self) -> None:
        privacy = self.read_public("tietosuojaseloste/index.html")
        cookies = self.read_public("evasteet/index.html")
        self.assertEqual(privacy.count("<h1"), 1)
        self.assertEqual(cookies.count("<h1"), 1)
        critical = (ROOT / "layouts/partials/critical-css.html").read_text(encoding="utf-8")
        article = (ROOT / "themes/uutistenlukija/static/css/article.css").read_text(encoding="utf-8")
        for css in (critical, article):
            self.assertIn("overflow-x:auto", css.replace(" ", ""))
            self.assertIn("42rem", css)

    def test_rendered_banner_links_to_the_canonical_statement(self) -> None:
        homepage = self.read_public("index.html")
        self.assertRegex(
            homepage,
            r'href=(?:"/tietosuojaseloste/"|/tietosuojaseloste/) class=cb-link>Tietosuoja- ja evästetiedot</a>',
        )

    def test_rendered_footer_exposes_one_persistent_settings_control(self) -> None:
        homepage = self.read_public("index.html")
        self.assertEqual(homepage.count('id=cookie-settings'), 1)
        self.assertRegex(
            homepage,
            r'<button[^>]+id=cookie-settings[^>]+aria-controls=cookie-modal[^>]*>Evästeasetukset</button>',
        )


if __name__ == "__main__":
    unittest.main()
