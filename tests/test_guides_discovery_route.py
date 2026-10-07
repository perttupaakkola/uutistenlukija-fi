"""Focused, secret-free checks for the curated Oppaat discovery route."""
import json
import re
import unittest

from news_mvp import site


HELSINKI_ID = "9c818b9e83818ccf047a7fce9a4c2657f551f5abe743370f60b812af3bd5ed56"
VANTAA_ID = "f1f023667c0fcb8fd1fc1a0b600cb91c32c7d5717e765892463169e1c4aedcfa"


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


class GuidesDiscoveryRoute(unittest.TestCase):
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
        self.assertIn("Helsingistä", description)
        self.assertNotIn("Vantaalta", description)
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
