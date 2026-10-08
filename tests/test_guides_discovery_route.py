"""Focused, secret-free checks for the curated Oppaat discovery route."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_mvp import site
from news_mvp.editorial import digest


HELSINKI_ID = "9c818b9e83818ccf047a7fce9a4c2657f551f5abe743370f60b812af3bd5ed56"
VANTAA_ID = "f1f023667c0fcb8fd1fc1a0b600cb91c32c7d5717e765892463169e1c4aedcfa"
OULU_URL = "https://www.ouka.fi/fiilis"
OULU_HEADING = "Lisää syyslomatekemistä"
OULU_DESCRIPTION = (
    "Oulu: kaupungin Fiilis-sivulle on koottu lasten ja nuorten toimintaa "
    "syyslomalle 19.–23.10.2026. Tarkista tapahtumien ikärajat, hinnat ja "
    "ilmoittautuminen kaupungin sivulta."
)
OULU_LABEL = "Linkki kaupungin palvelusivulle – ei Uutistenlukijan uutisjuttu."
OULU_ANCHOR = "Oulun kaupungin syyslomatoiminta"
TURKU_URL = (
    "https://www.turku.fi/ajankohtaista/"
    "turussa-tapahtuu-syyslomalla-joka-paiva"
)
TURKU_DESCRIPTION = (
    "Turku: kaupungin ohjelmakoosteessa on tekemistä lasten ja nuorten syyslomalle "
    "12.–18.10.2026. Tarkista maksut, ikärajat ja ennakkovaraukset tapahtuman tiedoista."
)
TURKU_LABEL = "Linkki kaupungin ohjelmakoosteeseen – ei Uutistenlukijan uutisjuttu."
TURKU_ANCHOR = "Turun kaupungin syyslomaohjelma"
JYVASKYLA_URL = "https://www.jyvaskyla.fi/harrastukset/lomalokki"
JYVASKYLA_DESCRIPTION = (
    "Jyväskylän Lomalokki kokoaa syyslomatekemistä lapsille, nuorille ja perheille. "
    "Tarkista järjestäjän ohjelmasta ikärajat, hinnat ja ilmoittautuminen."
)
JYVASKYLA_LABEL = "Linkki kaupungin ohjelmakoosteeseen – ei Uutistenlukijan uutisjuttu."
JYVASKYLA_ANCHOR = "Jyväskylän kaupungin Lomalokki"
KUOPIO_URL = "https://www.kuopionseina.fi/tapahtumat/?event-search-s=Supersyysloma"
KUOPIO_DESCRIPTION = (
    "Kuopion kaupungin tapahtumakalenterista löytyy syyslomatekemistä lapsille ja nuorille. "
    "Tarkista tapahtuman ikärajat, hinnat ja ilmoittautuminen järjestäjältä."
)
KUOPIO_LABEL = "Linkki kaupungin tapahtumakalenteriin – ei Uutistenlukijan uutisjuttu."
KUOPIO_ANCHOR = "Kuopion kaupungin syyslomakalenteri"
ESPOO_URL = "https://www.espoo.fi/fi/lomatekemista"
ESPOO_DESCRIPTION = (
    "Espoon kaupungin sivulta löytyy lomatekemistä lapsille ja nuorille. "
    "Tarkista ohjelmasta ikärajat, maksut ja ilmoittautumisen määräajat."
)
ESPOO_LABEL = "Linkki Espoon kaupungin lomaohjelmaan – ei Uutistenlukijan uutisjuttu."
ESPOO_ANCHOR = "Espoon kaupungin lomaohjelma"
TAMPERE_URL = "https://www.tampere.fi/ajankohtaista/syyslomalla-tapahtuu-2026"
TAMPERE_DESCRIPTION = (
    "Tampereen kaupungin sivulle on koottu syyslomatekemistä lapsille, nuorille ja perheille. "
    "Tarkista järjestäjiltä ikärajat, hinnat ja ilmoittautuminen."
)
TAMPERE_LABEL = (
    "Linkki Tampereen kaupungin syyslomaohjelmaan – ei Uutistenlukijan uutisjuttu."
)
TAMPERE_ANCHOR = "Tampereen kaupungin syyslomaohjelma"
TYRES_URL = (
    "https://www.traficom.fi/fi/autoilijat/"
    "vinkkeja-liikenteeseen/auton-kesa-ja-talvirenkaat"
)
TYRES_HEADING = "Talvirenkaat: tarkista sää, keli ja renkaiden kunto"
TYRES_DESCRIPTION = (
    "Henkilö- ja pakettiautoissa talvirenkaita on käytettävä marraskuusta maaliskuuhun, "
    "jos sää tai keli sitä edellyttää. Nastarenkaita saa käyttää samana aikana ja muulloinkin, "
    "kun sää tai keli sitä vaatii. Talvirenkaiden pääurien lakisääteinen vähimmäissyvyys on "
    "3 mm; vaikeissa oloissa Traficom suosittelee vähintään 5 mm."
)
TYRES_LABEL = "Viranomaisen ohje – ei uusi uutisjuttu."
TYRES_ANCHOR = "Traficomin ohje kesä- ja talvirenkaista"
TYRES_SECTION = (
    '<section class="portal-list-page" aria-labelledby="oppaat-talvirenkaat-title">'
    '<header class="portal-list-header">'
    f'<p class="portal-list-header__eyebrow">{TYRES_LABEL}</p>'
    '<div class="portal-list-header__title">'
    f'<h2 id="oppaat-talvirenkaat-title">{TYRES_HEADING}</h2></div>'
    f'<p>{TYRES_DESCRIPTION}</p>'
    f'<p class="empty-recovery"><a href="{TYRES_URL}" rel="noopener noreferrer">'
    f'{TYRES_ANCHOR}</a></p>'
    '</header></section>'
)
REFLECTOR_GUIDE_URL = "https://www.liikenneturva.fi/liikenteessa/heijastin/"
REFLECTOR_TEST_URL = "https://extrat.liikenneturva.fi/heijastin/"
REFLECTOR_HEADING = "Heijastin: näy pimeällä"
REFLECTOR_DESCRIPTION = (
    "Pimeällä liikkuessa heijastin auttaa autoilijaa huomaamaan jalankulkijan. "
    "Tarkista heijastimen sijoittaminen Liikenneturvan ohjeesta ja kokeile havaintotestissä, "
    "miten heijastinliivi muuttaa näkyvyyttä."
)
REFLECTOR_LABEL = "Liikenneturvan ohje ja havaintotesti – ei uusi uutisjuttu."
REFLECTOR_GUIDE_ANCHOR = "Liikenneturvan heijastinohje"
REFLECTOR_TEST_ANCHOR = "Kokeile näkyvyyttä havaintotestissä"
REFLECTOR_SECTION = (
    '<section class="portal-list-page" aria-labelledby="oppaat-heijastin-title">'
    '<header class="portal-list-header">'
    f'<p class="portal-list-header__eyebrow">{REFLECTOR_LABEL}</p>'
    '<div class="portal-list-header__title">'
    f'<h2 id="oppaat-heijastin-title">{REFLECTOR_HEADING}</h2></div>'
    f'<p>{REFLECTOR_DESCRIPTION}</p>'
    f'<p class="empty-recovery"><a href="{REFLECTOR_GUIDE_URL}" '
    f'rel="noopener noreferrer">{REFLECTOR_GUIDE_ANCHOR}</a></p>'
    f'<p class="empty-recovery"><a href="{REFLECTOR_TEST_URL}" '
    f'rel="noopener noreferrer">{REFLECTOR_TEST_ANCHOR}</a></p>'
    '</header></section>'
)


def listing_item(job_id, label):
    job = {"id": job_id, "created_at": f"2026-10-0{label}T10:0{label}:00+00:00"}
    draft = {
        "category": "Kulttuuri",
        "title": f"Alkuperäinen otsikko {label}",
        "summary": f"Alkuperäinen tiivistelmä {label}",
    }
    link = f"/uutiset/alkuperainen-{label}/"
    date = f"alkuperäinen päivä {label}"
    image = {"alt": f"Alkuperäinen vaihtoehtoteksti {label}", "width": 640, "height": 480}
    image_url = f"/mvp-assets/images/alkuperainen-{label}.jpg"
    return (job, draft, link, date, "", image, image_url)


def rendered_job(job_id, label):
    image = {
        "url": f"https://example.invalid/image-{label}.jpg",
        "source_url": f"https://example.invalid/source-{label}",
        "license_url": "https://example.invalid/image-terms",
        "license": "Synthetic test terms",
        "credit": "Synthetic test credit",
        "alt": f"Synthetic guide image {label}",
        "width": 640,
        "height": 480,
    }
    packet = {
        "fixture": True,
        "story_key": f"guides-route-{label}",
        "sources": [{
            "id": "A",
            "url": f"https://example.invalid/source-{label}",
            "publisher": f"Synthetic publisher {label}",
            "title": f"Synthetic source {label}",
            "published_at": f"2026-10-0{label}T08:00:00+00:00",
        }],
        "image": image,
    }
    draft = {
        "category": "Kulttuuri",
        "title": f"Alkuperäinen otsikko {label}",
        "summary": f"Alkuperäinen tiivistelmä {label}",
        "paragraphs": [
            {"text": f"Ensimmäinen synteettinen kappale {label}.", "source_ids": ["A"]},
            {"text": f"Toinen synteettinen kappale {label}.", "source_ids": ["A"]},
        ],
        "image": image,
    }
    review = {
        "approved": True,
        "draft_sha256": digest(draft),
        "reasons": ["Synthetic route regression fixture."],
    }
    return {
        "id": job_id,
        "created_at": f"2026-10-0{label}T10:0{label}:00+00:00",
        "packet": json.dumps(packet),
        "draft": json.dumps(draft),
        "review": json.dumps(review),
    }


class FakeStore:
    def __init__(self, jobs):
        self.jobs = jobs

    def articles(self):
        return list(self.jobs)

    def mark_rendered(self, _ids):
        pass


class GuidesDiscoveryRoute(unittest.TestCase):
    def render_guides(self, jobs):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            with patch("news_mvp.release_contract.media"):
                site.render_site(FakeStore(jobs), output, public=True)
            return (
                (output / "oppaat/index.html").read_text(encoding="utf-8"),
                (output / "rss.xml").read_text(encoding="utf-8"),
            )

    def test_exact_reviewed_ids_are_selected_in_supplied_order_without_mutation(self):
        vantaa = listing_item(VANTAA_ID, 1)
        old_conflicting = listing_item("2684ca78-unresolved-old-story", 2)
        unrelated = listing_item("unrelated-story", 3)
        helsinki = listing_item(HELSINKI_ID, 4)
        prefix_only = listing_item(HELSINKI_ID + "-not-exact", 5)

        selected = site.guides_listing_items(
            [vantaa, old_conflicting, unrelated, helsinki, prefix_only]
        )

        self.assertEqual(selected, [vantaa, helsinki])
        self.assertIs(selected[0], vantaa)
        self.assertIs(selected[1], helsinki)
        body = site.category_page_body(
            "Oppaat", site.GUIDES_DESCRIPTION, selected,
            "Oppaita ei ole vielä julkaistu.", recovery_html=site.recovery_links_html(),
        )
        self.assertIn("2 juttua", body)
        for item in selected:
            job, draft, link, date, fixture, image, image_url = item
            self.assertIn(link, body)
            self.assertIn(draft["title"], body)
            self.assertIn(draft["summary"], body)
            self.assertIn(site.time_html(job["created_at"], "portal-feed-item__time"), body)
            self.assertIn(image["alt"], body)
            self.assertIn(image_url, body)
            self.assertEqual(item[3], date)
            self.assertEqual(item[4], fixture)
        self.assertLess(body.index(vantaa[2]), body.index(helsinki[2]))
        self.assertNotIn(old_conflicting[2], body)
        self.assertNotIn(unrelated[2], body)
        self.assertNotIn(prefix_only[2], body)

    def test_metadata_uses_the_same_selected_items_and_collection_description(self):
        selected = site.guides_listing_items([
            listing_item(VANTAA_ID, 1),
            listing_item("2684ca78-unresolved-old-story", 2),
            listing_item(HELSINKI_ID, 4),
        ])
        description = site.guides_description(selected)
        self.assertEqual(
            description,
            "Syysloman 2026 menovinkit ja linkit kaupunkien ohjelmiin sekä "
            "viranomaisohjeita syksyn arkeen. Tarkista ajantasaiset tiedot "
            "alkuperäisistä lähteistä.",
        )

        metadata = site.homepage_head_meta(
            selected, path=site.OPPAAT_PATH, page_title="Oppaat",
            description=description,
        )
        self.assertIn(
            f'<meta name="description" content="{site.GUIDES_DESCRIPTION}">', metadata
        )
        payloads = [
            json.loads(raw) for raw in re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', metadata
            )
        ]
        item_lists = [payload for payload in payloads if payload.get("@type") == "ItemList"]
        self.assertEqual(len(item_lists), 1)
        self.assertEqual(
            item_lists[0]["itemListElement"],
            [
                {
                    "@type": "ListItem",
                    "position": position,
                    "url": site.SITE_URL.rstrip("/") + item[2],
                    "name": item[1]["title"],
                }
                for position, item in enumerate(selected, 1)
            ],
        )
        self.assertFalse(any(payload.get("@type") == "NewsArticle" for payload in payloads))

    def test_rendered_route_keeps_curated_references_outside_two_article_inventory(self):
        vantaa = rendered_job(VANTAA_ID, 1)
        unrelated = rendered_job("unrelated-story", 2)
        helsinki = rendered_job(HELSINKI_ID, 3)

        page, rss = self.render_guides([vantaa, unrelated, helsinki])
        original_links = ["/" + site.article_path(job) for job in (vantaa, helsinki)]

        self.assertIn('<p class="archive-count">2 juttua</p>', page)
        self.assertEqual(page.count('<article class="portal-feed-item'), 2)
        self.assertLess(page.index(original_links[0]), page.index(original_links[1]))
        for link in original_links:
            self.assertIn(f'href="{link}"', page)
        self.assertEqual(page.count(f'href="{OULU_URL}"'), 1)
        self.assertIn(
            f'<a href="{OULU_URL}" rel="noopener noreferrer">{OULU_ANCHOR}</a>', page
        )
        self.assertEqual(page.count(OULU_HEADING), 1)
        self.assertEqual(page.count(OULU_DESCRIPTION), 1)
        self.assertEqual(page.count(OULU_LABEL), 1)
        self.assertLess(page.index(original_links[1]), page.index(OULU_HEADING))
        self.assertEqual(page.count(f'href="{TURKU_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{TURKU_URL}" rel="noopener noreferrer">{TURKU_ANCHOR}</a>'
            ),
            1,
        )
        self.assertEqual(page.count(TURKU_DESCRIPTION), 1)
        self.assertEqual(page.count(TURKU_LABEL), 2)
        self.assertLess(page.index(OULU_ANCHOR), page.index(TURKU_LABEL))
        self.assertEqual(page.count(f'href="{JYVASKYLA_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{JYVASKYLA_URL}" rel="noopener noreferrer">'
                f'{JYVASKYLA_ANCHOR}</a>'
            ),
            1,
        )
        self.assertEqual(page.count(JYVASKYLA_DESCRIPTION), 1)
        self.assertEqual(page.count(JYVASKYLA_LABEL), 2)
        self.assertLess(page.index(TURKU_ANCHOR), page.index(JYVASKYLA_ANCHOR))
        self.assertEqual(page.count(f'href="{KUOPIO_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{KUOPIO_URL}" rel="noopener noreferrer">{KUOPIO_ANCHOR}</a>'
            ),
            1,
        )
        self.assertEqual(page.count(KUOPIO_DESCRIPTION), 1)
        self.assertEqual(page.count(KUOPIO_LABEL), 1)
        self.assertLess(page.index(JYVASKYLA_ANCHOR), page.index(KUOPIO_ANCHOR))
        self.assertEqual(page.count(f'href="{ESPOO_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{ESPOO_URL}" rel="noopener noreferrer">{ESPOO_ANCHOR}</a>'
            ),
            1,
        )
        self.assertEqual(page.count(ESPOO_DESCRIPTION), 1)
        self.assertEqual(page.count(ESPOO_LABEL), 1)
        self.assertLess(page.index(KUOPIO_ANCHOR), page.index(ESPOO_LABEL))
        self.assertEqual(page.count(f'href="{TAMPERE_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{TAMPERE_URL}" rel="noopener noreferrer">'
                f'{TAMPERE_ANCHOR}</a>'
            ),
            1,
        )
        self.assertEqual(page.count(TAMPERE_DESCRIPTION), 1)
        self.assertEqual(page.count(TAMPERE_LABEL), 1)
        self.assertLess(page.index(ESPOO_ANCHOR), page.index(TAMPERE_LABEL))
        self.assertEqual(page.count(TYRES_SECTION), 1)
        self.assertEqual(page.count(TYRES_HEADING), 1)
        self.assertEqual(page.count(TYRES_DESCRIPTION), 1)
        self.assertEqual(page.count(TYRES_LABEL), 1)
        self.assertEqual(page.count(f'href="{TYRES_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{TYRES_URL}" rel="noopener noreferrer">{TYRES_ANCHOR}</a>'
            ),
            1,
        )
        self.assertLess(page.index(TAMPERE_ANCHOR), page.index(TYRES_SECTION))
        self.assertEqual(page.count(REFLECTOR_SECTION), 1)
        self.assertEqual(page.count(REFLECTOR_HEADING), 1)
        self.assertEqual(page.count(REFLECTOR_DESCRIPTION), 1)
        self.assertEqual(page.count(REFLECTOR_LABEL), 1)
        self.assertEqual(page.count(f'href="{REFLECTOR_GUIDE_URL}"'), 1)
        self.assertEqual(page.count(f'href="{REFLECTOR_TEST_URL}"'), 1)
        self.assertEqual(
            page.count(
                f'<a href="{REFLECTOR_GUIDE_URL}" rel="noopener noreferrer">'
                f'{REFLECTOR_GUIDE_ANCHOR}</a>'
            ),
            1,
        )
        self.assertEqual(
            page.count(
                f'<a href="{REFLECTOR_TEST_URL}" rel="noopener noreferrer">'
                f'{REFLECTOR_TEST_ANCHOR}</a>'
            ),
            1,
        )
        self.assertLess(page.index(TYRES_SECTION), page.index(REFLECTOR_SECTION))

        payloads = [
            json.loads(raw) for raw in re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', page
            )
        ]
        self.assertEqual([payload.get("@type") for payload in payloads], ["WebSite", "ItemList"])
        item_list = payloads[1]["itemListElement"]
        self.assertEqual(
            [item["url"] for item in item_list],
            [site.SITE_URL.rstrip("/") + link for link in original_links],
        )
        self.assertNotIn(OULU_URL, json.dumps(payloads))
        self.assertNotIn(TURKU_URL, json.dumps(payloads))
        self.assertNotIn(JYVASKYLA_URL, json.dumps(payloads))
        self.assertNotIn(KUOPIO_URL, json.dumps(payloads))
        self.assertNotIn(ESPOO_URL, json.dumps(payloads))
        self.assertNotIn(TAMPERE_URL, json.dumps(payloads))
        self.assertNotIn(TYRES_URL, json.dumps(payloads))
        self.assertNotIn(REFLECTOR_GUIDE_URL, json.dumps(payloads))
        self.assertNotIn(REFLECTOR_TEST_URL, json.dumps(payloads))
        self.assertNotIn(OULU_URL, rss)
        self.assertNotIn(TURKU_URL, rss)
        self.assertNotIn(JYVASKYLA_URL, rss)
        self.assertNotIn(KUOPIO_URL, rss)
        self.assertNotIn(ESPOO_URL, rss)
        self.assertNotIn(TAMPERE_URL, rss)
        self.assertNotIn(TYRES_URL, rss)
        self.assertNotIn(REFLECTOR_GUIDE_URL, rss)
        self.assertNotIn(REFLECTOR_TEST_URL, rss)

    def test_rendered_reference_stays_separate_with_zero_or_one_selected_article(self):
        unrelated = rendered_job("unrelated-story", 2)
        helsinki = rendered_job(HELSINKI_ID, 3)

        for jobs, expected_count in (([unrelated], 0), ([unrelated, helsinki], 1)):
            with self.subTest(selected=expected_count):
                page, rss = self.render_guides(jobs)
                self.assertIn(
                    f'<p class="archive-count">{expected_count} '
                    f'{"juttu" if expected_count == 1 else "juttua"}</p>',
                    page,
                )
                self.assertEqual(page.count('<article class="portal-feed-item'), expected_count)
                self.assertEqual(page.count(f'href="{OULU_URL}"'), 1)
                self.assertEqual(page.count(f'href="{TURKU_URL}"'), 1)
                self.assertEqual(page.count(f'href="{JYVASKYLA_URL}"'), 1)
                self.assertEqual(page.count(f'href="{KUOPIO_URL}"'), 1)
                self.assertEqual(page.count(f'href="{ESPOO_URL}"'), 1)
                self.assertEqual(page.count(f'href="{TAMPERE_URL}"'), 1)
                self.assertEqual(page.count(TURKU_ANCHOR), 1)
                self.assertEqual(page.count(JYVASKYLA_ANCHOR), 1)
                self.assertEqual(page.count(KUOPIO_ANCHOR), 1)
                self.assertEqual(
                    page.count(
                        f'<a href="{ESPOO_URL}" rel="noopener noreferrer">'
                        f'{ESPOO_ANCHOR}</a>'
                    ),
                    1,
                )
                self.assertEqual(
                    page.count(
                        f'<a href="{TAMPERE_URL}" rel="noopener noreferrer">'
                        f'{TAMPERE_ANCHOR}</a>'
                    ),
                    1,
                )
                self.assertEqual(page.count(JYVASKYLA_LABEL), 2)
                self.assertEqual(page.count(KUOPIO_LABEL), 1)
                self.assertEqual(page.count(ESPOO_LABEL), 1)
                self.assertEqual(page.count(TAMPERE_DESCRIPTION), 1)
                self.assertEqual(page.count(TAMPERE_LABEL), 1)
                self.assertLess(page.index(ESPOO_ANCHOR), page.index(TAMPERE_LABEL))
                self.assertEqual(page.count(TYRES_SECTION), 1)
                self.assertLess(page.index(TAMPERE_ANCHOR), page.index(TYRES_SECTION))
                self.assertEqual(page.count(REFLECTOR_SECTION), 1)
                self.assertEqual(page.count(REFLECTOR_HEADING), 1)
                self.assertEqual(page.count(REFLECTOR_DESCRIPTION), 1)
                self.assertEqual(page.count(REFLECTOR_LABEL), 1)
                self.assertEqual(page.count(f'href="{REFLECTOR_GUIDE_URL}"'), 1)
                self.assertEqual(page.count(f'href="{REFLECTOR_TEST_URL}"'), 1)
                self.assertEqual(
                    page.count(
                        f'<a href="{REFLECTOR_GUIDE_URL}" rel="noopener noreferrer">'
                        f'{REFLECTOR_GUIDE_ANCHOR}</a>'
                    ),
                    1,
                )
                self.assertEqual(
                    page.count(
                        f'<a href="{REFLECTOR_TEST_URL}" rel="noopener noreferrer">'
                        f'{REFLECTOR_TEST_ANCHOR}</a>'
                    ),
                    1,
                )
                self.assertLess(page.index(TYRES_SECTION), page.index(REFLECTOR_SECTION))
                self.assertIn(
                    '</div><section class="portal-list-page" '
                    'aria-labelledby="oppaat-lisaa-title">',
                    page,
                )
                if expected_count == 0:
                    self.assertLess(page.index('class="empty-recovery"'), page.index(OULU_HEADING))
                else:
                    original_link = "/" + site.article_path(helsinki)
                    self.assertLess(page.index(original_link), page.index(OULU_HEADING))
                payloads = [
                    json.loads(raw) for raw in re.findall(
                        r'<script type="application/ld\+json">(.*?)</script>', page
                    )
                ]
                item_lists = [payload for payload in payloads if payload.get("@type") == "ItemList"]
                self.assertEqual(len(item_lists), 1)
                self.assertEqual(len(item_lists[0]["itemListElement"]), expected_count)
                self.assertFalse(any(payload.get("@type") == "NewsArticle" for payload in payloads))
                self.assertNotIn(OULU_URL, json.dumps(payloads))
                self.assertNotIn(TURKU_URL, json.dumps(payloads))
                self.assertNotIn(JYVASKYLA_URL, json.dumps(payloads))
                self.assertNotIn(KUOPIO_URL, json.dumps(payloads))
                self.assertNotIn(ESPOO_URL, json.dumps(payloads))
                self.assertNotIn(TAMPERE_URL, json.dumps(payloads))
                self.assertNotIn(TYRES_URL, json.dumps(payloads))
                self.assertNotIn(REFLECTOR_GUIDE_URL, json.dumps(payloads))
                self.assertNotIn(REFLECTOR_TEST_URL, json.dumps(payloads))
                self.assertNotIn(TYRES_URL, rss)
                self.assertNotIn(REFLECTOR_GUIDE_URL, rss)
                self.assertNotIn(REFLECTOR_TEST_URL, rss)

    def test_empty_and_single_match_remain_truthful(self):
        unrelated = listing_item("unrelated-story", 3)
        self.assertEqual(site.guides_listing_items([unrelated]), [])
        empty = site.category_page_body(
            "Oppaat", site.GUIDES_DESCRIPTION, [],
            "Oppaita ei ole vielä julkaistu.", recovery_html=site.recovery_links_html(),
        )
        self.assertIn("0 juttua", empty)
        self.assertIn("Oppaita ei ole vielä julkaistu.", empty)
        self.assertIn('class="empty-recovery"', empty)
        self.assertEqual(site.guides_description([]), "Toimitukselliset oppaat ja taustat.")

        only = listing_item(HELSINKI_ID, 4)
        selected = site.guides_listing_items([unrelated, only])
        self.assertEqual(selected, [only])
        description = site.guides_description(selected)
        self.assertEqual(
            description,
            "Syysloman 2026 tapahtumajuttu Helsingistä. "
            "Tarkista ajantasainen ohjelma jutun lähteestä.",
        )
        one = site.category_page_body(
            "Oppaat", description, selected,
            "Oppaita ei ole vielä julkaistu.", recovery_html=site.recovery_links_html(),
        )
        self.assertIn("1 juttu", one)
        self.assertNotIn("Oppaita ei ole vielä julkaistu.", one)
        self.assertEqual(one.count('<article class="portal-feed-item'), 1)
        metadata = site.homepage_head_meta(
            selected, path=site.OPPAAT_PATH, page_title="Oppaat", description=description,
        )
        self.assertIn(f'<meta name="description" content="{description}">', metadata)
        self.assertEqual(metadata.count('"@type": "ListItem"'), 1)


if __name__ == "__main__":
    unittest.main()
