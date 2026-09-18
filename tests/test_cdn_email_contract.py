"""Regression: CDN e-mail obfuscation must not break the reviewed-content contract.

Real incident: ``publish.py`` verifies a deployed article by fetching the live
canonical URL and comparing it to the reviewed draft. Cloudflare rewrites every
plain address in served HTML into a ``data-cfemail`` link, so any article whose
body cites an address failed verification with "Public article differs from
reviewed content/licence" even though the deployed page was byte-correct. The
publication stayed ``unknown`` and the tick exited 1 on every retry.

The contract must compare *reviewed content* against the served page, not against
a reverse proxy's rewriting of it — while still refusing any real divergence.
"""
import unittest
from html import escape

from news_mvp.release_contract import (
    _denormalize_cdn_email_obfuscation,
    check_article,
)

ADDRESS = "hulevesimaksu@vantaa.fi"
PARAGRAPH = (
    "Tiedotteen saatuaan kiinteistönomistajan kannattaa perehtyä siihen, miten "
    "maksu määräytyy omalle kiinteistölle ja miten kysymykset kaupunki ohjaa "
    f"osoitteeseen {ADDRESS}."
)


def cf_encode(address: str, key: int = 0x2D) -> str:
    """Encode an address the way Cloudflare's data-cfemail attribute does."""
    return f"{key:02x}" + "".join(f"{b ^ key:02x}" for b in address.encode())


def cf_link(address: str) -> str:
    return (
        '<a href="/cdn-cgi/l/email-protection" class="__cf_email__" '
        f'data-cfemail="{cf_encode(address)}">[email&#160;protected]</a>'
    )


def draft_with(text: str) -> dict:
    return {
        "title": "Vantaa lähettää kiinteistönomistajille tiedotteet",
        "summary": "Vantaan kaupunki lähettää tiedotteita.",
        "paragraphs": [{"text": text, "source_ids": ["s1"]}],
    }


def packet() -> dict:
    return {
        "sources": [
            {
                "id": "s1",
                "url": "https://www.vantaa.fi/fi/ajankohtaista/uutinen/esimerkki",
                "publisher": "Vantaan kaupunki",
                "title": "Esimerkki",
                "published_at": "2026-09-17",
            }
        ]
    }


def plain_public_html(text: str, address_html: str | None = None) -> str:
    """A public page: reviewed text, no image, correct placeholder.

    Mirrors what ``render_site`` emits: title, summary, the paragraphs, the
    source list (including every source URL), and the text-only placeholder.
    ``address_html`` lets a caller swap an obfuscated anchor in *after* escaping,
    which is how a CDN does it — the surrounding prose is escaped, the injected
    markup is not.
    """
    body = escape(text)
    if address_html is not None:
        body = body.replace(escape(ADDRESS), address_html)
    d = draft_with(text)
    p = packet()
    source_items = "".join(
        f'<li><a href="{escape(s["url"])}">{escape(s["publisher"])}: '
        f'{escape(s["title"])}</a></li>'
        for s in p["sources"]
    )
    return (
        "<!doctype html><html><body>"
        f"<h1>{escape(d['title'])}</h1>"
        f"<p class=\"summary\">{escape(d['summary'])}</p>"
        f"<p>{body}</p>"
        '<p class="image-note">Tämä uutinen julkaistaan ilman kuvaa.</p>'
        f"<ul>{source_items}</ul>"
        "</body></html>"
    )


class CdnEmailObfuscation(unittest.TestCase):
    def test_obfuscated_address_still_satisfies_the_contract(self):
        """The served page is correct content; proxy rewriting must not fail it."""
        served = plain_public_html(PARAGRAPH, address_html=cf_link(ADDRESS))
        # Precondition: the served page really is obfuscated, so this test would
        # be vacuous if the fixture were not exercising the transform.
        self.assertIn("data-cfemail", served)
        self.assertNotIn(ADDRESS, served)

        check_article(served, packet(), draft_with(PARAGRAPH))  # must not raise

    def test_deobfuscation_restores_the_exact_address(self):
        served = cf_link(ADDRESS)
        restored = _denormalize_cdn_email_obfuscation(served)
        self.assertEqual(restored, ADDRESS)

    def test_genuine_content_divergence_still_fails(self):
        """The relaxation must not weaken real content verification."""
        served = plain_public_html(PARAGRAPH).replace(ADDRESS, "jokin.muu@example.fi")
        with self.assertRaises(ValueError):
            check_article(served, packet(), draft_with(PARAGRAPH))

    def test_missing_paragraph_still_fails(self):
        served = plain_public_html("Aivan eri teksti kuin reviewed sisältö.")
        with self.assertRaises(ValueError):
            check_article(served, packet(), draft_with(PARAGRAPH))

    def test_malformed_obfuscation_is_left_untouched(self):
        """A non-hex payload must not be silently decoded to garbage."""
        broken = '<a href="/cdn-cgi/l/email-protection" data-cfemail="zz">x</a>'
        self.assertEqual(_denormalize_cdn_email_obfuscation(broken), broken)

    def test_short_payload_is_left_untouched(self):
        broken = '<a href="/cdn-cgi/l/email-protection" data-cfemail="2d">x</a>'
        self.assertEqual(_denormalize_cdn_email_obfuscation(broken), broken)


if __name__ == "__main__":
    unittest.main()