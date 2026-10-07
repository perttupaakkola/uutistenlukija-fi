"""Focused tests for the non-activating amendment text-review bridge."""
import copy
import hashlib
import json
import unittest

from news_mvp.amendment_review import (
    NOT_RECONSTRUCTED,
    ROLE,
    build_review_envelope,
    review_amendment,
)
from news_mvp.editorial import ROOT, digest, encode
from tests import test_amendment_assessments as assessment_fixtures


def artifact_bytes():
    """Adapt the existing secret-free preparation fixture to the real 11-row diff."""
    fixture = assessment_fixtures.AmendmentAssessmentTests(
        "test_valid_binding_is_frozen_nonactivating_and_ignores_ancillary_upstream_canonical"
    )
    fixture.setUp()
    artifact = copy.deepcopy(fixture.artifact)
    candidate = artifact["candidate_manuscript"]
    predecessor = json.loads(artifact["predecessor"]["job"]["draft"])
    predecessor["summary"] = candidate["summary"]
    predecessor["paragraphs"] = []
    candidate["paragraphs"] = []
    for index in range(1, 12):
        old_text = f"Synthetic paragraph {index}."
        new_text = old_text if index != 6 else "Corrected synthetic paragraph 6."
        predecessor["paragraphs"].append({"text": old_text, "source_ids": ["A"]})
        source_ids = ["amendment:original:A"]
        if index == 6:
            source_ids.append("amendment:update:A")
        candidate["paragraphs"].append({"text": new_text, "source_ids": source_ids})

    job = artifact["predecessor"]["job"]
    publication = artifact["predecessor"]["publication"]
    evidence = artifact["evidence"]
    job["draft"] = json.dumps(predecessor, ensure_ascii=False)
    publication["draft_sha"] = digest(predecessor)
    evidence["predecessor_draft_sha256"] = digest(predecessor)
    evidence["predecessor_publication_sha256"] = digest(publication)
    return encode(artifact).encode()


class ReceiptFixtureModel:
    name = "fixture"

    def __init__(self, mode="ok"):
        self.mode = mode
        self.receipts = []

    def call(self, role, packet, draft=None, *, context=None):
        response = {
            "approved": True,
            "draft_sha256": digest(draft),
            "review_envelope_sha256": context["review_envelope_sha256"],
            "reasons": ["Fixture reviewer decision for the exact bound text."],
        }
        if self.mode == "unbound_draft":
            response["draft_sha256"] = "0" * 64
        elif self.mode == "unbound_envelope":
            response["review_envelope_sha256"] = "0" * 64
        if self.mode != "missing_receipt":
            request = {
                "source_packet": packet,
                "context": context,
                "draft": draft,
                "draft_sha256": digest(draft),
            }
            prompt = ((ROOT / "prompts" / (ROLE + ".md")).read_text()
                      + "\n\nINPUT JSON:\n" + encode(request))
            receipt = {
                "role": role,
                "exit_code": 0,
                "session_id": "fixture-session",
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "response_sha256": digest(response),
            }
            if self.mode == "stale_receipt":
                receipt["prompt_sha256"] = "0" * 64
            elif self.mode == "null_session":
                receipt["session_id"] = None
            self.receipts.append(receipt)
        return response


class AmendmentReviewTests(unittest.TestCase):
    def test_real_shape_diff_and_reconstruction_are_derived_fail_closed(self):
        envelope = build_review_envelope(artifact_bytes())
        diff = envelope["actual_diff"]
        self.assertEqual(diff["text_change_indices"], [6])
        self.assertEqual(diff["citation_change_indices"], list(range(1, 12)))
        self.assertFalse(diff["summary"]["changed"])
        self.assertEqual(diff["paragraph_count_before"], 11)
        self.assertEqual(diff["paragraph_count_after"], 11)
        self.assertEqual(envelope["validation"]["capture_reconstruction"],
                         NOT_RECONSTRUCTED)
        self.assertIn("does not authenticate source HTML",
                      envelope["validation"]["preparation_artifact"])

    def test_true_fixture_text_decision_never_becomes_normal_approval(self):
        result = review_amendment(
            artifact_bytes(), model=ReceiptFixtureModel(), fixture=True
        )
        self.assertTrue(result["text_approval"])
        self.assertTrue(result["fixture"])
        self.assertEqual(result["execution"]["kind"], "fixture")
        self.assertFalse(result["execution"]["cryptographic_or_semantic_authentication"])
        self.assertEqual(result["capture_reconstruction"], NOT_RECONSTRUCTED)
        self.assertEqual(result["exact_final_image_execution"], NOT_RECONSTRUCTED)
        for field in ("normal_approval", "activation", "release_authorization"):
            self.assertFalse(result[field])

    def test_receipt_and_response_fail_closed(self):
        for mode in ("missing_receipt", "stale_receipt", "null_session",
                     "unbound_draft", "unbound_envelope"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                review_amendment(
                    artifact_bytes(), model=ReceiptFixtureModel(mode), fixture=True
                )

    def test_changed_candidate_public_identities_are_refused(self):
        for field in ("title", "category"):
            with self.subTest(field=field):
                artifact = json.loads(artifact_bytes())
                artifact["candidate_manuscript"][field] += " changed"
                with self.assertRaises(ValueError):
                    build_review_envelope(encode(artifact).encode())


if __name__ == "__main__":
    unittest.main()
