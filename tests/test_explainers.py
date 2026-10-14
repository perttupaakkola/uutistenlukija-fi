import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_mvp.editorial import digest, validate_draft, validate_packet
from news_mvp.explainers import (SECTION_LABELS, build_packet, can_admit,
                                 daily_count, deterministic_relevance, pick_topics,
                                 policy_digest, story_key)
from news_mvp.release_contract import check_article, media
from news_mvp.site import article_path, render_site
from news_mvp.store import database


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
TEXT = " ".join(["Lähde kertoo päätöksen vaikutuksista, aikataulusta ja perusteista."] * 24)


def hit(url, title, published=NOW.isoformat(), text=TEXT):
    return {"url": url, "title": title, "published_at": published, "text": text}


def topic_search(query, limit):
    if "viranomainen" in query:
        return [hit("https://www.kela.fi/ajankohtaista-paatos", "Kelan päätös")]
    return [
        hit("https://www.mtv.fi/uutiset/paatos-vaikuttaa", "MTV kertoo Kelan päätöksestä"),
        hit("https://www.iltalehti.fi/politiikka/a/paatos", "IL kertoo Kelan päätöksestä"),
        hit("https://www.uusisuomi.fi/uutiset/paatos", "US kertoo Kelan päätöksestä"),
    ]


def relevant(_request):
    return {"relevant": True, "reason": "Lähde käsittelee otsikon toimijaa ja päätöstä."}


