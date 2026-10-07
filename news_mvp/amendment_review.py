"""Fresh, non-activating text review of one complete amendment preparation."""
import copy
import hashlib
import json

from news_mvp import amendment_assessments as assessments
from news_mvp.editorial import (
    HermesModel,
    ROOT,
    digest,
    encode,
    timestamp,
    validate_draft,
    validate_review,
)


ROLE = "amendment_reviewer"
TEXT_SCOPE = "TEXT REVIEW ONLY"
NOT_RECONSTRUCTED = "NOT RECONSTRUCTED / NOT APPROVED"


def _clone(value):
    return json.loads(encode(value))


def _private_text_validation(candidate, citations):
    """Run the ordinary validator without pretending the retained image is fresh.

    The preparation uses amendment-only citation identities, rather than an
    ordinary packet.  This private view supplies those identities.  Both image
    slots are deliberately null: the exact retained image stays in the review
    envelope, but its predecessor pixel review is stale for the changed text.
    """
    sources = []
    for citation in citations:
        source = _clone(citation["capture_source"])
        source["id"] = citation["id"]
        sources.append(source)
    draft = _clone(candidate)
    draft["image"] = None
    validate_draft(draft, {"sources": sources, "image": None})


def _paragraph_diff(before, after):
    changes = []
    for index, (old, new) in enumerate(zip(before, after), 1):
        if type(old) is not dict or type(old.get("text")) is not str or type(old.get("source_ids")) is not list:
            raise ValueError("Invalid predecessor paragraph")
        text_changed = old["text"] != new["text"]
        citations_changed = old["source_ids"] != new["source_ids"]
        if text_changed or citations_changed:
            changes.append({
                "index": index,
                "text": {"changed": text_changed, "before": old["text"], "after": new["text"]},
                "citations": {
                    "changed": citations_changed,
                    "before": _clone(old["source_ids"]),
                    "after": _clone(new["source_ids"]),
                },
            })
    if not any(change["text"]["changed"] for change in changes):
        raise ValueError("Amendment must change article text")
    return changes


def build_review_envelope(preparation_bytes):
    """Validate and derive the exact review input from preparation bytes only."""
    artifact = assessments._json_object(  # Reuse the installed strict decoder.
        preparation_bytes, "artifact", assessments.MAX_ARTIFACT_BYTES
    )
    (candidate, paragraphs, image, canonical, _original_url, _role_data,
     evidence, predecessor_draft) = assessments._artifact(artifact)

    if candidate["title"] != predecessor_draft.get("title") or candidate["category"] != predecessor_draft.get("category"):
        raise ValueError("Title/category must remain unchanged")
    before = predecessor_draft.get("paragraphs")
    if type(before) is not list or len(before) != len(paragraphs):
        raise ValueError("Amendment paragraph count must remain unchanged")
    changes = _paragraph_diff(before, paragraphs)
    _private_text_validation(candidate, artifact["citations"])

    job = artifact["predecessor"]["job"]
    published, modified = job["created_at"], evidence["updated_at"]
    if timestamp(modified) <= timestamp(published):
        raise ValueError("dateModified must follow datePublished")
    reason = evidence["reason"]
    if type(reason) is not str or not reason.strip() or len(reason) > 600:
        raise ValueError("Amendment notice must be nonempty and at most 600 characters")

    final_draft = _clone(candidate)
    final_draft["image"] = _clone(image)
    publishers = [item["capture_source"].get("publisher") for item in artifact["citations"]]
    same_publisher = bool(publishers) and len({str(value).casefold() for value in publishers}) == 1
    return {
        "schema": "normal-amendment-text-review-envelope-v1",
        "scope": TEXT_SCOPE,
        "preparation": _clone(artifact),
        "bindings": {
            "preparation_sha256": hashlib.sha256(preparation_bytes).hexdigest(),
            "predecessor_sha256": digest(artifact["predecessor"]),
            "candidate_manuscript_sha256": digest(candidate),
            "final_draft_sha256": digest(final_draft),
            "final_image_sha256": digest(image),
        },
        "final_draft": final_draft,
        "final_image": _clone(image),
        "public_metadata": {
            "canonical": canonical,
            "datePublished": published,
            "dateModified": modified,
            "notice": {"kind": "updated", "at": modified, "note": reason},
            "dateModified_status": "review input only; not a claim that publication occurred",
        },
        "actual_diff": {
            "title_changed": False,
            "category_changed": False,
            "summary": {
                "changed": predecessor_draft.get("summary") != candidate["summary"],
                "before": predecessor_draft.get("summary"),
                "after": candidate["summary"],
            },
            "paragraph_count_before": len(before),
            "paragraph_count_after": len(paragraphs),
            "paragraph_changes": changes,
            "text_change_indices": [item["index"] for item in changes if item["text"]["changed"]],
            "citation_change_indices": [item["index"] for item in changes if item["citations"]["changed"]],
        },
        "source_relationship": {
            "publishers": publishers,
            "same_publisher": same_publisher,
            "independent_corroboration_established": False,
        },
        "validation": {
            "preparation_artifact": "structurally parsed from supplied bytes only; does not authenticate source HTML",
            "capture_reconstruction": NOT_RECONSTRUCTED,
            "normal_validate_draft": "passed on private namespaced text view with image null",
            "exact_final_image_execution": NOT_RECONSTRUCTED,
        },
    }


