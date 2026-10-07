"""Portable render-site coverage for synthetic amendment composites only."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cutover.check_release import check
from news_mvp import site
from news_mvp.amendment_review import build_review_envelope
from news_mvp.editorial import digest, encode
from news_mvp.release_contract import check_article, media
from tests.test_amendment_release_consumer import portable_amendment, set_version


IMAGE_BYTES = b"synthetic image bytes"


class TinyStore:
    def __init__(self, jobs):
        self.jobs = jobs
        self.rendered = None

    def articles(self):
        return list(self.jobs)

    def mark_rendered(self, ids):
        self.rendered = list(ids)


def amendment_job(packet, draft):
    envelope = packet["final_review_input"]["source_packet"]
    job = copy.deepcopy(envelope["preparation"]["predecessor"]["job"])
    job["packet"] = json.dumps(packet)
    job["draft"] = json.dumps(draft)
    job["review"] = json.dumps(packet["final_review_result"]["review"])
    return job


def ordinary_job(image_bytes):
    sha = hashlib.sha256(image_bytes).hexdigest()
    image = {
        "generated": False, "sha256": sha, "local_path": f"media/{sha}.jpg",
        "url": f"https://uutistenlukija.fi/media/{sha}.jpg",
        "source_url": "https://example.org/synthetic-photo", "license_url": "https://example.org/license",
        "license": "Synthetic test permission", "alt": "Synthetic ordinary image",
        "credit": "Synthetic photographer", "caption": "Synthetic ordinary image",
    }
    source = {
        "id": "A", "url": "https://example.org/synthetic-story", "publisher": "Synthetic publisher",
        "title": "Synthetic ordinary source", "published_at": "2026-10-02T00:00:00+00:00",
        "text": "Synthetic source text. " * 20,
    }
    packet = {"fixture": False, "sources": [source], "image": image}
    draft = {
        "title": "Ordinary synthetic story", "summary": "An ordinary synthetic summary.",
        "category": "Tiede", "image": image,
        "paragraphs": [
            {"text": "Ordinary synthetic paragraph one.", "source_ids": ["A"]},
            {"text": "Ordinary synthetic paragraph two.", "source_ids": ["A"]},
        ],
    }
    review = {"approved": True, "draft_sha256": digest(draft), "reasons": ["Synthetic test approval."]}
    job = {
        "id": "2" * 64, "created_at": "2026-10-02T00:00:00+00:00",
        "packet": json.dumps(packet), "draft": json.dumps(draft), "review": json.dumps(review),
    }
    return job, sha


def stale_policy_amendment():
    """Rebind a synthetic composite to an old policy digest; no validator is mocked."""
    packet, draft = portable_amendment()
    artifact = json.loads(packet["preparation_json"])
    for index, role in enumerate(("original", "update")):
        capture = artifact["captures"][role]
        capture["packet"]["publication_basis"]["policy_sha256"] = "0" * 64
        capture["receipt"]["packet_sha256"] = digest(capture["packet"])
        packet_raw, receipt_raw = encode(capture["packet"]), encode(capture["receipt"])
        capture["binding"] = {
            "packet_sha256": hashlib.sha256(packet_raw.encode()).hexdigest(),
            "receipt_sha256": hashlib.sha256(receipt_raw.encode()).hexdigest(),
        }
        artifact["evidence"][role + "_capture"] = copy.deepcopy(capture["binding"])
        artifact["rights"][index]["publication_basis"] = copy.deepcopy(
            capture["packet"]["publication_basis"])
        packet["capture_json"][role] = {"packet": packet_raw, "receipt": receipt_raw}

    original = artifact["captures"]["original"]["packet"]
    publication = artifact["predecessor"]["publication"]
    artifact["predecessor"]["job"]["packet"] = encode(original)
    publication["packet_sha"] = digest(original)
    artifact["evidence"]["predecessor_packet_sha256"] = digest(original)
    artifact["evidence"]["predecessor_publication_sha256"] = digest(publication)
    raw = encode(artifact)
    envelope = build_review_envelope(raw.encode())
    image = copy.deepcopy(draft["image"])
    selection = copy.deepcopy(packet["selection"])
    selection["preparation_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    selection_raw = encode(selection) + "\n"
    old_envelope = packet["final_review_input"]["source_packet"]
    envelope.update(
        schema="private-amendment-combined-review-envelope-v1",
        scope="COMBINED FINAL TEXT AND IMAGE REVIEW; NO ACTIVATION OR RELEASE AUTHORITY",
        final_draft=copy.deepcopy(draft), final_image=image,
        selection_bytes_sha256=hashlib.sha256(selection_raw.encode()).hexdigest(),
        independent_image_assessment=copy.deepcopy(old_envelope["independent_image_assessment"]),
    )
    envelope["bindings"].update(final_draft_sha256=digest(draft), final_image_sha256=digest(image))
    envelope["validation"].update(
        capture_reconstruction="Both exact original captures passed media(policy_gate=True) and verify_intake in this execution",
        exact_final_image_execution="Fresh installed article-first selection and pixel review, validated against complete final draft; exact local image SHA verified",
    )
    context = {
        "operation": "published_amendment_combined_review",
        "review_envelope_sha256": digest(envelope), "original_canonical": envelope["public_metadata"]["canonical"],
        "source_relationship": envelope["source_relationship"], "actual_diff": envelope["actual_diff"],
        "normal_activation": False, "release_authorization": False,
    }
    request = {"source_packet": envelope, "context": context, "draft": draft, "draft_sha256": digest(draft)}
    result = copy.deepcopy(packet["final_review_result"])
    result.update(final_draft_sha256=digest(draft), review_envelope_sha256=digest(envelope),
                  preparation_sha256=selection["preparation_sha256"],
                  selection_bytes_sha256=envelope["selection_bytes_sha256"], image_sha256=image["sha256"])
    prompt = packet["reviewer_prompt"]["text"]
    result["same_call_receipt"]["prompt_sha256"] = hashlib.sha256(
        (prompt + "\n\nINPUT JSON:\n" + encode(request)).encode()).hexdigest()
    result["same_call_receipt"]["response_sha256"] = digest(result["review"])
    packet.update(preparation_json=raw, selection=selection, selection_json=selection_raw,
                  final_review_input=request, final_review_result=result, version={})
    set_version(packet)
    return packet, draft


class AmendmentRendererTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "state"

    def write_image(self, draft, data=IMAGE_BYTES):
        path = self.state / draft["image"]["local_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_real_render_site_and_hosted_gate_use_authenticated_projection(self):
        packet, draft = portable_amendment()
        before = copy.deepcopy(packet)
        job = amendment_job(packet, draft)
        self.write_image(draft)
        output = self.root / "site"
        store = TinyStore([job])

        self.assertEqual(site.render_site(store, output, self.state, public=True,
                                          verify_policy_ids=set()), 1)
        metadata = packet["final_review_input"]["source_packet"]["public_metadata"]
        name = metadata["canonical"].removeprefix("https://uutistenlukija.fi/").rstrip("/") + "/index.html"
        article = output / name
        rendered = article.read_text()
        self.assertEqual(packet, before)
        self.assertEqual(store.rendered, [job["id"]])
        self.assertIn(f'<link rel="canonical" href="{metadata["canonical"]}">', rendered)
        self.assertIn(site.article_status_html(metadata["notice"]), rendered)
        self.assertIn(site.time_html(metadata["datePublished"]), rendered)
        citations = packet["final_review_input"]["source_packet"]["preparation"]["citations"]
        urls = [item["capture_source"]["url"] for item in citations]
        self.assertLess(rendered.index(urls[0]), rendered.index(urls[1]))
        body = rendered.split('<div class="content">', 1)[1].split("</div>", 1)[0]
        for paragraph in draft["paragraphs"]:
            self.assertEqual(body.count(paragraph["text"]), 1)
        check_article(rendered, packet, draft, canonical=metadata["canonical"])

        binding = media(packet, draft)
        image_name = "mvp-assets/" + binding["image_sha256"] + ".jpg"
        files = {str(path.relative_to(output)): path.read_bytes()
                 for path in output.rglob("*") if path.is_file()}
        self.assertIn(image_name, files)
        receipt = {
            "schema_version": 3, "packet": packet, "draft": draft,
            "review": packet["final_review_result"]["review"], "packet_sha256": digest(packet),
            "draft_sha256": digest(draft), "job_id": job["id"],
            "source_commit": packet["final_review_result"]["source_ref"], **binding,
            "public_release_authorized": True, "hermes_step": 5,
            "origin": "https://uutistenlukija.fi", "ga4_id": "G-35XERS8V6J",
            "new_article_files": [name],
            "files": {path: hashlib.sha256(data).hexdigest() for path, data in files.items()},
        }
        self.assertEqual(check(output, receipt), len(files))

    def test_row_and_predecessor_identity_mismatches_refuse_before_article_write(self):
        packet, draft = portable_amendment()
        base = amendment_job(packet, draft)
        self.write_image(draft)
        mutations = {
            "row review": lambda job: json.loads(job["review"]) | {"reasons": ["Different row review"]},
            "job id": lambda job: "f" * 64,
            "created at": lambda job: "2026-10-01T00:00:01+00:00",
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                job = copy.deepcopy(base)
                if label == "row review":
                    job["review"] = json.dumps(mutation(job))
                elif label == "job id":
                    job["id"] = mutation(job)
                else:
                    job["created_at"] = mutation(job)
                output = self.root / label.replace(" ", "-")
                with self.assertRaises(ValueError):
                    site.render_site(TinyStore([job]), output, self.state, public=True)
                self.assertFalse(any(output.glob("uutiset/*/index.html")))

    def test_amendment_never_receives_archive_policy_exemption(self):
        packet, draft = stale_policy_amendment()
        self.assertIn("amendment", media(packet, draft, policy_gate=False))
        self.write_image(draft)
        with self.assertRaisesRegex(ValueError, "Missing exact text-only policy"):
            site.render_site(TinyStore([amendment_job(packet, draft)]), self.root / "stale",
                             self.state, public=True, verify_policy_ids=set())

    def test_mixed_ordinary_and_amendment_render_keeps_both_routes(self):
        packet, draft = portable_amendment()
        amendment = amendment_job(packet, draft)
        self.write_image(draft)
        ordinary_bytes = b"ordinary synthetic image bytes"
        ordinary, ordinary_sha = ordinary_job(ordinary_bytes)
        ordinary_path = self.state / "media" / (ordinary_sha + ".jpg")
        ordinary_path.write_bytes(ordinary_bytes)
        output = self.root / "mixed"
        self.assertEqual(site.render_site(TinyStore([amendment, ordinary]), output, self.state,
                                          public=True, verify_policy_ids={ordinary["id"]}), 2)
        amendment_html = (output / site.article_path(amendment) / "index.html").read_text()
        check_article(amendment_html, packet, draft,
                      canonical=packet["final_review_input"]["source_packet"]["public_metadata"]["canonical"])
        self.assertTrue((output / site.article_path(ordinary) / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
