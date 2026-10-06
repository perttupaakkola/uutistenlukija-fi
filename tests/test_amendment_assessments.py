"""Secret-free tests for pure, non-activating amendment assessment binding."""
import copy
import dataclasses
import hashlib
import json
import math
import unittest

from news_mvp.amendment_assessments import bind_assessments
from news_mvp.release_contract import digest
from news_mvp.site import SITE_URL, article_path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def coverage(text):
    raw = text.encode()
    return {
        "encoding": "UTF-8", "bytes": len(raw), "sha256": sha(raw),
        "reviewed_byte_range": [0, len(raw)], "complete_text_read": True,
        "includes_navigation_and_keyword_tail": True,
    }


class AmendmentAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.image_bytes = b"synthetic retained jpeg bytes"
        self.image_sha = sha(self.image_bytes)
        self.job_id = "1" * 64
        provenance = {
            "photo_id": "synthetic-photo", "retrieved_at": "2026-10-01T00:00:00Z",
            "attribution": {"title": "Synthetic manor.jpg", "changes": "JPEG encoding only"},
        }
        self.retained_image = {
            "sha256": self.image_sha,
            "url": f"https://uutistenlukija.fi/media/{self.image_sha}.jpg",
            "source_url": "https://images.example/manor",
            "credit": "Synthetic photographer", "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0",
            "alt": "Synthetic manor exterior", "caption": "Synthetic archive image",
            "stock_provenance": provenance,
            "stock_provenance_sha256": digest(provenance),
            # Deliberately present but never accepted as this assessment.
            "pixel_review": {"approved": True, "image_sha256": self.image_sha},
        }
        predecessor_draft = {
            "title": "Synthetic manor programme", "category": "Kulttuuri",
            "summary": "Old summary", "paragraphs": [], "image": self.retained_image,
        }
        predecessor_packet = {"story_key": "url:https://source.example/original"}
        publication = {
            "job_id": self.job_id, "packet_sha": digest(predecessor_packet),
            "draft_sha": digest(predecessor_draft), "image_sha": self.image_sha,
            "source_commit": "synthetic", "remote_commit": "synthetic",
            "run_id": 1, "status": "deployed", "attempts": 0, "error": None,
        }
        job = {
            "id": self.job_id, "story_key": "url:https://source.example/original",
            "source_url": "https://source.example/original",
            "packet": json.dumps(predecessor_packet),
            "draft": json.dumps(predecessor_draft, ensure_ascii=False),
            "review": json.dumps({"approved": True}), "status": "rendered",
            "created_at": "2026-10-01T00:00:00+00:00", "attempts": 1,
            "next_attempt": 0.0, "error": None, "adapter": "synthetic",
        }
        self.sources = {
            "original": {
                "id": "A", "title": "Original source", "url": job["source_url"],
                "publisher": "Synthetic city", "published_at": "2026-10-01T01:00:00+00:00",
                "text": "Original complete source text\nNavigation tail",
                "reuse": {"license": "synthetic text terms"},
            },
            "update": {
                "id": "A", "title": "Update source", "url": "https://source.example/update",
                "publisher": "Synthetic city", "published_at": "2026-10-02T01:00:00+00:00",
                "text": "Update complete source text\nNavigation tail",
                "reuse": {"license": "synthetic text terms"},
            },
        }
        captures, citations, rights = {}, [], []
        for role in ("original", "update"):
            source = self.sources[role]
            document = {"id": "RIGHTS", "text": "Complete synthetic rights text",
                        "purpose": "text reuse only"}
            basis = {"provider": "synthetic", "source_fields_sha256": digest(source)}
            packet = {
                "sources": [source], "supporting_documents": [document],
                "publication_basis": basis, "story_key": "url:" + source["url"],
            }
            receipt = {
                "packet_sha256": digest(packet), "source_sha256": sha((role + " raw html").encode()),
                "retrieved_at": "2026-10-03T00:00:00+00:00",
            }
            binding = {"packet_sha256": sha((role + " packet file").encode()),
                       "receipt_sha256": sha((role + " receipt file").encode())}
            captures[role] = {"packet": packet, "receipt": receipt, "binding": binding,
                              "validation_draft": {"image": None}}
            citations.append({"id": f"amendment:{role}:A", "role": role,
                              "capture_source": source})
            rights.append({"id": f"amendment:{role}:RIGHTS", "role": role,
                           "publication_basis": basis, "reuse": source["reuse"],
                           "document": document})
        self.candidate = {
            "category": "Kulttuuri", "title": predecessor_draft["title"],
            "summary": "Corrected synthetic summary",
            "paragraphs": [
                {"text": "Unchanged synthetic paragraph.",
                 "source_ids": ["amendment:original:A"]},
                {"text": "Corrected synthetic paragraph.",
                 "source_ids": ["amendment:original:A", "amendment:update:A"]},
            ],
        }
        reason = "Correct the synthetic schedule"
        updated_at = "2026-10-04T00:00:00+00:00"
        self.artifact = {
            "schema": "published-amendment-artifact-preparation-v1",
            "preparation_only": True, "approval": False, "activation": False,
            "acceptance": "frozen-preparation-hash-only; fresh-fulltext-and-image-approval-and-CAS-required",
            "predecessor": {"job": job, "publication": publication},
            "evidence": {
                "schema": "published-amendment-preparation-v1", "job_id": self.job_id,
                "predecessor_packet_sha256": digest(predecessor_packet),
                "predecessor_draft_sha256": digest(predecessor_draft),
                "predecessor_publication_sha256": digest(publication),
                "original_capture": captures["original"]["binding"],
                "update_capture": captures["update"]["binding"],
                "reason": reason, "updated_at": updated_at,
            },
            "identity": {key: job[key] for key in ("id", "story_key", "source_url", "created_at")},
            "captures": captures,
            "validation_drafts_purpose": "capture-validation-provenance-only-not-amendment-approval",
            "candidate_manuscript": self.candidate, "citations": citations, "rights": rights,
            "projection_kind": "amendment-only-two-capture-roles-not-ordinary-packet",
        }
        self.canonical = SITE_URL + article_path({"id": self.job_id, "draft": predecessor_draft})
        self.rebind_all()

    def rebind_all(self):
        artifact_raw = encode(self.artifact)
        candidate_raw = encode(self.candidate)
        paragraph_reviews = []
        claims = []
        for number, paragraph in enumerate(self.candidate["paragraphs"], 1):
            claim = f"Synthetic supported claim {number}"
            claims.append(claim)
            paragraph_reviews.append({
                "paragraph": number, "text_sha256": sha(paragraph["text"].encode()),
                "full_text_read": True, "source_ids": paragraph["source_ids"],
                "supported_claims": claim, "unsupported_claims": [],
                "verdict": "supported", "editorial_note": None,
            })
        source_reviews = []
        for role in ("original", "update"):
            capture = self.artifact["captures"][role]
            source = capture["packet"]["sources"][0]
            receipt = capture["receipt"]
            document = capture["packet"]["supporting_documents"][0]
            source_reviews.append({
                "role": role, "citation_id": f"amendment:{role}:A",
                "url": source["url"], "publisher": source["publisher"],
                "published_at": source["published_at"], "retrieved_at": receipt["retrieved_at"],
                "complete_source_text_coverage": coverage(source["text"]),
                "canonical_complete_source_object_bytes": len(encode(source)),
                "canonical_complete_source_object_sha256": digest(source),
                "capture_binding_as_recorded": capture["binding"],
                "embedded_packet_canonical_sha256": digest(capture["packet"]),
                "embedded_receipt_canonical_sha256": digest(receipt),
                "receipt_source_sha256_as_recorded": receipt["source_sha256"],
                "raw_capture_file_bytes_reverified": False,
                "rights_document_text_coverage": coverage(document["text"]),
                "reuse_projection": source["reuse"],
                "publication_basis_projection": capture["packet"]["publication_basis"],
                "citation_projection_equals_capture_source": True,
            })
        self.fulltext = {
            "schema": "independent-fulltext-editorial-review-v1",
            "reviewed_at": "2026-10-04T01:00:00+00:00",
            "scope": "Fresh independent full-text editorial review of exact embedded two-capture candidate only; not activation, image review, installed publication approval or release.",
            "artifact_path": "/synthetic/preparation.json", "artifact_bytes": len(artifact_raw),
            "artifact_sha256": sha(artifact_raw), "candidate_manuscript_sha256": digest(self.candidate),
            "candidate_manuscript_canonical_bytes": len(candidate_raw),
            "canonical_digest_definition": "SHA256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(comma, colon)).encode(UTF-8)); matches news_mvp/amendments.py _digest",
            "predecessor_review_reused": False, "paragraphs_read": len(self.candidate["paragraphs"]),
            "paragraph_reviews": paragraph_reviews, "source_reviews": source_reviews,
            "title_summary_category_review": {
                "title_supported": True, "summary_supported": True, "category_appropriate": True,
                "title_unchanged": True, "summary_unchanged": True, "category_unchanged": True,
            },
            "changed_text_paragraphs": [2],
            "corrected_paragraph_verdict": {
                "paragraph": 2, "verdict": "pass", "new_source_exact_support": "new support",
                "old_source_exact_support": "old support", "analysis": "synthetic comparison",
            },
            "factual_verdict": "pass", "attribution_verdict": "scoped pass",
            "editorial_verdict": "scoped pass", "textual_pass": True,
            "supported_claims": claims, "unsupported_claims": [],
            "rights_verdict": "observed only; no legal authentication",
            "downstream_requirements": {
                "genuine_visible_update_notice_required": True,
                "reason": self.artifact["evidence"]["reason"],
                "updated_at": self.artifact["evidence"]["updated_at"],
                "notice_recommendation": "Show a correction notice",
                # Deliberately the upstream URL: ancillary and ignored.
                "preserve_original_canonical": self.sources["original"]["url"],
                "preserve_datePublished": "2026-10-01T00:00:00+00:00",
                "preserve_title": self.candidate["title"],
                "preserve_category": self.candidate["category"],
                "notice_rendered_or_installed": False,
            },
            "limitations": ["No network, rights authentication, approval or activation"],
            "image_approval": False, "release_authorization": False,
            "activation_authorization": False, "installed_publication_approval": False,
        }
        self.image_review = self.make_image_review(len(artifact_raw), sha(artifact_raw))

    def make_image_review(self, artifact_len, artifact_sha):
        provenance = self.retained_image["stock_provenance"]
        metadata = {
            "source": "JSON-decoded preparation.predecessor.job.draft.image; image.stock_provenance supplies image-specific provenance, not preparation.rights",
            "source_url": self.retained_image["source_url"],
            "provenance_photo_id": provenance["photo_id"],
            "provenance_title": provenance["attribution"]["title"],
            "identity_status": "recorded metadata only", "year_status": "recorded only",
            "exact_capture_date": "UNKNOWN", "credit": self.retained_image["credit"],
            "license_recorded": self.retained_image["license"],
            "license_url_recorded": self.retained_image["license_url"],
            "changes_recorded": provenance["attribution"]["changes"],
            "provenance_retrieved_at": provenance["retrieved_at"],
            "stock_provenance_sha256_recorded": self.retained_image["stock_provenance_sha256"],
            "alt_recorded": self.retained_image["alt"],
            "caption_recorded": self.retained_image["caption"],
            "rights_status": "recorded, not authenticated",
            "excluded_rights_basis": "text rights are not image rights",
        }
        return {
            "schema": "fresh-scoped-image-assessment-v1",
            "assessment_type": "Reader-benefit review of retained image against complete corrected manuscript; not normal model approval",
            "scope": {
                "preparation_only": True, "normal_model_approval": False,
                "licensing_certification": False, "release_authorization": False,
                "activation": False, "new_stock_searches_performed": False,
                "credentials_or_model_provider_calls": False,
                "source_state_or_repository_changes": False,
                "prior_image_scores_or_approval_used_as_truth": False,
                "visual_surface": "synthetic supplied screenshot only",
            },
            "bindings": {
                "preparation_path": self.fulltext["artifact_path"],
                "preparation_bytes": artifact_len,
                "preparation_sha256_computed": artifact_sha,
                "candidate_manuscript_sha256_computed": digest(self.candidate),
                "candidate_digest_method": "canonical JSON SHA256",
                "candidate_paragraph_count_read": len(self.candidate["paragraphs"]),
                "candidate_title": self.candidate["title"],
                "public_canonical_url": self.canonical,
                "original_upstream_url": self.sources["original"]["url"],
                "image_sha256_exact_retained_metadata": self.image_sha,
                "actual_live_image_url_supplied": f"https://uutistenlukija.fi/mvp-assets/{self.image_sha}.jpg",
                "original_draft_image_url": self.retained_image["url"],
                "image_byte_digest_independently_recomputed": False,
                "image_byte_verification_limitation": "prior review used metadata only",
                "screenshot_path": "/synthetic/screenshot.png",
                "screenshot_sha256_computed": sha(b"synthetic screenshot"),
                "screenshot_bytes": 20, "screenshot_context_supplied": "synthetic desktop",
            },
            "complete_text_review_basis": {
                "paragraphs_1_to_2": ["first paragraph", "second paragraph"],
                "interpretation": "complete synthetic manuscript read",
            },
            "ranked_article_supported_image_concepts": [{
                "rank": 1, "concept": "manor exterior", "support": "complete text",
                "reader_benefit": "place recognition", "boundary": "metadata identity only",
            }],
            "independent_pixel_inspection": {
                "observed": "synthetic building", "quality_and_reader_value": "legible",
                "not_inferred_from_pixels": ["identity", "license"],
                "limitation": "not a licensing check",
            },
            "exact_retained_metadata_evidence": metadata,
            "fresh_conceptual_fit": {
                "score_out_of_10": 8, "meets_at_least_8": True,
                "basis": "fresh fit to complete corrected text",
                "limitations": ["not fresh network proof"],
                "unsupported_claims_to_avoid": ["normal approval"],
                "retaining_after_new_approval_reasonable": True,
                "retention_conditions": "requires a later distinct normal approval gate",
            },
            "issues": [],
        }

    def bind(self, artifact_raw=None, fulltext_raw=None, image_raw=None, image_bytes=None):
        return bind_assessments(
            artifact_raw if artifact_raw is not None else encode(self.artifact),
            fulltext_raw if fulltext_raw is not None else encode(self.fulltext),
            image_raw if image_raw is not None else encode(self.image_review),
            image_bytes if image_bytes is not None else self.image_bytes,
        )

    def refused(self, **kwargs):
        with self.assertRaises(ValueError):
            self.bind(**kwargs)

    def rebind_artifact_bytes_only(self):
        raw = encode(self.artifact)
        self.fulltext["artifact_bytes"] = len(raw)
        self.fulltext["artifact_sha256"] = sha(raw)
        self.image_review["bindings"]["preparation_bytes"] = len(raw)
        self.image_review["bindings"]["preparation_sha256_computed"] = sha(raw)

    def test_valid_binding_is_frozen_nonactivating_and_ignores_ancillary_upstream_canonical(self):
        result = self.bind()
        self.assertTrue(result.preparation_only)
        self.assertFalse(result.normal_approval)
        self.assertFalse(result.activation)
        self.assertFalse(result.release_authorization)
        self.assertFalse(result.licensing_certification)
        self.assertFalse(result.fresh_network_proof)
        self.assertTrue(result.observations_only)
        self.assertFalse(result.semantic_authentication)
        self.assertEqual(result.public_canonical_url, self.canonical)
        self.assertEqual(result.ignored_ancillary_fulltext_canonical,
                         self.sources["original"]["url"])
        self.assertEqual(result.fulltext_review_sha256, sha(encode(self.fulltext)))
        self.assertEqual(result.image_assessment_sha256, sha(encode(self.image_review)))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.normal_approval = True

    def test_changed_artifact_and_retained_image_bytes_refused(self):
        self.refused(artifact_raw=encode(self.artifact) + b" ")
        self.refused(image_bytes=self.image_bytes + b"changed")

    def test_changed_manuscript_and_source_refused_after_artifact_rebinding(self):
        candidate = self.artifact["candidate_manuscript"]
        candidate["summary"] = "Changed after review"
        self.rebind_artifact_bytes_only()
        self.refused()
        self.setUp()
        self.artifact["captures"]["original"]["packet"]["sources"][0]["text"] += " changed"
        self.rebind_artifact_bytes_only()
        self.refused()

    def test_changed_paragraph_review_and_duplicate_indices_refused(self):
        self.fulltext["paragraph_reviews"][0]["text_sha256"] = "0" * 64
        self.refused()
        self.setUp()
        self.fulltext["paragraph_reviews"][1]["paragraph"] = 1
        self.refused()

    def test_stale_artifact_manuscript_and_image_hashes_refused(self):
        mutations = [
            (self.fulltext, "artifact_sha256"),
            (self.fulltext, "candidate_manuscript_sha256"),
            (self.image_review["bindings"], "preparation_sha256_computed"),
            (self.image_review["bindings"], "candidate_manuscript_sha256_computed"),
            (self.image_review["bindings"], "image_sha256_exact_retained_metadata"),
        ]
        for owner, key in mutations:
            with self.subTest(key=key):
                old = owner[key]
                owner[key] = "0" * 64
                self.refused()
                owner[key] = old

    def test_missing_or_partial_fulltext_and_source_coverage_refused(self):
        self.fulltext["paragraph_reviews"].pop()
        self.refused()
        self.setUp()
        self.fulltext["source_reviews"].pop()
        self.refused()
        self.setUp()
        self.fulltext["source_reviews"][0]["complete_source_text_coverage"]["reviewed_byte_range"][1] -= 1
        self.refused()

    def test_boolean_is_not_integer_or_score(self):
        cases = [
            (self.fulltext, "paragraphs_read"),
            (self.fulltext["source_reviews"][0]["complete_source_text_coverage"], "bytes"),
            (self.image_review["bindings"], "screenshot_bytes"),
            (self.image_review["fresh_conceptual_fit"], "score_out_of_10"),
        ]
        for owner, key in cases:
            with self.subTest(key=key):
                old = owner[key]
                owner[key] = True
                self.refused()
                owner[key] = old

    def test_nonfinite_and_duplicate_json_refused(self):
        self.refused(fulltext_raw=b'{"x":NaN}')
        self.refused(image_raw=b'{"schema":1,"schema":2}')
        self.image_review["fresh_conceptual_fit"]["score_out_of_10"] = math.inf
        raw = json.dumps(self.image_review, allow_nan=True).encode()
        self.refused(image_raw=raw)

    def test_old_publication_approval_is_not_scoped_review(self):
        old = self.artifact["predecessor"]["job"]["review"].encode()
        self.refused(fulltext_raw=old)
        self.fulltext["scope"] = "ordinary installed publication approval"
        self.fulltext["installed_publication_approval"] = True
        self.refused()

    def test_stale_fulltext_review_instant_refused(self):
        self.fulltext["reviewed_at"] = "2026-10-03T23:59:59+00:00"
        self.refused()

    def test_false_scope_flags_and_global_approval_claim_refused(self):
        for key in ("normal_model_approval", "licensing_certification",
                    "release_authorization", "activation",
                    "prior_image_scores_or_approval_used_as_truth"):
            with self.subTest(key=key):
                self.image_review["scope"][key] = True
                self.refused()
                self.image_review["scope"][key] = False
        self.image_review["approval"] = True
        self.refused()

    def test_public_canonical_cannot_be_upstream_source(self):
        self.image_review["bindings"]["public_canonical_url"] = self.sources["original"]["url"]
        self.refused()
        self.setUp()
        self.image_review["bindings"]["original_upstream_url"] = self.canonical
        self.refused()

    def test_screenshot_hash_cannot_substitute_for_image_hash(self):
        self.image_review["bindings"]["screenshot_sha256_computed"] = self.image_sha
        self.refused()


if __name__ == "__main__":
    unittest.main()
