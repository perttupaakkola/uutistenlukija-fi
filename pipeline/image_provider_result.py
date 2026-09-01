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
) -> dict[str, Any]:
    """Combine all searches for one article into one deterministic receipt."""
    rows = [dict(row) for row in searches if isinstance(row, dict)]
    attempted = any(bool(row.get("attempted")) for row in rows)
    succeeded = any(bool(row.get("succeeded")) for row in rows)
    fault_count = sum(_bounded_count(row.get("fault_count")) for row in rows)

    if accepted_count:
        outcome = "accepted"
        final_reason = reason or "candidate_accepted"
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

    return build_provider_result(
        provider=provider,
        attempted=attempted,
        succeeded=succeeded,
        outcome=outcome,
        reason=final_reason,
        query_count=len(rows),
        candidate_count=candidate_count,
        fresh_candidate_count=fresh_candidate_count,
        rejected_count=rejected_count,
        accepted_count=accepted_count,
        fault_count=fault_count,
    )


def set_provider_result(article: dict[str, Any], result: dict[str, Any]) -> None:
    """Keep exactly the latest typed receipt for each provider on an article."""
    provider = str(result.get("provider") or "unknown").strip().lower()
    rows = article.get(IMAGE_PROVIDER_RESULTS_FIELD)
    if not isinstance(rows, list):
        rows = []
    retained = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("provider") or "unknown").strip().lower() != provider
    ]
    retained.append(dict(result))
    article[IMAGE_PROVIDER_RESULTS_FIELD] = retained


def get_provider_result(article: dict[str, Any], provider: str) -> dict[str, Any] | None:
    provider = str(provider or "").strip().lower()
    rows = article.get(IMAGE_PROVIDER_RESULTS_FIELD)
    if not isinstance(rows, list):
        return None
    for row in reversed(rows):
        if isinstance(row, dict) and str(row.get("provider") or "").strip().lower() == provider:
            return dict(row)
    return None
