#!/usr/bin/env python3
"""Privacy-safe per-provider stock-image execution receipts."""

from __future__ import annotations

from typing import Any, Iterable

IMAGE_PROVIDER_RESULTS_FIELD = "image_provider_results"
IMAGE_PROVIDER_RESULT_SCHEMA = "uutistenlukija.image_provider_result.v1"
MAX_PROVIDER_COUNT = 10_000


def _bounded_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(count, MAX_PROVIDER_COUNT))


def build_provider_result(
    *,
    provider: str,
    attempted: bool,
    succeeded: bool,
    outcome: str,
    reason: str,
    query_count: int = 0,
    candidate_count: int = 0,
    fresh_candidate_count: int = 0,
    rejected_count: int = 0,
    accepted_count: int = 0,
    fault_count: int = 0,
    semantic_accepted: bool = False,
    attribution_complete: bool = False,
    delivery_mode: str = "none",
    delivery_attempted: bool = False,
    delivery_succeeded: bool = False,
    thumbnail_delivery_succeeded: bool = False,
    tracking_attempted: bool = False,
    tracking_succeeded: bool = False,
) -> dict[str, Any]:
    """Build one bounded receipt without queries, URLs, or provider payloads."""
    return {
        "schema": IMAGE_PROVIDER_RESULT_SCHEMA,
        "provider": str(provider or "unknown").strip().lower(),
        "attempted": bool(attempted),
        "succeeded": bool(succeeded),
        "outcome": str(outcome or "unknown").strip().lower(),
        "reason": str(reason or outcome or "unknown").strip().lower(),
        "query_count": _bounded_count(query_count),
        "candidate_count": _bounded_count(candidate_count),
        "fresh_candidate_count": _bounded_count(fresh_candidate_count),
        "rejected_count": _bounded_count(rejected_count),
        "accepted_count": _bounded_count(accepted_count),
        "fault_count": _bounded_count(fault_count),
        "semantic_accepted": bool(semantic_accepted),
        "attribution_complete": bool(attribution_complete),
        "delivery_mode": str(delivery_mode or "none").strip().lower(),
        "delivery_attempted": bool(delivery_attempted),
        "delivery_succeeded": bool(delivery_succeeded),
        "thumbnail_delivery_succeeded": bool(thumbnail_delivery_succeeded),
        "tracking_attempted": bool(tracking_attempted),
        "tracking_succeeded": bool(tracking_succeeded),
    }


class ProviderSearchPhotos(list[dict[str, Any]]):
    """List-compatible search result carrying a non-sensitive request receipt."""

    def __init__(self, photos: Iterable[dict[str, Any]], result: dict[str, Any]):
        super().__init__(photos)
        self.provider_result = dict(result)


def search_photos(
    photos: Iterable[dict[str, Any]],
    *,
    provider: str,
    attempted: bool,
    succeeded: bool,
    outcome: str,
    reason: str,
    fault_count: int = 0,
) -> ProviderSearchPhotos:
    rows = list(photos)
    return ProviderSearchPhotos(
        rows,
        build_provider_result(
            provider=provider,
            attempted=attempted,
            succeeded=succeeded,
            outcome=outcome,
            reason=reason,
            query_count=1,
            candidate_count=len(rows),
            fault_count=fault_count,
        ),
    )


def search_result(photos: list[dict[str, Any]], provider: str) -> dict[str, Any]:
    """Read a search receipt; fail closed if an adapter omitted the contract."""
    result = getattr(photos, "provider_result", None)
    if isinstance(result, dict):
        return dict(result)
    return build_provider_result(
        provider=provider,
        attempted=False,
        succeeded=False,
        outcome="provider_fault",
        reason="missing_search_receipt",
        query_count=1,
        candidate_count=len(photos),
        fault_count=1,
    )


def combine_provider_results(
    *,
    provider: str,
    searches: Iterable[dict[str, Any]],
    candidate_count: int,
    fresh_candidate_count: int,
    rejected_count: int,
    accepted_count: int,
    reason: str = "",
    semantic_accepted: bool = False,
    attribution_complete: bool = False,
    delivery_mode: str = "none",
    delivery_attempted: bool = False,
    delivery_succeeded: bool = False,
    thumbnail_delivery_succeeded: bool = False,
    tracking_attempted: bool = False,
    tracking_succeeded: bool = False,
) -> dict[str, Any]:
    """Combine all searches for one article into one deterministic receipt."""
    provider_name = str(provider or "unknown").strip().lower()
    rows = [dict(row) for row in searches if isinstance(row, dict)]
    attempted = any(bool(row.get("attempted")) for row in rows)
    succeeded = any(bool(row.get("succeeded")) for row in rows)
    fault_count = sum(_bounded_count(row.get("fault_count")) for row in rows)

    compliance_fault = False
    if semantic_accepted and not attribution_complete:
        outcome = "attribution_incomplete"
        final_reason = reason or "provider_attribution_incomplete"
        compliance_fault = True
    elif semantic_accepted and (
        not delivery_attempted
        or not delivery_succeeded
        or not thumbnail_delivery_succeeded
    ):
        outcome = "delivery_failed"
        final_reason = reason or "hero_or_thumbnail_delivery_unavailable"
        compliance_fault = True
    elif semantic_accepted and provider_name == "unsplash" and (
        not tracking_attempted or not tracking_succeeded
    ):
        outcome = "tracking_failed"
        final_reason = reason or "download_tracking_failed"
        compliance_fault = True
    elif accepted_count and semantic_accepted:
        outcome = "accepted"
        final_reason = reason or "candidate_accepted"
    elif accepted_count:
        outcome = "provider_fault"
        final_reason = reason or "invalid_acceptance_receipt"
        compliance_fault = True
    elif fault_count and not succeeded:
        outcome = "provider_fault"
        final_reason = reason or "provider_request_failed"
    elif fresh_candidate_count and rejected_count >= fresh_candidate_count:
        outcome = "all_policy_rejected"
        final_reason = reason or "all_fresh_candidates_rejected"
    elif candidate_count and not fresh_candidate_count:
        outcome = "no_fresh_candidates"
        final_reason = reason or "all_candidates_previously_used"
    elif fault_count:
        outcome = "partial_fault"
        final_reason = reason or "search_partially_failed"
    else:
        outcome = "empty_search"
        final_reason = reason or "no_candidates_returned"

    if compliance_fault:
        fault_count += 1

    return build_provider_result(
        provider=provider_name,
        attempted=attempted,
        succeeded=succeeded,
        outcome=outcome,
        reason=final_reason,
        query_count=len(rows),
        candidate_count=candidate_count,
        fresh_candidate_count=fresh_candidate_count,
        rejected_count=rejected_count,
        accepted_count=accepted_count if outcome == "accepted" else 0,
        fault_count=fault_count,
        semantic_accepted=semantic_accepted,
        attribution_complete=attribution_complete,
        delivery_mode=delivery_mode,
        delivery_attempted=delivery_attempted,
        delivery_succeeded=delivery_succeeded,
        thumbnail_delivery_succeeded=thumbnail_delivery_succeeded,
        tracking_attempted=tracking_attempted,
        tracking_succeeded=tracking_succeeded,
    )


