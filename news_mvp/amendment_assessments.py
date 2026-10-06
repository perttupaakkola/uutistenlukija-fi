"""Pure, non-activating binding of amendment preparation assessments.

This module only binds caller-supplied bytes.  It does not read files, use a
database or network, accept an amendment, or satisfy any publication gate.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from news_mvp.release_contract import digest
from news_mvp.site import SITE_URL, article_path


MAX_ARTIFACT_BYTES = 256 * 1024
MAX_FULLTEXT_REVIEW_BYTES = 64 * 1024
MAX_IMAGE_ASSESSMENT_BYTES = 64 * 1024
MAX_RETAINED_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PARAGRAPHS = 40
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

_ARTIFACT_FIELDS = {
    "schema", "preparation_only", "approval", "activation", "acceptance",
    "predecessor", "evidence", "identity", "captures",
    "validation_drafts_purpose", "candidate_manuscript", "citations",
    "rights", "projection_kind",
}
_FULLTEXT_FIELDS = {
    "schema", "reviewed_at", "scope", "artifact_path", "artifact_bytes",
    "artifact_sha256", "candidate_manuscript_sha256",
    "candidate_manuscript_canonical_bytes", "canonical_digest_definition",
    "predecessor_review_reused", "paragraphs_read", "paragraph_reviews",
    "source_reviews", "title_summary_category_review",
    "changed_text_paragraphs", "corrected_paragraph_verdict",
    "factual_verdict", "attribution_verdict", "editorial_verdict",
    "textual_pass", "supported_claims", "unsupported_claims",
    "rights_verdict", "downstream_requirements", "limitations",
    "image_approval", "release_authorization", "activation_authorization",
    "installed_publication_approval",
}
_IMAGE_FIELDS = {
    "schema", "assessment_type", "scope", "bindings",
    "complete_text_review_basis", "exact_retained_metadata_evidence",
    "fresh_conceptual_fit", "independent_pixel_inspection", "issues",
    "ranked_article_supported_image_concepts",
}


@dataclass(frozen=True)
class AmendmentAssessmentBinding:
    """Hash-bound observations that deliberately confer no approval."""

    artifact_sha256: str
    fulltext_review_sha256: str
    image_assessment_sha256: str
    retained_image_sha256: str
    candidate_manuscript_sha256: str
    public_canonical_url: str
    paragraph_count: int
    fit_score: float
    ignored_ancillary_fulltext_canonical: str
    schema: str = "published-amendment-assessment-binding-v1"
    preparation_only: bool = True
    normal_approval: bool = False
    activation: bool = False
    release_authorization: bool = False
    licensing_certification: bool = False
    fresh_network_proof: bool = False
    observations_only: bool = True
    semantic_authentication: bool = False


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _json_object(raw, label, maximum):
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise ValueError(f"{label} must be nonempty bounded bytes")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("Nonfinite JSON")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label} JSON") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value


def _embedded_object(value, label):
    if type(value) is not str or len(value.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Invalid embedded {label}")
    return _json_object(value.encode("utf-8"), label, MAX_ARTIFACT_BYTES)


def _canonical_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _raw_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fields(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"Unexpected {label} schema")
    return value


def _list(value, label, minimum=0, maximum=MAX_PARAGRAPHS):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError(f"Invalid {label}")
    return value


def _text(value, label, maximum=20000, empty=False):
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"Invalid {label}")
    return value


def _sha(value, label):
    if type(value) is not str or SHA256.fullmatch(value) is None:
        raise ValueError(f"Invalid {label}")
    return value


def _integer(value, label, minimum=0, maximum=2**31 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid {label}")
    return value


def _is(value, expected, label):
    if type(value) is not type(expected) or value != expected:
        raise ValueError(f"Invalid {label}")


def _instant(value, label):
    _text(value, label, 100)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid {label}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Invalid {label}")
    return parsed


def _coverage(coverage, raw, label):
    _fields(coverage, {
        "encoding", "bytes", "sha256", "reviewed_byte_range",
        "complete_text_read", "includes_navigation_and_keyword_tail",
    }, label)
    _is(coverage["encoding"], "UTF-8", label + " encoding")
    _integer(coverage["bytes"], label + " bytes")
    if coverage["bytes"] != len(raw):
        raise ValueError(label + " byte count differs")
    if _sha(coverage["sha256"], label + " sha256") != _raw_sha(raw):
        raise ValueError(label + " digest differs")
    byte_range = coverage["reviewed_byte_range"]
    if (type(byte_range) is not list or len(byte_range) != 2 or
            type(byte_range[0]) is not int or type(byte_range[1]) is not int or
            byte_range != [0, len(raw)]):
        raise ValueError(label + " is not complete byte coverage")
    _is(coverage["complete_text_read"], True, label + " complete_text_read")
    _is(coverage["includes_navigation_and_keyword_tail"], True,
        label + " includes_navigation_and_keyword_tail")


def _artifact(artifact):
    _fields(artifact, _ARTIFACT_FIELDS, "preparation artifact")
    _is(artifact["schema"], "published-amendment-artifact-preparation-v1", "artifact schema")
    _is(artifact["preparation_only"], True, "artifact preparation_only")
    _is(artifact["approval"], False, "artifact approval")
    _is(artifact["activation"], False, "artifact activation")
    _is(artifact["acceptance"],
        "frozen-preparation-hash-only; fresh-fulltext-and-image-approval-and-CAS-required",
        "artifact acceptance")
    _is(artifact["projection_kind"],
        "amendment-only-two-capture-roles-not-ordinary-packet", "artifact projection")
    _is(artifact["validation_drafts_purpose"],
        "capture-validation-provenance-only-not-amendment-approval",
        "validation draft purpose")

    predecessor = _fields(artifact["predecessor"], {"job", "publication"}, "predecessor")
    job = _fields(predecessor["job"], {
        "id", "story_key", "source_url", "packet", "draft", "review", "status",
        "created_at", "attempts", "next_attempt", "error", "adapter",
    }, "predecessor job")
    publication = _fields(predecessor["publication"], {
        "job_id", "packet_sha", "draft_sha", "image_sha", "source_commit",
        "remote_commit", "run_id", "status", "attempts", "error",
    }, "predecessor publication")
    predecessor_packet = _embedded_object(job["packet"], "predecessor packet")
    predecessor_draft = _embedded_object(job["draft"], "predecessor draft")
    job_id = _sha(job["id"], "predecessor job id")
    _text(predecessor_draft.get("title"), "predecessor title", 300)
    retained_image = predecessor_draft.get("image")
    if type(retained_image) is not dict:
        raise ValueError("Predecessor draft has no retained image metadata")

    evidence = _fields(artifact["evidence"], {
        "schema", "job_id", "predecessor_packet_sha256",
        "predecessor_draft_sha256", "predecessor_publication_sha256",
        "original_capture", "update_capture", "reason", "updated_at",
    }, "artifact evidence")
    _is(evidence["schema"], "published-amendment-preparation-v1", "evidence schema")
    _instant(evidence["updated_at"], "evidence updated_at")
    _text(evidence["reason"], "evidence reason", 2000)
    identity = _fields(artifact["identity"], {"id", "story_key", "source_url", "created_at"}, "artifact identity")
    for key in identity:
        if identity[key] != job[key]:
            raise ValueError("Artifact identity differs from predecessor")
    if evidence["job_id"] != job_id or publication["job_id"] != job_id:
        raise ValueError("Predecessor job identity differs")
    if (evidence["predecessor_packet_sha256"] != digest(predecessor_packet) or
            evidence["predecessor_draft_sha256"] != digest(predecessor_draft) or
            evidence["predecessor_publication_sha256"] != digest(publication) or
            publication["packet_sha"] != digest(predecessor_packet) or
            publication["draft_sha"] != digest(predecessor_draft)):
        raise ValueError("Predecessor canonical identity differs")

    candidate = _fields(artifact["candidate_manuscript"],
                        {"category", "title", "summary", "paragraphs"},
                        "candidate manuscript")
    for key, maximum in (("category", 100), ("title", 300), ("summary", 3000)):
        _text(candidate[key], "candidate " + key, maximum)
    if (candidate["title"] != predecessor_draft.get("title") or
            candidate["category"] != predecessor_draft.get("category")):
        raise ValueError("Candidate public identity differs from predecessor")
    paragraphs = _list(candidate["paragraphs"], "candidate paragraphs", 1)

    captures = _fields(artifact["captures"], {"original", "update"}, "captures")
    citations = _list(artifact["citations"], "citations", 2, 2)
    rights = _list(artifact["rights"], "rights", 2, 2)
    role_data = {}
    for index, role in enumerate(("original", "update")):
        capture = _fields(captures[role], {"packet", "receipt", "binding", "validation_draft"}, role + " capture")
        packet = capture["packet"]
        receipt = capture["receipt"]
        binding = _fields(capture["binding"], {"packet_sha256", "receipt_sha256"}, role + " capture binding")
        evidence_binding = _fields(evidence[role + "_capture"],
                                   {"packet_sha256", "receipt_sha256"}, role + " evidence binding")
        if binding != evidence_binding:
            raise ValueError("Capture binding differs from evidence")
        _sha(binding["packet_sha256"], role + " raw packet digest")
        _sha(binding["receipt_sha256"], role + " raw receipt digest")
        if type(packet) is not dict or type(receipt) is not dict:
            raise ValueError("Embedded capture objects required")
        sources = packet.get("sources")
        documents = packet.get("supporting_documents")
        if type(sources) is not list or len(sources) != 1 or type(sources[0]) is not dict:
            raise ValueError("Exactly one embedded capture source required")
        if type(documents) is not list or len(documents) != 1 or type(documents[0]) is not dict:
            raise ValueError("Exactly one embedded rights document required")
        source = sources[0]
        citation = _fields(citations[index], {"id", "role", "capture_source"}, role + " citation")
        expected_citation = f"amendment:{role}:A"
        if (citation["id"] != expected_citation or citation["role"] != role or
                citation["capture_source"] != source or source.get("id") != "A"):
            raise ValueError("Citation does not equal embedded capture source")
        right = _fields(rights[index], {"id", "role", "publication_basis", "reuse", "document"}, role + " rights")
        if (right["id"] != f"amendment:{role}:RIGHTS" or right["role"] != role or
                right["publication_basis"] != packet.get("publication_basis") or
                right["reuse"] != source.get("reuse") or right["document"] != documents[0]):
            raise ValueError("Rights projection differs from embedded capture")
        if receipt.get("packet_sha256") != digest(packet):
            raise ValueError("Embedded receipt packet identity differs")
        role_data[role] = (capture, packet, receipt, binding, source, documents[0], citation)

    allowed_ids = {item[6]["id"] for item in role_data.values()}
    for paragraph in paragraphs:
        _fields(paragraph, {"text", "source_ids"}, "candidate paragraph")
        _text(paragraph["text"], "candidate paragraph text", 6000)
        ids = _list(paragraph["source_ids"], "candidate paragraph source_ids", 1, len(allowed_ids))
        if any(type(item) is not str or item not in allowed_ids for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("Candidate paragraph source identity differs")

    canonical = SITE_URL + article_path({"id": job_id, "draft": predecessor_draft})
    original_url = role_data["original"][4].get("url")
    if job.get("source_url") != original_url or canonical == original_url:
        raise ValueError("Public canonical and upstream source identity are confused")
    return candidate, paragraphs, retained_image, canonical, original_url, role_data, evidence, predecessor_draft


def _fulltext(review, raw, artifact_raw, candidate, paragraphs, role_data,
              evidence, predecessor_draft):
    _fields(review, _FULLTEXT_FIELDS, "fulltext review")
    _is(review["schema"], "independent-fulltext-editorial-review-v1", "fulltext schema")
    reviewed_at = _instant(review["reviewed_at"], "fulltext reviewed_at")
    if reviewed_at <= _instant(evidence["updated_at"], "evidence updated_at"):
        raise ValueError("Fulltext review predates the amendment preparation")
    _is(review["scope"],
        "Fresh independent full-text editorial review of exact embedded two-capture candidate only; not activation, image review, installed publication approval or release.",
        "fulltext scope")
    _text(review["artifact_path"], "fulltext artifact_path", 4096)
    _integer(review["artifact_bytes"], "fulltext artifact_bytes")
    if review["artifact_bytes"] != len(artifact_raw) or review["artifact_sha256"] != _raw_sha(artifact_raw):
        raise ValueError("Fulltext review artifact byte identity differs")
    candidate_raw = _canonical_bytes(candidate)
    candidate_sha = digest(candidate)
    if (review["candidate_manuscript_sha256"] != candidate_sha or
            review["candidate_manuscript_canonical_bytes"] != len(candidate_raw)):
        raise ValueError("Fulltext candidate identity differs")
    _is(review["canonical_digest_definition"],
        "SHA256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(comma, colon)).encode(UTF-8)); matches news_mvp/amendments.py _digest",
        "fulltext canonical digest definition")
    _is(review["predecessor_review_reused"], False, "predecessor review reuse")
    _is(review["textual_pass"], True, "fulltext textual pass")
    for field in ("image_approval", "release_authorization", "activation_authorization", "installed_publication_approval"):
        _is(review[field], False, "fulltext " + field)

    count = len(paragraphs)
    _integer(review["paragraphs_read"], "paragraphs_read", 1, MAX_PARAGRAPHS)
    if review["paragraphs_read"] != count:
        raise ValueError("Fulltext paragraph count differs")
    paragraph_reviews = _list(review["paragraph_reviews"], "paragraph reviews", count, count)
    claims = []
    for index, (paragraph, item) in enumerate(zip(paragraphs, paragraph_reviews), 1):
        _fields(item, {"paragraph", "text_sha256", "full_text_read", "source_ids",
                       "supported_claims", "unsupported_claims", "verdict", "editorial_note"},
                "paragraph review")
        if type(item["paragraph"]) is not int or item["paragraph"] != index:
            raise ValueError("Paragraph reviews must be ordered 1..N")
        if item["text_sha256"] != _raw_sha(paragraph["text"].encode("utf-8")):
            raise ValueError("Reviewed paragraph text differs")
        _is(item["full_text_read"], True, "paragraph full_text_read")
        if item["source_ids"] != paragraph["source_ids"]:
            raise ValueError("Reviewed paragraph source ids differ")
        claim = _text(item["supported_claims"], "supported paragraph claims", 6000)
        claims.append(claim)
        _is(item["unsupported_claims"], [], "paragraph unsupported claims")
        _is(item["verdict"], "supported", "paragraph verdict")
        if item["editorial_note"] is not None:
            _text(item["editorial_note"], "paragraph editorial note", 6000)
    if review["supported_claims"] != claims:
        raise ValueError("Aggregate supported claims differ from paragraph reviews")
    _is(review["unsupported_claims"], [], "aggregate unsupported claims")

    source_reviews = _list(review["source_reviews"], "source reviews", 2, 2)
    source_fields = {
        "role", "citation_id", "url", "publisher", "published_at", "retrieved_at",
        "complete_source_text_coverage", "canonical_complete_source_object_bytes",
        "canonical_complete_source_object_sha256", "capture_binding_as_recorded",
        "embedded_packet_canonical_sha256", "embedded_receipt_canonical_sha256",
        "receipt_source_sha256_as_recorded", "raw_capture_file_bytes_reverified",
        "rights_document_text_coverage", "reuse_projection",
        "publication_basis_projection", "citation_projection_equals_capture_source",
    }
    for role, item in zip(("original", "update"), source_reviews):
        _fields(item, source_fields, role + " source review")
        capture, packet, receipt, binding, source, document, citation = role_data[role]
        expected = {
            "role": role, "citation_id": citation["id"], "url": source.get("url"),
            "publisher": source.get("publisher"), "published_at": source.get("published_at"),
            "retrieved_at": receipt.get("retrieved_at"),
        }
        if any(item[key] != value for key, value in expected.items()):
            raise ValueError("Reviewed source identity differs from embedded capture")
        source_text = _text(source.get("text"), role + " embedded source text", MAX_ARTIFACT_BYTES).encode("utf-8")
        _coverage(item["complete_source_text_coverage"], source_text, role + " source coverage")
        source_raw = _canonical_bytes(source)
        if (type(item["canonical_complete_source_object_bytes"]) is not int or
                item["canonical_complete_source_object_bytes"] != len(source_raw) or
                item["canonical_complete_source_object_sha256"] != digest(source)):
            raise ValueError("Canonical source object identity differs")
        if item["capture_binding_as_recorded"] != binding:
            raise ValueError("Recorded raw capture binding differs")
        if (item["embedded_packet_canonical_sha256"] != digest(packet) or
                item["embedded_receipt_canonical_sha256"] != digest(receipt)):
            raise ValueError("Canonical embedded capture identity differs")
        if item["receipt_source_sha256_as_recorded"] != receipt.get("source_sha256"):
            raise ValueError("Recorded raw source capture identity differs")
        _is(item["raw_capture_file_bytes_reverified"], False, "raw capture reverified")
        rights_text = _text(document.get("text"), role + " rights text", MAX_ARTIFACT_BYTES).encode("utf-8")
        _coverage(item["rights_document_text_coverage"], rights_text, role + " rights coverage")
        if (item["reuse_projection"] != source.get("reuse") or
                item["publication_basis_projection"] != packet.get("publication_basis")):
            raise ValueError("Reviewed source projections differ")
        if packet.get("publication_basis", {}).get("source_fields_sha256") != digest(source):
            raise ValueError("Embedded source-fields identity differs")
        _is(item["citation_projection_equals_capture_source"], True, "citation projection equality")
        if citation["capture_source"] != source:
            raise ValueError("Citation projection differs")

    summary_review = _fields(review["title_summary_category_review"], {
        "title_supported", "summary_supported", "category_appropriate",
        "title_unchanged", "summary_unchanged", "category_unchanged",
    }, "title summary category review")
    for key, value in summary_review.items():
        _is(value, True, key)
    changed = _list(review["changed_text_paragraphs"], "changed paragraphs", 1, count)
    if (any(type(value) is not int or not 1 <= value <= count for value in changed) or
            changed != sorted(set(changed))):
        raise ValueError("Changed paragraph indices are invalid")
    corrected = _fields(review["corrected_paragraph_verdict"], {
        "paragraph", "verdict", "new_source_exact_support",
        "old_source_exact_support", "analysis",
    }, "corrected paragraph verdict")
    if type(corrected["paragraph"]) is not int or corrected["paragraph"] not in changed:
        raise ValueError("Corrected paragraph is not identified as changed")
    _is(corrected["verdict"], "pass", "corrected paragraph verdict")
    for key in ("new_source_exact_support", "old_source_exact_support", "analysis"):
        _text(corrected[key], "corrected paragraph " + key, 10000)
    for key in ("factual_verdict", "attribution_verdict", "editorial_verdict", "rights_verdict"):
        _text(review[key], key, 10000)
    limitations = _list(review["limitations"], "fulltext limitations", 1, 20)
    for limitation in limitations:
        _text(limitation, "fulltext limitation", 5000)

    downstream = _fields(review["downstream_requirements"], {
        "genuine_visible_update_notice_required", "reason", "updated_at",
        "notice_recommendation", "preserve_original_canonical",
        "preserve_datePublished", "preserve_title", "preserve_category",
        "notice_rendered_or_installed",
    }, "downstream requirements")
    _is(downstream["genuine_visible_update_notice_required"], True, "visible update notice")
    _is(downstream["notice_rendered_or_installed"], False, "notice installation")
    if downstream["reason"] != evidence["reason"] or downstream["updated_at"] != evidence["updated_at"]:
        raise ValueError("Update notice identity differs")
    _text(downstream["notice_recommendation"], "notice recommendation", 5000)
    _text(downstream["preserve_original_canonical"], "ignored ancillary canonical", 4096)
    if (downstream["preserve_title"] != predecessor_draft.get("title") or
            downstream["preserve_category"] != predecessor_draft.get("category")):
        raise ValueError("Preserved title/category identity differs")
    _text(downstream["preserve_datePublished"], "preserve datePublished", 100)
    return candidate_sha, downstream["preserve_original_canonical"]


def _retained_metadata(review, image):
    fields = {
        "source", "source_url", "provenance_photo_id", "provenance_title",
        "identity_status", "year_status", "exact_capture_date", "credit",
        "license_recorded", "license_url_recorded", "changes_recorded",
        "provenance_retrieved_at", "stock_provenance_sha256_recorded",
        "alt_recorded", "caption_recorded", "rights_status", "excluded_rights_basis",
    }
    _fields(review, fields, "retained metadata evidence")
    _is(review["source"],
        "JSON-decoded preparation.predecessor.job.draft.image; image.stock_provenance supplies image-specific provenance, not preparation.rights",
        "retained metadata source")
    provenance = image.get("stock_provenance")
    if type(provenance) is not dict or type(provenance.get("attribution")) is not dict:
        raise ValueError("Retained stock provenance missing")
    expected = {
        "source_url": image.get("source_url"),
        "provenance_photo_id": provenance.get("photo_id"),
        "provenance_title": provenance["attribution"].get("title"),
        "credit": image.get("credit"),
        "license_recorded": image.get("license"),
        "license_url_recorded": image.get("license_url"),
        "changes_recorded": provenance["attribution"].get("changes"),
        "provenance_retrieved_at": provenance.get("retrieved_at"),
        "stock_provenance_sha256_recorded": image.get("stock_provenance_sha256"),
        "alt_recorded": image.get("alt"),
        "caption_recorded": image.get("caption"),
    }
    if any(review[key] != value for key, value in expected.items()):
        raise ValueError("Image assessment retained metadata differs")
    if image.get("stock_provenance_sha256") != digest(provenance):
        raise ValueError("Retained stock provenance digest differs")
    for key in ("identity_status", "year_status", "exact_capture_date",
                "rights_status", "excluded_rights_basis"):
        _text(review[key], "retained metadata " + key, 10000)


def _image_assessment(review, artifact_raw, fulltext, candidate, paragraphs,
                      retained_image, canonical, original_url, candidate_sha,
                      retained_image_raw):
    _fields(review, _IMAGE_FIELDS, "image assessment")
    _is(review["schema"], "fresh-scoped-image-assessment-v1", "image assessment schema")
    _is(review["assessment_type"],
        "Reader-benefit review of retained image against complete corrected manuscript; not normal model approval",
        "image assessment type")
    scope = _fields(review["scope"], {
        "preparation_only", "normal_model_approval", "licensing_certification",
        "release_authorization", "activation", "new_stock_searches_performed",
        "credentials_or_model_provider_calls", "source_state_or_repository_changes",
        "prior_image_scores_or_approval_used_as_truth", "visual_surface",
    }, "image assessment scope")
    _is(scope["preparation_only"], True, "image preparation_only")
    for key in ("normal_model_approval", "licensing_certification",
                "release_authorization", "activation", "new_stock_searches_performed",
                "credentials_or_model_provider_calls", "source_state_or_repository_changes",
                "prior_image_scores_or_approval_used_as_truth"):
        _is(scope[key], False, "image scope " + key)
    _text(scope["visual_surface"], "image visual surface", 5000)

    bindings = _fields(review["bindings"], {
        "preparation_path", "preparation_bytes", "preparation_sha256_computed",
        "candidate_manuscript_sha256_computed", "candidate_digest_method",
        "candidate_paragraph_count_read", "candidate_title", "public_canonical_url",
        "original_upstream_url", "image_sha256_exact_retained_metadata",
        "actual_live_image_url_supplied", "original_draft_image_url",
        "image_byte_digest_independently_recomputed", "image_byte_verification_limitation",
        "screenshot_path", "screenshot_sha256_computed", "screenshot_bytes",
        "screenshot_context_supplied",
    }, "image assessment bindings")
    if bindings["preparation_path"] != fulltext["artifact_path"]:
        raise ValueError("Image and fulltext preparation path identities differ")
    if (type(bindings["preparation_bytes"]) is not int or
            bindings["preparation_bytes"] != len(artifact_raw) or
            bindings["preparation_sha256_computed"] != _raw_sha(artifact_raw)):
        raise ValueError("Image assessment preparation identity differs")
    if (bindings["candidate_manuscript_sha256_computed"] != candidate_sha or
            type(bindings["candidate_paragraph_count_read"]) is not int or
            bindings["candidate_paragraph_count_read"] != len(paragraphs) or
            bindings["candidate_title"] != candidate["title"]):
        raise ValueError("Image assessment candidate identity differs")
    _text(bindings["candidate_digest_method"], "image candidate digest method", 2000)
    if bindings["public_canonical_url"] != canonical:
        raise ValueError("Image assessment public canonical differs")
    if bindings["original_upstream_url"] != original_url:
        raise ValueError("Image assessment upstream URL differs")
    if canonical == original_url or bindings["public_canonical_url"] == bindings["original_upstream_url"]:
        raise ValueError("Public canonical cannot be an upstream source URL")

    image_sha = _raw_sha(retained_image_raw)
    metadata_sha = _sha(retained_image.get("sha256"), "retained image metadata sha256")
    if image_sha != metadata_sha or bindings["image_sha256_exact_retained_metadata"] != image_sha:
        raise ValueError("Supplied retained image bytes differ")
    if bindings["original_draft_image_url"] != retained_image.get("url"):
        raise ValueError("Original draft image URL differs")
    live_url = _text(bindings["actual_live_image_url_supplied"], "actual live image URL", 4096)
    parts = urlsplit(live_url)
    if parts.scheme != "https" or parts.hostname != urlsplit(SITE_URL).hostname or not parts.path.endswith("/" + image_sha + ".jpg"):
        raise ValueError("Actual live image URL does not bind retained image")
    if type(bindings["image_byte_digest_independently_recomputed"]) is not bool:
        raise ValueError("Invalid prior image-byte verification statement")
    _text(bindings["image_byte_verification_limitation"], "image byte limitation", 5000)
    _text(bindings["screenshot_path"], "screenshot path", 4096)
    screenshot_sha = _sha(bindings["screenshot_sha256_computed"], "screenshot sha256")
    if screenshot_sha == image_sha:
        raise ValueError("Screenshot digest cannot substitute for retained image bytes")
    _integer(bindings["screenshot_bytes"], "screenshot bytes", 1)
    _text(bindings["screenshot_context_supplied"], "screenshot context", 5000)

    basis = review["complete_text_review_basis"]
    paragraphs_key = f"paragraphs_1_to_{len(paragraphs)}"
    _fields(basis, {paragraphs_key, "interpretation"}, "complete image text basis")
    summaries = _list(basis[paragraphs_key], "image paragraph summaries", len(paragraphs), len(paragraphs))
    for summary in summaries:
        _text(summary, "image paragraph summary", 3000)
    _text(basis["interpretation"], "image text interpretation", 10000)

    concepts = _list(review["ranked_article_supported_image_concepts"], "ranked image concepts", 1, 10)
    for rank, concept in enumerate(concepts, 1):
        _fields(concept, {"rank", "concept", "support", "reader_benefit", "boundary"}, "image concept")
        if type(concept["rank"]) is not int or concept["rank"] != rank:
            raise ValueError("Image concept ranks must be ordered")
        for key in ("concept", "support", "reader_benefit", "boundary"):
            _text(concept[key], "image concept " + key, 5000)

    pixels = _fields(review["independent_pixel_inspection"], {
        "observed", "quality_and_reader_value", "not_inferred_from_pixels", "limitation",
    }, "independent pixel inspection")
    for key in ("observed", "quality_and_reader_value", "limitation"):
        _text(pixels[key], "pixel inspection " + key, 10000)
    not_inferred = _list(pixels["not_inferred_from_pixels"], "pixel non-inferences", 1, 20)
    for item in not_inferred:
        _text(item, "pixel non-inference", 1000)

    _retained_metadata(review["exact_retained_metadata_evidence"], retained_image)
    fit = _fields(review["fresh_conceptual_fit"], {
        "score_out_of_10", "meets_at_least_8", "basis", "limitations",
        "unsupported_claims_to_avoid", "retaining_after_new_approval_reasonable",
        "retention_conditions",
    }, "fresh conceptual fit")
    score = fit["score_out_of_10"]
    if type(score) not in (int, float) or not math.isfinite(score) or not 8 <= score <= 10:
        raise ValueError("Fresh image fit score must be finite and between 8 and 10")
    _is(fit["meets_at_least_8"], True, "image fit threshold")
    _is(fit["retaining_after_new_approval_reasonable"], True, "conditional retention")
    for key in ("basis", "retention_conditions"):
        _text(fit[key], "image fit " + key, 10000)
    for key in ("limitations", "unsupported_claims_to_avoid"):
        items = _list(fit[key], "image fit " + key, 1, 30)
        for item in items:
            _text(item, "image fit " + key, 3000)
    issues = _list(review["issues"], "image assessment issues", 0, 30)
    for issue in issues:
        _text(issue, "image assessment issue", 5000)
    return float(score), image_sha


def bind_assessments(artifact_bytes, fulltext_review_bytes,
                     image_assessment_bytes, retained_image_bytes):
    """Bind exact preparation/review/image bytes without approving anything.

    The returned value records prior scoped observations.  Even a successful
    result requires a later, distinct normal approval and activation gate.
    Local retained image bytes are not fresh network or licensing proof.
    """
    artifact = _json_object(artifact_bytes, "artifact", MAX_ARTIFACT_BYTES)
    fulltext = _json_object(fulltext_review_bytes, "fulltext review", MAX_FULLTEXT_REVIEW_BYTES)
    image_review = _json_object(image_assessment_bytes, "image assessment", MAX_IMAGE_ASSESSMENT_BYTES)
    if (type(retained_image_bytes) is not bytes or not retained_image_bytes or
            len(retained_image_bytes) > MAX_RETAINED_IMAGE_BYTES):
        raise ValueError("Retained image must be nonempty bounded bytes")

    (candidate, paragraphs, retained_image, canonical, original_url, role_data,
     evidence, predecessor_draft) = _artifact(artifact)
    candidate_sha, ignored_canonical = _fulltext(
        fulltext, fulltext_review_bytes, artifact_bytes, candidate, paragraphs,
        role_data, evidence, predecessor_draft,
    )
    score, image_sha = _image_assessment(
        image_review, artifact_bytes, fulltext, candidate, paragraphs,
        retained_image, canonical, original_url, candidate_sha,
        retained_image_bytes,
    )
    return AmendmentAssessmentBinding(
        artifact_sha256=_raw_sha(artifact_bytes),
        fulltext_review_sha256=_raw_sha(fulltext_review_bytes),
        image_assessment_sha256=_raw_sha(image_assessment_bytes),
        retained_image_sha256=image_sha,
        candidate_manuscript_sha256=candidate_sha,
        public_canonical_url=canonical,
        paragraph_count=len(paragraphs),
        fit_score=score,
        ignored_ancillary_fulltext_canonical=ignored_canonical,
    )