class Explainers(unittest.TestCase):
    def packet(self):
        topic = {"title": "Mitä Kelan päätös tarkoittaa", "story_key": "explainer:kela-paatos",
                 "outlet_count": 4, "coverage": topic_search("normal", 10)}
        packet = build_packet(topic, topic_search, now=NOW, relevance_checker=relevant)
        self.assertIsNotNone(packet)
        return packet

    def draft(self, image=None):
        paragraphs = []
        for index, label in enumerate(SECTION_LABELS):
            # Exactly 100 words per section: the schema's lower bound is exercised.
            words = [f"asia{index}"] * 100
            paragraphs.append({"section": label, "text": " ".join(words) + ".",
                               "source_ids": ["A", "B"]})
        return {"kind": "explainer", "title": "Mitä Kelan päätös tarkoittaa – vaikutukset",
                "summary": "Päätös muuttaa lähteissä kuvattuja etuuksia ja aikatauluja.",
                "category": "Kotimaa", "paragraphs": paragraphs, "image": image}

    def test_topic_picker_requires_three_outlets_and_skips_crime_and_dedupe(self):
        headlines = [
            {"title": "Kelan päätös vaikuttaa tukiin", "url": "https://yle.fi/a/1",
             "published_at": NOW.isoformat()},
            {"title": "Yksi lehti kertoo näyttelystä", "url": "https://example.fi/a",
             "published_at": NOW.isoformat()},
            {"title": "Poliisi tutkii murhaa", "url": "https://example.fi/rikos",
             "published_at": NOW.isoformat()},
            {"title": "Veropäätös vaikuttaa maksuihin", "url": "https://yle.fi/a/2",
             "published_at": NOW.isoformat()},
        ]
        def search(query, limit):
            if query.startswith("Kelan"):
                return [{"url": "https://mtvuutiset.fi/a", "title": query},
                        {"url": "https://is.fi/a", "title": query},
                        {"url": "https://vauva.fi/keskustelu/a", "title": query}]
            if query.startswith("Veropäätös"):
                return [{"url": "https://mtvuutiset.fi/b", "title": query},
                        {"url": "https://is.fi/b", "title": query}]
            return []
        topics = pick_topics(headlines, search,
                             {story_key("Veropäätös vaikuttaa maksuihin")})
        self.assertEqual([row["story_key"] for row in topics],
                         [story_key("Kelan päätös vaikuttaa tukiin")])
        self.assertEqual(topics[0]["outlet_count"], 3)

    def test_packet_excludes_headline_only_paywall_blocked_and_stt_text(self):
        topic = {"title": "Mitä Kelan päätös tarkoittaa", "story_key": "explainer:kela",
                 "outlet_count": 6, "coverage": [
                     hit("https://yle.fi/a/1", "Yle"),
                     hit("https://www.hs.fi/politiikka/art-1", "HS"),
                     hit("https://mirror.fi/a", "STT:n uutinen", text="STT " + TEXT),
                     *topic_search("normal", 10),
                 ]}
        packet = build_packet(topic, topic_search, now=NOW, relevance_checker=relevant)
        self.assertEqual([source["publisher"] for source in packet["sources"]],
                         ["kela.fi", "mtv.fi", "iltalehti.fi", "uusisuomi.fi"])
        self.assertNotIn("yle.fi", json.dumps(packet))
        self.assertEqual(packet["publication_basis"]["policy_sha256"], policy_digest())
        validate_packet(packet, NOW, 48)
        changed = copy.deepcopy(packet)
        changed["publication_basis"]["primary_relevance"]["model"]["relevant"] = False
        with self.assertRaisesRegex(ValueError, "not directly relevant"):
            validate_packet(changed, NOW, 48)

    def test_daily_cap_uses_helsinki_day(self):
        with tempfile.TemporaryDirectory() as temp, database(temp) as store:
            for index, created in enumerate(("2026-10-12T21:30:00+00:00",
                                             "2026-10-13T20:00:00+00:00")):
                packet = {"kind": "explainer", "story_key": f"explainer:{index}",
                          "sources": [{"url": f"https://example.fi/{index}"}]}
                store.admit(packet, created)
            self.assertEqual(daily_count(store, NOW), 2)
            self.assertFalse(can_admit(store, NOW, 2))

    def test_prompt_shape_route_render_and_release_contract(self):
        packet = self.packet()
        draft = self.draft()
        validate_draft(draft, packet)
        prompt = (Path(__file__).parents[1] / "prompts/explainer.md").read_text()
        self.assertIn("mitä hänen pitää tarkistaa tai tehdä", prompt)
        self.assertIn("Lähteissä ei kerrota suorasta vaikutuksesta", prompt)
        self.assertTrue((Path(__file__).parents[1] /
                         "prompts/explainer_source_relevance.md").is_file())
        self.assertEqual(media(packet, draft)["text_only"]["policy"],
                         "explainer-sources-v2")

    def test_he_157_2026_is_not_a_google_primary_and_reporting_falls_back_to_a(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "explainers" /
                              "he157-google.json").read_text())
        topic = fixture["topic"]
        checked = []

        def search(query, limit):
            return fixture["official_hits"] if "viranomainen" in query else fixture["reports"]

        def checker(request):
            checked.append(request["candidate"]["url"])
            return {"relevant": True, "reason": "Raportti käsittelee Googlea ja Muhosta."}

        he = fixture["official_hits"][0]
        overlap = deterministic_relevance(topic["title"], he)
        self.assertFalse(overlap["passed"])
        self.assertEqual(overlap["matched_terms"], [])
        packet = build_packet(topic, search, now=NOW, relevance_checker=checker)
        self.assertIsNotNone(packet)
        self.assertEqual(packet["sources"][0]["primary_type"], "original_reporting")
        self.assertNotEqual(packet["sources"][0]["url"], he["url"])
        self.assertNotIn(he["url"], checked)
        validate_packet(packet, NOW, 48)

    def test_reader_impact_outranks_and_filters_corporate_regulatory_dispute(self):
        headlines = [
            {"title": "Google kiistää viraston datakeskustulkinnan",
             "url": "https://yle.fi/a/corporate", "published_at": NOW.isoformat()},
            {"title": "Suomeen tuli kolmen miljoonan Eurojackpot-voitto",
             "url": "https://yle.fi/a/lottery", "published_at": NOW.isoformat()},
            {"title": "Tuhannen euron pizzatilaus yllätti ravintolan",
             "url": "https://yle.fi/a/pizza", "published_at": NOW.isoformat()},
            {"title": "Kelan asumistuki muuttuu – tarkista maksupäivä",
             "url": "https://yle.fi/a/benefit", "published_at": NOW.isoformat()},
        ]

        def search(query, limit):
            suffix = ("corp" if query.startswith("Google") else
                      "lottery" if "Eurojackpot" in query else "benefit")
            hits = [{"url": f"https://mtvuutiset.fi/{suffix}", "title": query},
                    {"url": f"https://is.fi/{suffix}", "title": query}]
            if suffix in ("corp", "lottery"):
                hits += [{"url": "https://iltalehti.fi/corp", "title": query},
                         {"url": "https://uusisuomi.fi/corp", "title": query}]
            return hits

        topics = pick_topics(headlines, search)
        self.assertEqual([row["title"] for row in topics],
                         ["Kelan asumistuki muuttuu – tarkista maksupäivä"])
        self.assertGreater(topics[0]["impact_score"], 0)
        self.assertIn("benefits", topics[0]["impact_reasons"])

    def test_model_relevance_can_reject_overlap_and_force_reporting_fallback(self):
        reports = [
            hit("https://www.mtv.fi/uutiset/asumistuki", "Kelan asumistuki muuttuu"),
            hit("https://www.iltalehti.fi/politiikka/a/asumistuki", "Asumistuen muutos"),
            hit("https://www.uusisuomi.fi/uutiset/asumistuki", "Kelan asumistuen muutos"),
        ]
        topic = {"title": "Kelan asumistuki muuttuu", "story_key": "explainer:kela",
                 "outlet_count": 3, "coverage": reports}

        def search(query, limit):
            if "viranomainen" in query:
                return [hit("https://www.kela.fi/ajankohtaista-paatos",
                            "Kelan päätös asumistuesta")]
            return reports

        def checker(request):
            official = request["candidate"]["publisher"] == "kela.fi"
            return {"relevant": not official,
                    "reason": "Asiakirja on eri Kelan päätöksestä." if official else
                              "Raportti käsittelee asumistuen muutosta."}

        self.assertIsNone(build_packet(topic, search, now=NOW))
        packet = build_packet(topic, search, now=NOW, relevance_checker=checker)
        self.assertEqual(packet["sources"][0]["primary_type"], "original_reporting")
        self.assertNotEqual(packet["sources"][0]["publisher"], "kela.fi")
        self.assertTrue(packet["publication_basis"]["primary_relevance"]["model"]["relevant"])

        raw = b"\xff\xd8\xffexplainer-test-image"
        sha = hashlib.sha256(raw).hexdigest()
        image = {"generated": True, "sha256": sha, "local_path": f"media/{sha}.jpg",
                 "url": "https://uutistenlukija.fi/ai-kuvat/", "source_url": "https://uutistenlukija.fi/ai-kuvat/",
                 "license_url": "https://uutistenlukija.fi/ai-kuvat/", "license": "AI",
                 "credit": "AI-kuvitus", "alt": "AI-generoitu kuva: Kelan päätöstä kuvaavia asiakirjoja pöydällä.",
                 "caption": "AI-generoitu kuva. Ei valokuva tapahtumasta.", "model": "fixture",
                 "prompt_sha256": "1" * 64, "prompt_version": "fixture-v1", "subject": "asiakirjat"}
        packet = {**packet, "image": image}
        packet.pop("image_note", None)
        draft = self.draft(image)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "state/media").mkdir(parents=True)
            (root / f"state/media/{sha}.jpg").write_bytes(raw)
            with database(root / "state") as store:
                identifier, _ = store.admit(packet, NOW.isoformat())
                store.save_draft(identifier, draft, "fixture")
                store.finish_review(identifier, {"approved": True, "fixable": False,
                    "draft_sha256": digest(draft), "reasons": ["Fixture review"]})
                job = store.get(identifier)
                render_site(store, root / "site", root / "state", public=True)
            route = "/" + article_path(job)
            self.assertIn("/uutiset/selittaja-", route)
            html = (root / "site" / article_path(job) / "index.html").read_text()
            self.assertIn('<p class="article-kicker">Selittäjä</p>', html)
            self.assertIn('"articleSection":"explainer"', html)
            check_article(html, packet, draft,
                          canonical="https://uutistenlukija.fi" + route)


if __name__ == "__main__":
    unittest.main()
