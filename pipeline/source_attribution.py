#!/usr/bin/env python3
"""Shared selected-source usage and public-attribution projection."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_QUERY_KEYS = frozenset(
    {
        "at_campaign",
        "at_medium",
        "fbclid",
        "gclid",
        "origin",
        "output",
        "ref",
        "ref_src",
    }
)
_WS_RE = re.compile(r"\s+")


def _normalize_ws(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def normalize_source_url(value: Any) -> str:
    """Normalize one public URL without discarding article-identifying query data."""
    raw = str(value or "").strip().rstrip(".,;:!?")
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    scheme = parts.scheme.casefold()
    if scheme not in {"http", "https"} or not parts.hostname:
        return ""
    hostname = parts.hostname.casefold().removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        return ""
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, hostname, path, parts.query, ""))


def source_identity_key(value: Any) -> str:
    """Return a stable same-article identity used for alias-safe accounting."""
    normalized = normalize_source_url(value)
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    hostname = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        return ""
    if hostname in {"bbc.co.uk", "bbc.com"}:
        hostname = "bbc.com"
    if port and not (
        (parts.scheme == "http" and port == 80)
        or (parts.scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_QUERY_KEYS
            and not key.casefold().startswith("utm_")
        )
    )
    return urlunsplit(("https", hostname, parts.path or "/", query, ""))


def selected_source_urls(packet: dict[str, Any]) -> tuple[str, ...]:
    """Return every distinct exact URL selected into the writer packet."""
    urls: list[str] = []
    seen: set[str] = set()
    blocks = packet.get("clean_source_blocks")
    if not isinstance(blocks, list):
        return ()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        url = normalize_source_url(block.get("source_url"))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return tuple(urls)


def normalize_source_usage(
    packet: dict[str, Any],
    rows: Any,
    *,
    require_complete: bool,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Validate and normalize per-URL claim usage without mutating the packet."""
    selected_urls = selected_source_urls(packet)
    selected_set = set(selected_urls)
    if not isinstance(rows, list):
        if require_complete or rows is not None:
            return [], ("source_usage must be a list",)
        return [], ()

    normalized_rows: list[dict[str, Any]] = []
    issues: list[str] = []
    seen_urls: set[str] = set()
    for index, row in enumerate(rows):
        label = f"source_usage[{index}]"
        if not isinstance(row, dict):
            issues.append(f"{label} must be an object")
            continue
        url = normalize_source_url(row.get("source_url"))
        if not url:
            issues.append(f"{label}.source_url is invalid")
            continue
        if url in seen_urls:
            issues.append(f"{label}.source_url is duplicated")
            continue
        seen_urls.add(url)
        if url not in selected_set:
            issues.append(f"{label}.source_url was not selected")

        used = row.get("used")
        if not isinstance(used, bool):
            issues.append(f"{label}.used must be boolean")
            continue
        claims = row.get("dependent_claims")
        if not isinstance(claims, list) or any(
            not isinstance(claim, str) or not _normalize_ws(claim)
            for claim in claims
        ):
            issues.append(f"{label}.dependent_claims must be a list of non-empty strings")
            continue
        normalized_claims = [_normalize_ws(claim) for claim in claims]
        if used is False and normalized_claims:
            issues.append(f"{label} used:false requires dependent_claims=[]")
        if used is True and not normalized_claims:
            issues.append(f"{label} used:true requires at least one dependent claim")
        normalized_rows.append(
            {
                "source_url": url,
                "used": used,
                "dependent_claims": normalized_claims,
            }
        )

    if require_complete:
        missing = [url for url in selected_urls if url not in seen_urls]
        if missing:
            issues.append("source_usage is missing selected URLs: " + ", ".join(missing))

    used_by_identity: dict[str, list[str]] = {}
    for row in normalized_rows:
        if row["used"] is not True:
            continue
        identity = source_identity_key(row["source_url"])
        used_by_identity.setdefault(identity, []).append(row["source_url"])
    for urls in used_by_identity.values():
        if len(urls) > 1:
            issues.append(
                "same-article aliases must collapse to one used URL: "
                + ", ".join(urls)
            )

    return normalized_rows, tuple(dict.fromkeys(issues))


def build_source_attributions(
    packet: dict[str, Any], rows: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Project used source rows into the single public attribution field."""
    names_by_url: dict[str, str] = {}
    blocks = packet.get("clean_source_blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            url = normalize_source_url(block.get("source_url"))
            name = _normalize_ws(block.get("source"))
            if url and name:
                names_by_url.setdefault(url, name)

    projected: list[dict[str, str]] = []
    seen_identities: set[str] = set()
    for row in rows:
        if row.get("used") is not True:
            continue
        url = normalize_source_url(row.get("source_url"))
        identity = source_identity_key(url)
        if not url or not identity or identity in seen_identities:
            continue
        seen_identities.add(identity)
        name = names_by_url.get(url) or (urlsplit(url).hostname or url)
        projected.append({"name": name, "url": url})
    return projected


def project_public_source_attributions(
    article: dict[str, Any],
) -> tuple[dict[str, str], ...]:
    """Return the exact structured source rows the publisher can render."""
    rows = article.get("source_attributions")
    if not isinstance(rows, list):
        return ()
    projected: list[dict[str, str]] = []
    seen_identities: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _normalize_ws(row.get("name"))
        url = normalize_source_url(row.get("url"))
        identity = source_identity_key(url)
        if not name or not url or not identity or identity in seen_identities:
            continue
        seen_identities.add(identity)
        projected.append({"name": name, "url": url})
    return tuple(projected)