def _accepted_receipt_complete(result: dict[str, Any]) -> bool:
    provider = str(result.get("provider") or "").strip().lower()
    delivery_mode = str(result.get("delivery_mode") or "none").strip().lower()
    if provider == "unsplash":
        provider_compliance = (
            delivery_mode == "hotlink"
            and bool(result.get("tracking_attempted"))
            and bool(result.get("tracking_succeeded"))
        )
    elif provider == "pexels":
        provider_compliance = delivery_mode in {"download", "hotlink"}
    else:
        provider_compliance = False
    return bool(
        result.get("schema") == IMAGE_PROVIDER_RESULT_SCHEMA
        and result.get("succeeded")
        and _bounded_count(result.get("accepted_count")) > 0
        and result.get("semantic_accepted")
        and result.get("attribution_complete")
        and result.get("delivery_attempted")
        and result.get("delivery_succeeded")
        and result.get("thumbnail_delivery_succeeded")
        and provider_compliance
    )


def normalize_provider_result(
    result: dict[str, Any],
    *,
    provider: str = "",
) -> dict[str, Any]:
    """Return a bounded typed receipt and invalidate impossible acceptance."""
    provider_name = str(provider or result.get("provider") or "unknown").strip().lower()
    schema_valid = result.get("schema") == IMAGE_PROVIDER_RESULT_SCHEMA
    outcome = str(result.get("outcome") or "unknown").strip().lower()
    reason = str(result.get("reason") or outcome or "unknown").strip().lower()
    fault_count = _bounded_count(result.get("fault_count"))
    accepted_count = _bounded_count(result.get("accepted_count"))

    candidate = dict(result)
    candidate["provider"] = provider_name
    if not schema_valid:
        outcome = "provider_fault"
        reason = "invalid_provider_receipt"
        fault_count += 1
        accepted_count = 0
    elif outcome == "accepted" and not _accepted_receipt_complete(candidate):
        outcome = "provider_fault"
        reason = "invalid_acceptance_receipt"
        fault_count += 1
        accepted_count = 0
    elif outcome != "accepted":
        accepted_count = 0

    return build_provider_result(
        provider=provider_name,
        attempted=bool(result.get("attempted")),
        succeeded=bool(result.get("succeeded")),
        outcome=outcome,
        reason=reason,
        query_count=_bounded_count(result.get("query_count")),
        candidate_count=_bounded_count(result.get("candidate_count")),
        fresh_candidate_count=_bounded_count(result.get("fresh_candidate_count")),
        rejected_count=_bounded_count(result.get("rejected_count")),
        accepted_count=accepted_count,
        fault_count=fault_count,
        semantic_accepted=bool(result.get("semantic_accepted")),
        attribution_complete=bool(result.get("attribution_complete")),
        delivery_mode=str(result.get("delivery_mode") or "none"),
        delivery_attempted=bool(result.get("delivery_attempted")),
        delivery_succeeded=bool(result.get("delivery_succeeded")),
        thumbnail_delivery_succeeded=bool(result.get("thumbnail_delivery_succeeded")),
        tracking_attempted=bool(result.get("tracking_attempted")),
        tracking_succeeded=bool(result.get("tracking_succeeded")),
    )


def set_provider_result(article: dict[str, Any], result: dict[str, Any]) -> None:
    """Keep exactly the latest typed receipt for each provider on an article."""
    normalized = normalize_provider_result(result)
    provider = str(normalized.get("provider") or "unknown").strip().lower()
    rows = article.get(IMAGE_PROVIDER_RESULTS_FIELD)
    if not isinstance(rows, list):
        rows = []
    retained = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("provider") or "unknown").strip().lower() != provider
    ]
    retained.append(normalized)
    article[IMAGE_PROVIDER_RESULTS_FIELD] = retained


def get_provider_result(article: dict[str, Any], provider: str) -> dict[str, Any] | None:
    provider = str(provider or "").strip().lower()
    rows = article.get(IMAGE_PROVIDER_RESULTS_FIELD)
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if isinstance(row, dict) and str(row.get("provider") or "").strip().lower() == provider:
            return normalize_provider_result(row, provider=provider)
    return None
