#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from . import audit_image_flow
except ImportError:  # pragma: no cover
    import audit_image_flow


FINANCE_ID = "finReg12345"
FINANCE_PAGE = (
    "https://unsplash.com/photos/"
    f"financial-regulation-compliance-documents-{FINANCE_ID}"
)
SNOW_PAGE = (
    "https://unsplash.com/photos/"
    "brown-wooden-fence-filled-with-snow-during-winter-rxLGSOM0e3U"
)
RAIL_PARIS_PAGE = (
    "https://unsplash.com/photos/"
    "railway-tracks-and-construction-in-paris-france-railParis12"
)
TV_BOOKS_PAGE = (
    "https://unsplash.com/photos/"
    "television-on-a-shelf-with-books-tvBooks123x"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFLICT_PACKET = (
    PROJECT_ROOT
    / "pipeline/queues/staged/published/20260901T175739Z_fa5ef5b7ff.json"
)
CONFLICT_ARTICLE = (
    PROJECT_ROOT
    / "content/posts/2026-09-01-yhdysvallat-iski-larakin-saarelle-iran-ilmoitti-ohjusiskuist.md"
)


def _write_post(
    path: Path,
    *,
    title: str = "Rahastoyhtiöiden rekisterivelvoitetta muutetaan",
    date: str = "2026-09-02T12:00:00+00:00",
    description: str = "Finanssisääntelyä ja hallinnollista velvoitetta muutetaan.",
    summary: str = "Muutos koskee rahastoyhtiöiden sisäpiirirekisteriä.",
    key_points: tuple[str, ...] = ("Rahastoyhtiöiden compliance-velvoite muuttuu.",),
    body: str = "EU-sääntely korvaa kansallista sisäpiirirekisteriä.",
    candidate_id: str = FINANCE_ID,
    source_page: str = FINANCE_PAGE,
    image_alt: str = "snowy winter weather",
    image_query: str = "winter weather",
) -> None:
    key_point_lines = "\n".join(f'  - "{value}"' for value in key_points)
    path.write_text(
        "---\n"
        f'title: "{title}"\n'
        f"date: {date}\n"
        "categories:\n  - Talous\n"
        f'description: "{description}"\n'
        f'summary: "{summary}"\n'
        "key_points:\n"
        f"{key_point_lines}\n"
        f'image: "https://images.unsplash.com/photo-{candidate_id}x?w=1080"\n'
        f'image_alt: "{image_alt}"\n'
        f'image_source_url: "{source_page}"\n'
        'image_source: "unsplash"\n'
        f'image_query: "{image_query}"\n'
        f'image_candidate_id: "{candidate_id}"\n'
        f'image_candidate_url: "{source_page}"\n'
        "image_category_fallback: false\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


class IndependentImageAuditTests(unittest.TestCase):
    def test_descriptive_photo_of_provider_slug_remains_semantic_evidence(self) -> None:
        tokens = audit_image_flow._provider_page_tokens(
            "pexels",
            {
                "image_candidate_id": "12345",
                "image_source_url": (
                    "https://www.pexels.com/photo/"
                    "photo-of-a-persons-hand-taking-out-a-golf-ball-12345/"
                ),
            },
        )

        self.assertTrue({"persons", "hand", "taking", "golf", "ball"} <= tokens)

    def test_final_alt_and_query_neither_create_nor_rescue_article_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            relevant = posts / "2026-09-02-relevant.md"
            unrelated = posts / "2026-09-02-unrelated.md"
            _write_post(
                relevant,
                image_alt="snow-covered fence in winter",
                image_query="winter weather",
            )
            _write_post(
                unrelated,
                date="2026-09-02T13:00:00+00:00",
                candidate_id="rxLGSOM0e3U",
                source_page=SNOW_PAGE,
                image_alt="Rahastoyhtiöiden rekisterivelvoitetta muutetaan",
                image_query="financial regulation documents",
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                rows = {Path(row["file"]).name: row for row in audit_image_flow.audit_recent(2)}

        self.assertEqual(rows[relevant.name]["status"], "ok")
        self.assertEqual(rows[unrelated.name]["status"], "flag")
        self.assertIn("candidate unrelated", str(rows[unrelated.name]["reason"]))

    def test_audit_truth_is_independent_from_runtime_intent_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-finance-snow.md"
            _write_post(
                post,
                candidate_id="rxLGSOM0e3U",
                source_page=SNOW_PAGE,
            )
            poisoned_runtime_intent = SimpleNamespace(
                subject="winter weather",
                must_have=["weather conditions"],
                locations=[],
                evidence_terms=["snow", "winter", "weather"],
                season_time="winter",
                stock_ok=True,
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts), patch.object(
                audit_image_flow,
                "build_image_intent",
                return_value=poisoned_runtime_intent,
                create=True,
            ):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("unrelated", str(row["reason"]))

    def test_finnish_regulation_token_is_not_weather_or_season_evidence(self) -> None:
        truth = audit_image_flow._derive_audit_truth(
            {
                "title": "Rahastoyhtiöiden sääntelyä muutetaan",
                "description": "Finanssisääntely ja compliance-velvoite uudistuvat.",
                "summary": "Muutos koskee sisäpiirirekisteriä.",
                "key_points": ["EU-sääntely korvaa kansallisen velvoitteen."],
            },
            "Rahastoyhtiöiden hallinnollinen velvoite kevenee.",
        )

        self.assertFalse(truth.weather_story)
        self.assertEqual(truth.season_time, "neutral")
        self.assertIn(
            "financial regulation, investment funds, or compliance documents",
            truth.acceptable_concepts,
        )

    def test_named_person_story_is_not_made_stock_safe_by_finance_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-named-person.md"
            _write_post(
                post,
                title="Donald Trump allekirjoitti rahastoyhtiöiden sääntelymuutoksen",
                description="Donald Trump allekirjoitti sijoitusrahastoja koskevan muutoksen.",
                summary="Muutos koskee rahastoyhtiöiden compliance-velvoitteita.",
                key_points=("Rahastoyhtiöiden finanssisääntely muuttuu.",),
                body="Donald Trump allekirjoitti muutoksen julkisessa tilaisuudessa.",
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("named-person", str(row["reason"]))

    def test_single_surname_story_is_not_made_stock_safe_by_finance_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-single-surname.md"
            _write_post(
                post,
                title="Trump allekirjoitti rahastoyhtiöiden sääntelymuutoksen",
                description="Trump allekirjoitti sijoitusrahastoja koskevan muutoksen.",
                summary="Muutos koskee rahastoyhtiöiden compliance-velvoitteita.",
                key_points=("Rahastoyhtiöiden finanssisääntely muuttuu.",),
                body="Trump allekirjoitti muutoksen julkisessa tilaisuudessa.",
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("named-person", str(row["reason"]))

    def test_location_specific_candidate_cannot_switch_tampere_to_paris(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-tampere-rail.md"
            _write_post(
                post,
                title="Tampereen ratainfrastruktuuria uudistetaan",
                description="Tampereella korjataan rautatietä ja rataverkkoa.",
                summary="Radan rakennustyöt tehdään Tampereella.",
                key_points=("Tampereen rautatiehanke etenee.",),
                body="Rataverkon rakennustyömaa sijaitsee Tampereella.",
                candidate_id="railParis12",
                source_page=RAIL_PARIS_PAGE,
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("location", str(row["reason"]))
        self.assertIn("paris", str(row["reason"]))

    def test_location_specific_candidate_rejects_known_and_unlisted_foreign_places(self) -> None:
        cases = {
            "rome": ("railRome123", "rome-italy", "rome"),
            "london": ("railLond123", "london-england", "london"),
            "new-york": ("railNYork12", "new-york-united-states", "new york"),
            # Madrid is intentionally not a city in the audit alias table. The
            # location claim must still be derived from the city/country slug.
            "madrid": ("railMadri12", "madrid-spain", "madrid"),
        }
        for label, (candidate_id, place_slug, expected) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                posts = Path(tmp)
                post = posts / f"2026-09-02-tampere-{label}.md"
                page = (
                    "https://unsplash.com/photos/"
                    f"railway-tracks-and-construction-in-{place_slug}-{candidate_id}"
                )
                _write_post(
                    post,
                    title="Tampereen ratainfrastruktuuria uudistetaan",
                    description="Tampereella korjataan rautatietä ja rataverkkoa.",
                    summary="Radan rakennustyöt tehdään Tampereella.",
                    key_points=("Tampereen rautatiehanke etenee.",),
                    body="Rataverkon rakennustyömaa sijaitsee Tampereella.",
                    candidate_id=candidate_id,
                    source_page=page,
                )

                with patch.object(audit_image_flow, "POSTS_DIR", posts):
                    row = audit_image_flow.audit_recent(1)[0]

            self.assertEqual(row["status"], "flag")
            self.assertIn("location", str(row["reason"]))
            self.assertIn(expected, str(row["reason"]))

    def test_location_specific_candidate_accepts_tampere_and_finland(self) -> None:
        candidate_id = "railTampr12"
        page = (
            "https://unsplash.com/photos/"
            f"railway-tracks-and-construction-in-tampere-finland-{candidate_id}"
        )
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-tampere-local.md"
            _write_post(
                post,
                title="Tampereen ratainfrastruktuuria uudistetaan",
                description="Tampereella korjataan rautatietä ja rataverkkoa.",
                summary="Radan rakennustyöt tehdään Tampereella.",
                key_points=("Tampereen rautatiehanke etenee.",),
                body="Rataverkon rakennustyömaa sijaitsee Tampereella.",
                candidate_id=candidate_id,
                source_page=page,
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "ok", row["reason"])

    def test_sensitive_inflections_are_independent_fail_closed_truth(self) -> None:
        cases = {
            "puukotus": "Puukotus tapahtui yliopistossa.",
            "ryöstettiin": "Rahastoyhtiö ryöstettiin aamulla.",
            "kavalluksesta": "Rahastoyhtiötä epäillään kavalluksesta.",
            "raiskauksesta": "Opiskelijaa epäillään raiskauksesta.",
        }
        for label, title in cases.items():
            with self.subTest(label=label):
                truth = audit_image_flow._derive_audit_truth(
                    {
                        "title": title,
                        "description": "Yliopiston ja rahastoyhtiön tapausta tutkitaan.",
                        "summary": "Tutkinta jatkuu.",
                        "key_points": ["Viranomaiset selvittävät tapahtumia."],
                    },
                    "Tapauksen tutkinta jatkuu.",
                )

                self.assertTrue(truth.sensitive_story)
                self.assertFalse(truth.stock_ok)

    def test_provider_semantic_evidence_requires_https_official_shape_and_id_binding(self) -> None:
        cases = {
            "http": {
                "image_candidate_id": FINANCE_ID,
                "image_candidate_url": FINANCE_PAGE.replace("https://", "http://"),
                "image_source_url": FINANCE_PAGE.replace("https://", "http://"),
            },
            "unofficial-subdomain": {
                "image_candidate_id": FINANCE_ID,
                "image_candidate_url": FINANCE_PAGE.replace(
                    "unsplash.com", "api.unsplash.com"
                ),
                "image_source_url": FINANCE_PAGE.replace(
                    "unsplash.com", "api.unsplash.com"
                ),
            },
            "wrong-path": {
                "image_candidate_id": FINANCE_ID,
                "image_candidate_url": FINANCE_PAGE.replace("/photos/", "/search/"),
                "image_source_url": FINANCE_PAGE.replace("/photos/", "/search/"),
            },
            "unbound-id": {
                "image_candidate_id": FINANCE_ID,
                "image_candidate_url": FINANCE_PAGE.replace(FINANCE_ID, "otherPhoto1"),
                "image_source_url": FINANCE_PAGE.replace(FINANCE_ID, "otherPhoto1"),
            },
            "invalid-id-format": {
                "image_candidate_id": "documents",
                "image_candidate_url": (
                    "https://unsplash.com/photos/financial-regulation-documents"
                ),
                "image_source_url": (
                    "https://unsplash.com/photos/financial-regulation-documents"
                ),
            },
            "inconsistent-pages": {
                "image_candidate_id": FINANCE_ID,
                "image_candidate_url": FINANCE_PAGE,
                "image_source_url": FINANCE_PAGE.replace(
                    "financial-regulation-compliance-documents",
                    "railway-tracks-and-construction",
                ),
            },
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                self.assertEqual(
                    audit_image_flow._provider_page_tokens("unsplash", candidate),
                    set(),
                )

        pexels_invalid = (
            "https://www.pexels.com/photos/financial-documents-12345/",
            "https://images.pexels.com/photo/financial-documents-12345/",
            "https://www.pexels.com/photo/financial-documents-99999/",
        )
        for page in pexels_invalid:
            with self.subTest(provider="pexels", page=page):
                self.assertEqual(
                    audit_image_flow._provider_page_tokens(
                        "pexels",
                        {
                            "image_candidate_id": "12345",
                            "image_source_url": page,
                        },
                    ),
                    set(),
                )

    def test_invalid_provider_page_makes_relevant_stock_candidate_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-provider-spoof.md"
            _write_post(
                post,
                source_page=FINANCE_PAGE.replace("https://", "http://"),
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "missing")
        self.assertIn("provider semantic evidence", str(row["reason"]))

    def test_sensitive_conflict_also_explains_tv_books_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-conflict.md"
            _write_post(
                post,
                title="Yhdysvallat iski Iraniin ohjuksilla",
                description="Sotilasisku kohdistui Iranin alueelle.",
                summary="Iran ilmoitti vastanneensa ohjusiskuun.",
                key_points=("Konflikti jatkui sotilaallisilla iskuilla.",),
                body="Hyökkäys ja vastaisku kiristivät maiden konfliktia.",
                candidate_id="tvBooks123x",
                source_page=TV_BOOKS_PAGE,
            )

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("sensitive", str(row["reason"]))
        self.assertIn("candidate unrelated", str(row["reason"]))

    def test_real_conflict_packet_rejects_incidental_television_as_visual_truth(self) -> None:
        row = audit_image_flow.audit_packet(CONFLICT_PACKET, CONFLICT_ARTICLE)

        self.assertEqual(row["status"], "flag")
        reason = str(row["reason"])
        self.assertIn("unsupported stored intent must_have=book, television", reason)
        self.assertIn("candidate unrelated", reason)
        self.assertIn("sensitive", reason)

    def test_packet_stored_acceptable_concept_is_checked_after_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article = root / "article.md"
            packet = root / "packet.json"
            _write_post(article)
            packet.write_text(
                json.dumps({
                    "packet": {
                        "source_text": (
                            "Rahastoyhtiöiden sisäpiirirekisteriä ja "
                            "finanssisääntelyä koskevaa velvoitetta muutetaan."
                        )
                    },
                    "article": {
                        "image": "https://images.unsplash.com/photo-finance",
                        "image_source": "unsplash",
                        "image_source_url": FINANCE_PAGE,
                        "image_candidate_url": FINANCE_PAGE,
                        "image_candidate_id": FINANCE_ID,
                        "image_visual_brief": {
                            "acceptable_concepts": ["winter weather"],
                        },
                    },
                }),
                encoding="utf-8",
            )

            row = audit_image_flow.audit_packet(packet, article)

        self.assertEqual(row["status"], "flag")
        self.assertIn("unsupported stored acceptable_concept=winter weather", str(row["reason"]))

    def test_frontmatter_summary_and_key_points_are_article_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "2026-09-02-key-points.md"
            _write_post(
                post,
                title="Muutos etenee",
                description="Esitys annetaan eduskunnalle.",
                summary="Hallinnollista taakkaa kevennetään.",
                key_points=("Rahastoyhtiöiden finanssisääntely ja compliance muuttuvat.",),
                body="Lakiesitys käsitellään syksyllä.",
            )

            fields = audit_image_flow._frontmatter(post)
            with patch.object(audit_image_flow, "POSTS_DIR", post.parent):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(
            fields["key_points"],
            ["Rahastoyhtiöiden finanssisääntely ja compliance muuttuvat."],
        )
        self.assertEqual(row["status"], "ok")

    def test_packet_source_text_can_ground_candidate_but_missing_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article = root / "article.md"
            packet = root / "packet.json"
            _write_post(
                article,
                title="Muutos etenee",
                description="Esitys annetaan eduskunnalle.",
                summary="Hallinnollista taakkaa kevennetään.",
                key_points=(),
                body="Lakiesitys käsitellään syksyllä.",
            )
            packet_article = {
                "image": "https://images.unsplash.com/photo-1234567890-abcdef?w=1080",
                "image_source": "unsplash",
                "image_source_url": FINANCE_PAGE,
                "image_candidate_url": FINANCE_PAGE,
                "image_candidate_id": FINANCE_ID,
            }
            packet.write_text(
                json.dumps({
                    "packet": {
                        "source_text": (
                            "Rahastoyhtiöiden sisäpiirirekisteriä ja "
                            "finanssisääntelyä koskevaa velvoitetta muutetaan."
                        )
                    },
                    "article": packet_article,
                }),
                encoding="utf-8",
            )

            grounded = audit_image_flow.audit_packet(packet, article)
            packet.write_text(json.dumps({"article": packet_article}), encoding="utf-8")
            missing = audit_image_flow.audit_packet(packet, article)

        self.assertEqual(grounded["status"], "ok")
        self.assertEqual(missing["status"], "missing")
        self.assertIn("source evidence unavailable", str(missing["reason"]))

    def test_same_title_reuse_still_requires_explicit_editorial_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            first = posts / "2026-09-02-first.md"
            second = posts / "2026-09-02-second.md"
            _write_post(first)
            _write_post(second, date="2026-09-02T13:00:00+00:00")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                rows = audit_image_flow.audit_recent(2)

        self.assertTrue(all("duplicate canonical image" in str(row["reason"]) for row in rows))

    def test_duplicate_aliases_join_legacy_url_only_and_id_bearing_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            current = posts / "2026-09-02-current.md"
            legacy = posts / "2026-09-02-legacy.md"
            _write_post(current)
            _write_post(legacy, date="2026-09-02T13:00:00+00:00")
            legacy_text = legacy.read_text(encoding="utf-8")
            legacy_text = legacy_text.replace(
                f'image_source_url: "{FINANCE_PAGE}"',
                'image_source_url: ""',
            ).replace(
                f'image_candidate_id: "{FINANCE_ID}"',
                'image_candidate_id: ""',
            ).replace(
                f'image_candidate_url: "{FINANCE_PAGE}"',
                'image_candidate_url: ""',
            )
            legacy.write_text(legacy_text, encoding="utf-8")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                rows = audit_image_flow.audit_recent(2)

        self.assertNotEqual(rows[0]["image_identity"], rows[1]["image_identity"])
        self.assertTrue(all("duplicate canonical image" in str(row["reason"]) for row in rows))

    def test_fallback_claim_must_match_safe_category_asset_and_clear_stock_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-false-fallback.md"
            _write_post(post)
            text = post.read_text(encoding="utf-8")
            text = text.replace(
                "image_category_fallback: false",
                "image_category_fallback: true",
            ).replace(
                'image_source: "unsplash"',
                'image_source: "category_fallback"',
            )
            post.write_text(text, encoding="utf-8")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("fallback", str(row["reason"]))

    def test_fallback_rejects_stale_generated_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-stale-fallback.md"
            _write_post(post)
            text = post.read_text(encoding="utf-8")
            replacements = {
                f'image: "https://images.unsplash.com/photo-{FINANCE_ID}x?w=1080"':
                    'image: "/images/categories/talous.jpg"\n'
                    'image_thumb: "/images/categories/talous.jpg"',
                'image_alt: "snowy winter weather"': 'image_alt: "Talous-uutiset"',
                f'image_source_url: "{FINANCE_PAGE}"': 'image_source_url: ""',
                'image_source: "unsplash"': 'image_source: "category_fallback"',
                'image_query: "winter weather"': 'image_generated_fallback: true',
                f'image_candidate_id: "{FINANCE_ID}"': 'image_model: "obsolete"',
                f'image_candidate_url: "{FINANCE_PAGE}"':
                    'image_generation_prompt: "stale generated prompt"',
                "image_category_fallback: false":
                    'image_source_type: "category_fallback"\nimage_category_fallback: true',
            }
            for old, new in replacements.items():
                text = text.replace(old, new)
            post.write_text(text, encoding="utf-8")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        self.assertIn("image_generated_fallback", str(row["reason"]))

    def test_fallback_accepts_current_policy_receipt_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-current-fallback-policy.md"
            _write_post(post)
            text = post.read_text(encoding="utf-8")
            replacements = {
                f'image: "https://images.unsplash.com/photo-{FINANCE_ID}x?w=1080"':
                    'image: "/images/categories/talous.jpg"\n'
                    'image_thumb: "/images/categories/talous.jpg"',
                'image_alt: "snowy winter weather"': 'image_alt: "Talous-uutiset"',
                f'image_source_url: "{FINANCE_PAGE}"': 'image_source_url: ""',
                'image_source: "unsplash"': 'image_source: "category_fallback"',
                'image_query: "winter weather"':
                    'image_decision_reason: "safe fallback after stock rejection"\n'
                    'image_visual_judge_score: 0\n'
                    'image_prompt_version: "image-flow-v3-grounded-2026-09-02"',
                f'image_candidate_id: "{FINANCE_ID}"': 'image_candidate_id: ""',
                f'image_candidate_url: "{FINANCE_PAGE}"': 'image_candidate_url: ""',
                "image_category_fallback: false":
                    'image_source_type: "category_fallback"\nimage_category_fallback: true',
            }
            for old, new in replacements.items():
                text = text.replace(old, new)
            post.write_text(text, encoding="utf-8")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "ok", row["reason"])

    def test_fallback_rejects_stale_decision_judge_prompt_and_reason_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-stale-fallback-policy.md"
            _write_post(post)
            text = post.read_text(encoding="utf-8")
            replacements = {
                f'image: "https://images.unsplash.com/photo-{FINANCE_ID}x?w=1080"':
                    'image: "/images/categories/talous.jpg"\n'
                    'image_thumb: "/images/categories/talous.jpg"',
                'image_alt: "snowy winter weather"': 'image_alt: "Talous-uutiset"',
                f'image_source_url: "{FINANCE_PAGE}"': 'image_source_url: ""',
                'image_source: "unsplash"': 'image_source: "category_fallback"',
                'image_query: "winter weather"':
                    'image_decision: \'{"source":"unsplash","accepted":true}\'\n'
                    'image_visual_judge_score: 91\n'
                    'image_prompt_version: "image-flow-v1-2025-01-01"\n'
                    'image_accepted_reasons:\n'
                    '  - "stock candidate matched"\n'
                    'image_rejected_reasons:\n'
                    '  - "old rejection"',
                f'image_candidate_id: "{FINANCE_ID}"': 'image_candidate_id: ""',
                f'image_candidate_url: "{FINANCE_PAGE}"': 'image_candidate_url: ""',
                "image_category_fallback: false":
                    'image_source_type: "category_fallback"\nimage_category_fallback: true',
            }
            for old, new in replacements.items():
                text = text.replace(old, new)
            post.write_text(text, encoding="utf-8")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                row = audit_image_flow.audit_recent(1)[0]

        self.assertEqual(row["status"], "flag")
        reason = str(row["reason"])
        for field in (
            "image_decision",
            "image_visual_judge_score",
            "image_prompt_version",
            "image_accepted_reasons",
            "image_rejected_reasons",
        ):
            with self.subTest(field=field):
                self.assertIn(field, reason)

    def test_packet_with_candidate_metadata_but_no_delivered_image_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            article = root / "article.md"
            packet = root / "packet.json"
            _write_post(article)
            packet.write_text(
                json.dumps({
                    "packet": {"source_text": "Rahastoyhtiöiden finanssisääntely muuttuu."},
                    "article": {
                        "image_source": "unsplash",
                        "image_source_url": FINANCE_PAGE,
                        "image_candidate_url": FINANCE_PAGE,
                        "image_candidate_id": FINANCE_ID,
                    },
                }),
                encoding="utf-8",
            )

            row = audit_image_flow.audit_packet(packet, article)

        self.assertEqual(row["status"], "missing")
        self.assertIn("delivered image", str(row["reason"]))

    def test_cli_returns_nonzero_for_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            post = posts / "2026-09-02-missing.md"
            post.write_text(
                "---\n"
                'title: "Kuva puuttuu"\n'
                "date: 2026-09-02T12:00:00+00:00\n"
                "categories:\n  - Kotimaa\n"
                "---\n\nArtikkelin leipäteksti.\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with patch.object(audit_image_flow, "POSTS_DIR", posts), redirect_stdout(output):
                result = audit_image_flow.main(["--limit", "1"])

        self.assertEqual(result, 1)
        self.assertIn("missing\t", output.getvalue())

    def test_empty_missing_and_nonpositive_recent_scans_fail_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = (
                ("empty", root, 30),
                ("missing", root / "does-not-exist", 30),
                ("zero-limit", root, 0),
                ("negative-limit", root, -1),
            )
            for label, posts, limit in cases:
                with self.subTest(label=label):
                    output = io.StringIO()
                    with patch.object(audit_image_flow, "POSTS_DIR", posts), redirect_stdout(output):
                        result = audit_image_flow.main(["--limit", str(limit)])

                    self.assertEqual(result, 1)
                    self.assertIn("missing\t", output.getvalue())

    def test_malformed_post_cannot_sort_outside_recent_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            _write_post(
                posts / "2026-09-02-newest-valid.md",
                date="2026-09-02T14:00:00+00:00",
            )
            _write_post(
                posts / "2026-09-02-older-valid.md",
                date="2026-09-02T13:00:00+00:00",
            )
            malformed = posts / "0000-malformed.md"
            malformed.write_text("not front matter\n", encoding="utf-8")

            with patch.object(audit_image_flow, "POSTS_DIR", posts):
                rows = audit_image_flow.audit_recent(1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(Path(str(rows[0]["file"])).name, malformed.name)
        self.assertEqual(rows[0]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