def _context(envelope):
    return {
        "operation": "normal_amendment_text_review",
        "scope": TEXT_SCOPE,
        "review_envelope_sha256": digest(envelope),
        "draft_sha256": digest(envelope["final_draft"]),
        "capture_reconstruction": NOT_RECONSTRUCTED,
        "exact_final_image_execution": NOT_RECONSTRUCTED,
        "normal_approval": False,
        "activation": False,
        "release_authorization": False,
    }


def _expected_prompt_sha256(envelope, draft, context):
    request = {
        "source_packet": envelope,
        "context": context,
        "draft": draft,
        "draft_sha256": digest(draft),
    }
    prompt = (ROOT / "prompts" / (ROLE + ".md")).read_text() + "\n\nINPUT JSON:\n" + encode(request)
    return hashlib.sha256(prompt.encode()).hexdigest()


def _same_call_receipt(model, before, response, expected_prompt_sha256):
    receipts = getattr(model, "receipts", None)
    if type(receipts) is not list or len(receipts) != len(before) + 1 or receipts[:len(before)] != before:
        raise ValueError("Review requires exactly one newly appended same-call receipt")
    receipt = receipts[-1]
    if type(receipt) is not dict:
        raise ValueError("Review receipt is malformed")
    session = receipt.get("session_id")
    if (receipt.get("role") != ROLE or type(receipt.get("exit_code")) is not int
            or receipt["exit_code"] != 0 or type(session) is not str or not session.strip()
            or receipt.get("prompt_sha256") != expected_prompt_sha256
            or receipt.get("response_sha256") != digest(response)):
        raise ValueError("Review receipt is missing, stale, or not bound to this call")
    return copy.deepcopy(receipt)


def review_amendment(preparation_bytes, *, model, fixture=False):
    """Make one text-review call and return a result that cannot authorize release."""
    if fixture:
        if getattr(model, "name", None) != "fixture" or isinstance(model, HermesModel):
            raise ValueError("Injected execution must be explicitly labelled fixture")
    elif type(model) is not HermesModel:
        raise ValueError("Production amendment review requires HermesModel")
    receipts = getattr(model, "receipts", None)
    if type(receipts) is not list:
        raise ValueError("Review model must expose its append-only receipts")
    before = copy.deepcopy(receipts)
    receipt_list = receipts

    envelope = build_review_envelope(preparation_bytes)
    draft = _clone(envelope["final_draft"])
    envelope_sha, draft_sha = digest(envelope), digest(draft)
    context = _context(envelope)
    expected_prompt = _expected_prompt_sha256(envelope, draft, context)
    response = model.call(ROLE, envelope, draft, context=context)

    if model.receipts is not receipt_list or digest(envelope) != envelope_sha or digest(draft) != draft_sha:
        raise ValueError("Review call changed bound request identities")
    receipt = _same_call_receipt(model, before, response, expected_prompt)
    if type(response) is not dict or set(response) != {
            "approved", "draft_sha256", "review_envelope_sha256", "reasons"}:
        raise ValueError("Malformed amendment text-review response")
    validate_review(response, draft)
    if response["review_envelope_sha256"] != envelope_sha:
        raise ValueError("Review is not bound to this exact envelope")

    return {
        "schema": "normal-amendment-text-review-result-v1",
        "scope": TEXT_SCOPE,
        "fixture": fixture,
        "review_envelope_sha256": envelope_sha,
        "draft_sha256": draft_sha,
        "text_approval": response["approved"],
        "review": _clone(response),
        "execution": {
            "kind": "fixture" if fixture else "hermes",
            "same_call_receipt": receipt,
            "cryptographic_or_semantic_authentication": False,
        },
        "capture_reconstruction": NOT_RECONSTRUCTED,
        "exact_final_image_execution": NOT_RECONSTRUCTED,
        "normal_approval": False,
        "activation": False,
        "release_authorization": False,
    }
