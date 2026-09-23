"""Offline URL normalization and path classification for the uutistenlukija.fi join.

Contract
--------
``normalize_url(value, host=None) -> str | None``
    Returns a canonical same-site path: query and fragment removed, path case
    and trailing slash preserved (no redirect guessing).  Accepts absolute
    HTTPS URLs on ``uutistenlukija.fi`` or absolute ``/paths``.  Host context
    is trusted only when the ``host`` argument is ``None`` (absent) or names
    exactly ``uutistenlukija.fi``; any other supplied host excludes the value.
    An absolute site origin without a path normalizes to ``/``; empty/unknown
    values never do.  Returns ``None`` for foreign, mismatched, malformed or
    ambiguous values, and normalization is idempotent for accepted values.

``classify_path(value, host=None) -> "reboot" | "legacy" | "excluded"``
    ``/`` and the slash-prefixed reboot paths ``/uutiset/...`` and
    ``/sivu/...`` are ``reboot``.  The bare prefixes ``/uutiset`` and
    ``/sivu`` are *not* reboot: they classify ``legacy``, as do boundary
    lookalikes such as ``/uutisetfake/``.  Every other same-site path is
    ``legacy``; unnormalizable values are ``excluded``.

``join_rows(articles, gsc_rows, ga4_rows, *, gsc_status, ga4_status, truncated)``
    Pure offline join of deployed articles to GSC page rows and GA4 landing-page
    rows, returning a JSON-serializable report.  See the join contract below.

``collect(state_dir=..., now=..., timeout=...)``
    Read-only catalog/provider adapter returning the same join report enriched
    with windows, live-canonical evidence and safe provider summaries.  It does
    not create or write state.

Normalization and joining are pure and offline; only ``collect`` performs the
explicitly bounded read-only public/provider reads described above.
"""

import argparse
import datetime as dt
import json
import math
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlsplit

try:
    # Keep the existing helper as the only credential/query implementation.  The
    # installed helper directory is deliberately not a project dependency.
    _ANALYTICS_HELPER_DIR = "/home/pertt/.local/share/lean-support/bin"
    if _ANALYTICS_HELPER_DIR not in sys.path:
        sys.path.insert(0, _ANALYTICS_HELPER_DIR)
    from news_analytics import query, requests_for, service_account_access_token
except (ImportError, ModuleNotFoundError):  # pragma: no cover - exercised only off-host
    def requests_for(now):
        raise RuntimeError("analytics helper unavailable")

    def query(url, payload, token):
        raise RuntimeError("analytics helper unavailable")

    def service_account_access_token(scopes):
        raise RuntimeError("analytics helper unavailable")

SITE_HOST = "uutistenlukija.fi"
SITE_ORIGIN = "https://" + SITE_HOST
UNSAFE_DECODED = ("?", "#", "%")
# Slash-prefixed only: the bare "/uutiset" and "/sivu" classify legacy.
REBOOT_PREFIXES = ("/uutiset", "/sivu")
UNKNOWN = frozenset(
    {"", "(not set)", "(none)", "(not provided)", "(unknown)", "unknown", "null", "none", "-"}
)


def _safe_path(path):
    """Validate percent escapes/traversal and return the decoded path, or None."""
    i = 0
    while i < len(path):
        if path[i] == "%":
            if i + 2 >= len(path) or any(c not in "0123456789abcdefABCDEF" for c in path[i + 1 : i + 3]):
                return None
            i += 3
        else:
            i += 1
    try:
        decoded = unquote_to_bytes(path).decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in decoded):
        return None
    if decoded.count("/") != path.count("/") or "\\" in decoded:
        return None  # percent-encoded slash or backslash
    if any(c in decoded for c in UNSAFE_DECODED):
        return None  # decoded delimiters/escapes would break idempotent joins
    for segment in decoded.split("/"):
        if segment in (".", ".."):
            return None  # raw or percent-encoded dot traversal
    return decoded


def normalize_url(value, host=None):
    """Canonical same-site path for ``value``, or None (see module contract)."""
    if not isinstance(value, str) or value.lower() in UNKNOWN:
        return None
    if value.startswith("//") or "\\" in value:
        return None
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        return None
    if host is not None:
        if not isinstance(host, str) or host.lower() != SITE_HOST:
            return None  # only an exact site host is trusted caller context
    try:
        parts = urlsplit(value)
    except ValueError:
        return None  # malformed URL
    if parts.scheme:
        if parts.scheme.lower() != "https":
            return None
        if parts.username is not None or parts.password is not None:
            return None  # empty userinfo is still userinfo
        try:
            hostname, port = parts.hostname, parts.port
        except ValueError:
            return None
        if hostname is None or hostname.lower() != SITE_HOST:
            return None
        if ":" in parts.netloc or port is not None:
            return None  # any explicit port syntax, even empty or default
        path = parts.path or "/"  # unambiguous bare site origin
    elif parts.path.startswith("/") and not parts.netloc:
        path = parts.path  # absolute /path; empty path is never implicit "/"
    else:
        return None
    if not path:
        return None
    clean = _safe_path(path)
    return clean if clean and clean.startswith("/") else None


def classify_path(value, host=None):
    """``"reboot"``, ``"legacy"`` or ``"excluded"`` for ``value`` (see contract)."""
    path = normalize_url(value, host)
    if path is None:
        return "excluded"
    if path == "/":
        return "reboot"
    for prefix in REBOOT_PREFIXES:
        if path.startswith(prefix + "/"):
            return "reboot"
    return "legacy"


# --- Offline performance join -------------------------------------------------
#
# ``join_rows`` performs no fetching and reads no state: adapters hand it plain
# provider rows and it returns a JSON-serializable report.  Every number stays
# traceable to a raw provider row and every ambiguity stays visible instead of
# being folded into a plausible-looking total.
#
# Input contract
# --------------
# ``articles`` rows carry ``id``, ``canonical_url`` (the exact deployed
# canonical, i.e. exactly ``https://uutistenlukija.fi`` plus the normalized
# ``/uutiset/...`` path with a nonempty suffix), ``deployed: True``, ``aliases``
# (explicitly evidenced URLs only; matched internally by normalized path)
# and ``metadata`` with ``description``/``og``/``jsonld`` presence as
# ``bool | None`` (``None`` stays unknown, never ``False``).  Malformed input,
# not-deployed or foreign canonicals, non-article paths, duplicate ids and
# ambiguous canonical or alias ownership raise ``ValueError``: the join fails
# closed instead of guessing.  Aliases join by exact normalized identity; no
# prefix, trailing-slash or redirect inference ever happens.
# ``gsc_rows`` rows carry ``page`` (absolute URL) plus ``clicks``,
# ``impressions``, ``ctr`` and ``position``; ``ga4_rows`` rows carry
# ``landing_page``, ``hostname``, ``views``, ``active_users`` and ``sessions``.
# Raw network adapters map provider payloads onto these shapes later.
#
# Status and unknowns
# -------------------
# Malformed provider metrics never become ``0``: the row keeps an error status
# with an explicit reason, and ``measurement_status`` becomes ``error`` so
# callers abstain.  Only a validation failure (malformed metrics, a
# contradictory duplicate, or a provider status of ``error``) is an error.
# Ordinary excluded or unattributed provider identities are a coverage
# limitation, not a provider failure: a complete pull that contains them stays
# ``ok`` while cohorts and ``coverage`` state exactly what was left out.
# ``unmatched`` keeps every provider row that was not aggregated, with the
# reason it was left out.  An empty successful provider response stays ``ok``:
# the per-article provider block is then ``missing``, which is unknown, not
# zero.  ``truncated`` is echoed and forbids ``ok``.  Every total that has no
# valid measurement behind it is ``null``, never ``0``, and a report is
# serializable with ``json.dumps(..., allow_nan=False)``: non-finite provider
# values are carried as an explicit invalid reason, never as a number.
#
# Aggregation semantics
# ---------------------
# The join key is the normalized path (query and fragment stripped), so query
# variants aggregate while exact duplicate source rows cannot double-count.
# Repeated source rows that disagree on metrics are contradictory and make the
# report ``incomplete``: neither copy is counted.  GSC ``clicks`` and
# ``impressions`` are additive and ``position`` is impression-weighted; ``ctr``
# is recomputed from the actual sums.  GA4 ``views`` are grouped by session
# landing page, not direct article pageviews, so ``sessions`` is additive while
# ``active_users`` is retained only for a single source row and withheld with a
# nonadditive note otherwise.  Individual counters and impression-weighted
# products grow without any float conversion, but a total that leaves the
# finite float range is reported as an unavailable (``null``) total with an
# explicit error instead of ``inf``/``nan``.
#
# Cohorts
# -------
# ``reboot``/``legacy``/``excluded``/``unattributed`` carry source row counts,
# additive totals over known values only, and explicit unknown counts.  ``/``
# and the slash-prefixed reboot paths are ``reboot``; same-domain root and
# archive rows may sit in that cohort but are never deployed articles, and no
# attribution ever happens by ``/uutiset`` prefix alone.  Unknown or empty GA4
# hostnames are excluded: an explicit ``None`` hostname never implies the
# trusted site host.  A known site hostname with an empty or ``(not set)``
# landing page is ``unattributed``, with its reason preserved, while a foreign
# or missing hostname is ``excluded``.  A cohort with no valid measurement
# keeps ``null`` totals and an explicit note instead of a plausible ``0``; an
# empty cohort of a successful provider may report zero with zero rows.

GSC_OK, GSC_MISSING, GSC_ERROR = "ok", "missing", "error"
GA4_OK, GA4_MISSING = "ok", "missing"
KNOWN_PROVIDER_STATUSES = (GSC_OK, GSC_MISSING, GSC_ERROR)
COHORT_LABELS = ("reboot", "legacy", "excluded", "unattributed")
LIMITATIONS = [
    "GSC clicks are not GA4 views; the providers measure different things over adapter-supplied windows.",
    "Same-domain GSC and GA4 rows include history from the old site, not only deployed reboot articles.",
    "GA4 views are grouped by session landing page, not direct pageviews of that URL.",
    "GA4 active_users is not additive across landing rows and is never summed.",
    "Provider rows are not exhaustive: privacy-suppressed or unlisted traffic is absent and stays unknown, not zero.",
    "Foreign, missing and unattributed identities are explicit coverage limitations, not trusted article traffic.",
    "Reporting windows are supplied by the adapter later and are not part of this pure join.",
]


def _clean_number(value):
    """Drop the float artifact for whole numbers so the report stays readable."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        # Do not turn a finite 1e308 into a several-hundred-digit JSON integer:
        # retaining the finite float keeps the report serializable and readable.
        integer = int(value)
        if len(str(abs(integer))) <= 1000:
            return integer
    return value


def _is_finite_number(value):
    """Finite real number, bool excluded; ``None``/huge ints are not finite."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False  # int too large for the float range


def _is_counter(value):
    """Finite nonnegative number, bool excluded; ``None`` means unknown."""
    return _is_finite_number(value) and value >= 0


def _is_position(value):
    """A real search position is finite and at least 1."""
    return _is_finite_number(value) and value >= 1


def _json_safe(value):
    """True when ``json.dumps(value, allow_nan=False)`` accepts the value."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def _safe_raw(value):
    """JSON-safe echo of a raw provider row.

    A raw ``nan``/``inf`` must never be serialized as a number, because that
    would either produce invalid JSON or silently read as a real metric.  Such
    values become an explicit marker instead; already-safe raw rows are
    returned unchanged so callers can still inspect the exact source object.
    """
    if _json_safe(value):
        return value
    if isinstance(value, float):
        return {"invalid": "non-finite float", "raw": repr(value)}
    if isinstance(value, dict):
        return {str(key): _safe_raw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_raw(item) for item in value]
    return repr(value)


def _finite_add(total, value):
    """Finite exact sum, or None when the total leaves the finite float range."""
    try:
        result = total + value
    except OverflowError:
        return None
    return result if _is_finite_number(result) else None


def _finite_product(left, right):
    """Finite product, or None when it leaves the finite float range."""
    try:
        result = left * right
    except OverflowError:
        return None
    return result if _is_finite_number(result) else None


def _finite_sum(values):
    """Finite exact sum, or None when any partial total leaves the range."""
    total = 0
    for value in values:
        total = _finite_add(total, value)
        if total is None:
            return None
    return total


def _hashable_identity(value):
    """Hashable, collision-safe stand-in for a raw provider identity value."""
    if value is None:
        return ("none",)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int) and not isinstance(value, bool):
        return ("int", str(value))
    if isinstance(value, float):
        return ("float", repr(value))
    if isinstance(value, str):
        return ("str", value)
    if _json_safe(value):
        try:
            return ("json", json.dumps(value, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError):
            pass
    try:
        return ("repr", type(value).__name__, repr(value))
    except Exception:
        return ("repr", type(value).__name__, id(value))


def _same_raw(left, right):
    """Compare malformed provider rows without allowing a hostile identity to raise."""
    try:
        result = left == right
        if isinstance(result, bool):
            return result
    except Exception:
        pass
    return _hashable_identity(left) == _hashable_identity(right)


def _prepare_article(article, index):
    where = f"articles[{index}]"
    if not isinstance(article, dict):
        raise ValueError(f"{where}: article must be a JSON object")
    if article.get("deployed") is not True:
        raise ValueError(f"{where}: deployed must be exactly True; only deployed canonicals are joined")
    identifier = article.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError(f"{where}: id must be a non-empty string")
    raw_canonical = article.get("canonical_url")
    canonical = normalize_url(raw_canonical)
    if canonical is None:
        raise ValueError(f"{where}: canonical_url {raw_canonical!r} is not a same-site URL or /path")
    if raw_canonical != SITE_ORIGIN + canonical:
        raise ValueError(
            f"{where}: canonical_url must be the exact normalized absolute canonical "
            f"{SITE_ORIGIN + canonical!r}, got {raw_canonical!r}"
        )
    if not canonical.startswith("/uutiset/") or len(canonical) == len("/uutiset/"):
        raise ValueError(
            f"{where}: canonical_url must be a deployed /uutiset/... article path with a "
            f"nonempty suffix, got {canonical!r}"
        )
    aliases = article.get("aliases", [])
    if aliases is None:
        aliases = []
    if not isinstance(aliases, (list, tuple)):
        raise ValueError(f"{where}: aliases must be a list")
    normalized_aliases = []
    for alias in aliases:
        path = normalize_url(alias)
        if path is None:
            raise ValueError(f"{where}: alias {alias!r} is not a same-site URL or /path")
        if path == canonical:
            continue  # redundant self-alias: unambiguous and carries no new identity
        if path in normalized_aliases:
            raise ValueError(f"{where}: duplicate alias after normalization: {path!r}")
        normalized_aliases.append(path)
    metadata = article.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError(f"{where}: metadata must be a JSON object")
    clean_metadata = {}
    for field in ("description", "og", "jsonld"):
        value = metadata.get(field)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{where}: metadata.{field} must be true, false or null (unknown)")
        clean_metadata[field] = value
    return {
        "id": identifier,
        "canonical": canonical,
        "canonical_url": SITE_ORIGIN + canonical,
        "aliases": normalized_aliases,
        "metadata": clean_metadata,
    }


def _prepare_articles(articles):
    """Validate article input fail-closed, returning records and a URL owner map."""
    if not isinstance(articles, (list, tuple)):
        raise ValueError("articles must be a list")
    records, seen_ids, owners = [], set(), {}
    for index, article in enumerate(articles):
        record = _prepare_article(article, index)
        if record["id"] in seen_ids:
            raise ValueError(f"articles[{index}]: duplicate article id {record['id']!r}")
        seen_ids.add(record["id"])
        for path in [record["canonical"]] + record["aliases"]:
            if path in owners:
                raise ValueError(
                    f"ambiguous URL ownership for {path!r}: both {owners[path]!r} and {record['id']!r}"
                )
            owners[path] = record["id"]
        records.append(record)
    return records, owners


def _new_row(provider, index, raw):
    return {
        "provider": provider, "index": index, "raw": raw, "path": None, "owner_id": None,
        "cohort": "excluded", "status": GSC_OK, "reason": None, "note": None,
    }


def _gsc_problem(clicks, impressions, ctr, position):
    if not _is_counter(clicks):
        return "clicks is missing or not a finite nonnegative number"
    if not _is_counter(impressions):
        return "impressions is missing or not a finite nonnegative number"
    if clicks > impressions:
        return f"clicks {clicks!r} exceed impressions {impressions!r}"
    if not _is_counter(ctr):
        return "ctr is missing or not a finite nonnegative number"
    if ctr > 1:
        return f"ctr {ctr!r} exceeds 1"
    if impressions > 0 and not _is_position(position):
        return "position must be a finite number >= 1 when impressions > 0"
    return None


def _gsc_row(raw, index, issues):
    """Validate one GSC row; invalid metrics keep the row with an explicit reason."""
    row = _new_row("gsc", index, raw)
    row.update({"clicks": None, "impressions": None, "ctr": None, "position": None, "position_known": False})
    if not isinstance(raw, dict):
        row["status"] = GSC_ERROR
        row["reason"] = "row is not a JSON object"
        issues.append(f"gsc_rows[{index}]: row is not a JSON object")
        return row
    clicks, impressions = raw.get("clicks"), raw.get("impressions")
    ctr, position = raw.get("ctr"), raw.get("position")
    problem = _gsc_problem(clicks, impressions, ctr, position)
    row["path"] = normalize_url(raw.get("page"))
    if row["path"] is not None:
        row["cohort"] = _classify_cohort(row, "gsc")
    if problem:
        row["status"] = GSC_ERROR
        row["reason"] = f"invalid metrics: {problem}"
        issues.append(f"gsc_rows[{index}]: {problem}")
        return row
    row["clicks"], row["impressions"], row["ctr"] = _clean_number(clicks), _clean_number(impressions), ctr
    if position is None:
        row["note"] = "position unknown at zero exposure; unknown is not rank 1"
    elif _is_position(position):
        row["position"], row["position_known"] = _clean_number(position), True
    else:
        row["note"] = f"position {position!r} ignored at zero exposure; treated as unknown"
    if row["path"] is None:
        row["reason"] = "page is not a same-site URL or /path; excluded from attribution"
        issues.append(f"gsc_rows[{index}]: {row['reason']}")
    return row


def _ga4_identity(hostname, landing):
    """``(path, cohort, reason)`` for a GA4 landing row; a ``None`` path has no identity."""
    if not isinstance(hostname, str) or not hostname.strip():
        return None, "excluded", "hostname is unknown or empty; excluded from attribution"
    if hostname.lower() != SITE_HOST:
        return None, "excluded", f"hostname {hostname!r} is not the site host; excluded from attribution"
    path = normalize_url(landing, hostname)
    if path is not None:
        return path, "excluded", None  # cohort assigned from the path by _cohorts
    if isinstance(landing, str) and ("://" in landing or landing.startswith("//")):
        return None, "excluded", f"landing_page {landing!r} is a foreign or malformed URL; excluded"
    return None, "unattributed", f"landing_page {landing!r} carries no same-site path identity; unattributed"


def _ga4_problem(raw):
    for field in ("views", "active_users", "sessions"):
        if not _is_counter(raw.get(field)):
            return f"{field} is missing or not a finite nonnegative number"
    return None


def _ga4_row(raw, index, issues):
    """Validate one GA4 landing row; unknown hostnames are excluded, never trusted."""
    row = _new_row("ga4", index, raw)
    row.update({"landing_page": None, "hostname": None, "views": None, "active_users": None, "sessions": None})
    if not isinstance(raw, dict):
        row["status"] = GSC_ERROR  # shared provider-row error status
        row["reason"] = "row is not a JSON object"
        issues.append(f"ga4_rows[{index}]: row is not a JSON object")
        return row
    row["hostname"], row["landing_page"] = raw.get("hostname"), raw.get("landing_page")
    row["path"], row["cohort"], row["reason"] = _ga4_identity(raw.get("hostname"), raw.get("landing_page"))
    if row["path"] is not None:
        row["cohort"] = _classify_cohort(row, "ga4")
    problem = _ga4_problem(raw)
    if problem:
        row["status"] = GSC_ERROR
        row["reason"] = f"invalid metrics: {problem}"
        issues.append(f"ga4_rows[{index}]: {problem}")
        return row
    for field in ("views", "active_users", "sessions"):
        row[field] = _clean_number(raw[field])
    if row["path"] is None:
        issues.append(f"ga4_rows[{index}]: {row['reason']}")
    return row


def _raw_key(row):
    """Raw provider identity for duplicate detection; query variants stay distinct."""
    raw = row["raw"]
    if not isinstance(raw, dict):
        return ("malformed", row["provider"], row["index"])
    if row["provider"] == "gsc":
        return ("gsc", _hashable_identity(raw.get("page")))
    return ("ga4", _hashable_identity(raw.get("hostname")),
            _hashable_identity(raw.get("landing_page")))


def _dedupe_rows(rows, label, issues):
    """Collapse exact duplicate rows; contradictory duplicates are rejected wholesale."""
    kept, seen, rejected, exact_duplicates, rejected_ids = [], {}, [], 0, set()
    for row in rows:
        key = _raw_key(row)
        previous = seen.get(key)
        if previous is None:
            seen[key] = row
            kept.append(row)
            continue
        if _same_raw(previous["raw"], row["raw"]) and id(previous) not in rejected_ids:
            exact_duplicates += 1
            continue
        reason = f"conflicting duplicate {label} for {key!r}; not counted, report incomplete"
        issues.append(f"conflicting duplicate {label} for {key!r}")
        for conflicting in (previous, row):
            conflicting["status"] = GSC_ERROR
            conflicting["reason"] = reason
            if id(conflicting) not in rejected_ids:
                rejected_ids.add(id(conflicting))
                rejected.append(conflicting)
        kept = [candidate for candidate in kept if id(candidate) not in rejected_ids]
    return kept, exact_duplicates, rejected


def _classify_cohort(row, kind):
    """Cohort from the normalized path alone; same-domain root/archive stay reboot."""
    if row["path"] is None:
        return "unattributed" if kind == "ga4" else "excluded"
    return "reboot" if classify_path(row["path"]) == "reboot" else "legacy"


def _empty_cohort(kind):
    if kind == "gsc":
        return {
            "rows": 0, "error_rows": 0, "clicks": 0, "impressions": 0, "position": None, "ctr": None,
            "unknown_rows": {"clicks": 0, "impressions": 0, "position": 0},
            "_weighted": 0, "_weighted_impressions": 0, "_measured_rows": 0,
            "_overflow": set(),
        }
    return {
        "rows": 0, "error_rows": 0, "views": 0, "sessions": 0, "active_users": None,
        "known_active_user_rows": 0,
        "unknown_rows": {"views": 0, "sessions": 0, "active_users": 0},
        "_measured_rows": 0, "_overflow": set(),
    }


def _unknown_for_row(totals, kind):
    fields = ("clicks", "impressions", "position") if kind == "gsc" else ("views", "sessions", "active_users")
    for field in fields:
        totals["unknown_rows"][field] += 1


def _accumulate_cohort(totals, row, kind, available=True):
    totals["rows"] += 1
    if not available:
        totals["error_rows"] += 1
        _unknown_for_row(totals, kind)
        return
    if row["status"] != GSC_OK:
        totals["error_rows"] += 1
        _unknown_for_row(totals, kind)
        return
    totals["_measured_rows"] += 1
    if kind == "gsc":
        for field in ("clicks", "impressions"):
            if row[field] is None:
                totals["unknown_rows"][field] += 1
            else:
                if field not in totals["_overflow"]:
                    result = _finite_add(totals[field], row[field])
                    if result is None:
                        totals["_overflow"].add(field)
                    else:
                        totals[field] = result
        if row["position_known"]:
            if "position" not in totals["_overflow"]:
                product = _finite_product(row["position"], row["impressions"])
                weighted = _finite_add(totals["_weighted"], product) if product is not None else None
                denominator = _finite_add(totals["_weighted_impressions"], row["impressions"])
                if weighted is None or denominator is None:
                    totals["_overflow"].add("position")
                else:
                    totals["_weighted"] = weighted
                    totals["_weighted_impressions"] = denominator
        else:
            totals["unknown_rows"]["position"] += 1
    else:
        for field in ("views", "sessions"):
            if row[field] is None:
                totals["unknown_rows"][field] += 1
            else:
                if field not in totals["_overflow"]:
                    result = _finite_add(totals[field], row[field])
                    if result is None:
                        totals["_overflow"].add(field)
                    else:
                        totals[field] = result
        if row["active_users"] is None:
            totals["unknown_rows"]["active_users"] += 1
        else:
            totals["known_active_user_rows"] += 1
            totals["active_users"] = row["active_users"]


def _finalize_cohort(totals, label, kind, available=True):
    measured_rows = totals.pop("_measured_rows")
    overflow = sorted(totals.pop("_overflow"))
    no_valid_rows = totals["rows"] > 0 and measured_rows == 0
    if kind == "gsc":
        weighted, impressions = totals.pop("_weighted"), totals.pop("_weighted_impressions")
        if not available or no_valid_rows:
            totals["clicks"] = totals["impressions"] = None
            totals["position"] = totals["ctr"] = None
        else:
            totals["clicks"] = None if "clicks" in overflow else _clean_number(totals["clicks"])
            totals["impressions"] = None if "impressions" in overflow else _clean_number(totals["impressions"])
            totals["position"] = (
                None if "position" in overflow or impressions <= 0
                else _clean_number(weighted / impressions)
            )
            totals["ctr"] = (
                None if totals["clicks"] is None or totals["impressions"] in (None, 0)
                else _clean_number(totals["clicks"] / totals["impressions"])
            )
        totals["measured_rows"] = measured_rows
        if overflow:
            totals["aggregation_errors"] = [f"finite aggregate overflow: {field}" for field in overflow]
        totals["note"] = "additive clicks/impressions; position impression-weighted; unknown values counted, never zero"
        if not available or no_valid_rows:
            totals["note"] = "no valid measurements; totals unknown, not zero"
        if label == "reboot":
            totals["note"] += "; root and archive rows may sit here but are not deployed articles"
    else:
        if not available or no_valid_rows:
            totals["views"] = totals["sessions"] = totals["active_users"] = None
        else:
            totals["views"] = None if "views" in overflow else _clean_number(totals["views"])
            totals["sessions"] = None if "sessions" in overflow else _clean_number(totals["sessions"])
        if not available or no_valid_rows or totals["known_active_user_rows"] != 1:
            totals["active_users"] = None
        totals.pop("known_active_user_rows")
        totals["note"] = "additive views/sessions; active_users kept only for a single row and never summed"
        if not available or no_valid_rows:
            totals["note"] = "no valid measurements; totals unknown, not zero"
        if overflow:
            totals["aggregation_errors"] = [f"finite aggregate overflow: {field}" for field in overflow]
        totals["measured_rows"] = measured_rows
    if label == "excluded":
        totals["note"] += "; untrusted identity or invalid metrics, excluded from attribution"
    elif label == "unattributed":
        totals["note"] += "; no same-site identity, so no article attribution"
    return totals


def _cohorts(rows, kind, available=True):
    cohorts = {label: _empty_cohort(kind) for label in COHORT_LABELS}
    for row in rows:
        if row["path"] is not None:
            row["cohort"] = _classify_cohort(row, kind)
        _accumulate_cohort(cohorts[row["cohort"]], row, kind, available=available)
    return {label: _finalize_cohort(totals, label, kind, available=available)
            for label, totals in cohorts.items()}


def _provider_status(requested, rows, label, issues, missing_value):
    """Adapter-level status; ``None`` rows mean the provider data is missing."""
    if requested != GSC_OK:
        return requested
    if rows is None:
        issues.append(f"{label}: provider data is None; metrics stay unknown")
        return missing_value
    if not isinstance(rows, (list, tuple)):
        issues.append(f"{label}: provider rows are not a list")
        return GSC_ERROR
    return GSC_OK


def _match(rows, owners):
    """Group usable rows by owning article; rows without an owner stay unmatched."""
    matched, unmatched = {}, []
    for row in rows:
        owner = owners.get(row["path"]) if row["path"] is not None else None
        if owner is None:
            unmatched.append(row)
            continue
        row["owner_id"] = owner
        matched.setdefault(owner, []).append(row)
        if row["status"] != GSC_OK:
            # Keep the identity attached to the article for an explicit error
            # block, while also retaining the malformed source in the audit.
            unmatched.append(row)
    return matched, unmatched


def _unknown_gsc(status, note):
    return {
        "status": status, "rows": 0, "clicks": None, "impressions": None, "position": None,
        "ctr": None, "paths": [], "unknown_rows": {"position": 0}, "note": note,
    }


def _unknown_ga4(status, note):
    return {
        "status": status, "rows": 0, "views": None, "sessions": None, "active_users": None,
        "paths": [], "note": note,
    }


def _article_gsc(rows):
    paths = sorted({row["path"] for row in rows})
    broken = [row for row in rows if row["status"] != GSC_OK]
    if broken:
        return {
            "status": GSC_ERROR, "rows": len(rows), "clicks": None, "impressions": None,
            "position": None, "ctr": None, "paths": paths,
            "reasons": sorted({row["reason"] for row in broken if row["reason"]}),
            "note": "invalid provider metrics on a joined row; totals withheld, not zero",
        }
    clicks = _finite_sum(row["clicks"] for row in rows)
    impressions = _finite_sum(row["impressions"] for row in rows)
    weighted = 0
    aggregation_errors = []
    for row in rows:
        if not row["position_known"]:
            continue
        product = _finite_product(row["position"], row["impressions"])
        weighted = _finite_add(weighted, product) if product is not None else None
        if weighted is None:
            aggregation_errors.append("finite aggregate overflow: position")
            break
    if clicks is None:
        aggregation_errors.append("finite aggregate overflow: clicks")
    if impressions is None:
        aggregation_errors.append("finite aggregate overflow: impressions")
    if aggregation_errors:
        return {
            "status": GSC_ERROR, "rows": len(rows), "clicks": None, "impressions": None,
            "position": None, "ctr": None, "paths": paths,
            "reasons": sorted(set(aggregation_errors)),
            "note": "finite aggregate overflow; totals withheld, not zero",
        }
    unknown_positions = sum(1 for row in rows if not row["position_known"])
    note = "clicks/impressions additive; position impression-weighted; ctr recomputed from sums"
    if unknown_positions:
        note += f"; position unknown on {unknown_positions} zero-exposure row(s)"
    return {
        "status": GSC_OK, "rows": len(rows),
        "clicks": _clean_number(clicks), "impressions": _clean_number(impressions),
        "position": _clean_number(weighted / impressions) if impressions > 0 else None,
        "ctr": _clean_number(clicks / impressions) if impressions > 0 else None,
        "paths": paths, "unknown_rows": {"position": unknown_positions},
        "notes": sorted({row["note"] for row in rows if row["note"]}), "note": note,
    }


def _article_ga4(rows):
    paths = sorted({row["path"] for row in rows})
    broken = [row for row in rows if row["status"] != GSC_OK]
    if broken:
        return {
            "status": GSC_ERROR, "rows": len(rows), "views": None, "sessions": None,
            "active_users": None, "paths": paths,
            "reasons": sorted({row["reason"] for row in broken if row["reason"]}),
            "note": "invalid provider metrics on a joined row; totals withheld, not zero",
        }
    views = _finite_sum(row["views"] for row in rows)
    sessions = _finite_sum(row["sessions"] for row in rows)
    aggregation_errors = []
    if views is None:
        aggregation_errors.append("finite aggregate overflow: views")
    if sessions is None:
        aggregation_errors.append("finite aggregate overflow: sessions")
    if aggregation_errors:
        return {
            "status": GSC_ERROR, "rows": len(rows), "views": None, "sessions": None,
            "active_users": None, "paths": paths,
            "reasons": sorted(set(aggregation_errors)),
            "note": "finite aggregate overflow; totals withheld, not zero",
        }
    note = "views are grouped by session landing page, not direct pageviews of this URL"
    if len(rows) == 1:
        active_users = rows[0]["active_users"]
    else:
        active_users = None
        note += "; nonadditive: active_users withheld across multiple rows, never summed"
    return {
        "status": GA4_OK, "rows": len(rows),
        "views": _clean_number(views), "sessions": _clean_number(sessions),
        "active_users": active_users, "paths": paths,
        "notes": sorted({row["note"] for row in rows if row["note"]}), "note": note,
    }


def _article_block(record, matched, status, kind):
    rows = matched.get(record["id"], [])
    if status == GSC_OK and rows:
        return _article_gsc(rows) if kind == "gsc" else _article_ga4(rows)
    if status != GSC_OK:
        note = f"provider status {status!r}: metrics unknown, not zero"
        missing = status
    else:
        note = "unknown: no provider row joined to this URL; absence is not zero"
        missing = GSC_MISSING if kind == "gsc" else GA4_MISSING
    return _unknown_gsc(missing, note) if kind == "gsc" else _unknown_ga4(missing, note)


def _unmatched_entry(row, status, reason):
    return {
        "provider": row["provider"], "raw": _safe_raw(row["raw"]), "normalized_path": row["path"],
        "cohort": row["cohort"], "status": row["status"], "owner_id": row["owner_id"],
        "reason": reason,
    }


def _unmatched_reason(row, status):
    if status != GSC_OK and row["status"] == GSC_OK:
        return f"provider status {status!r}: row not used, metrics stay unknown"
    if row["reason"]:
        return row["reason"]
    if row["cohort"] in ("reboot", "legacy"):
        return "no supplied deployed article owns this normalized path"
    return "no same-site identity; not attributable to an article"


def _provider_summary(status, rows, matched, duplicates, rejected, cohorts):
    attributed = sum(sum(row["status"] == GSC_OK for row in group) for group in matched.values())
    return {
        "status": status,
        "rows": len(rows),
        "attributed_rows": attributed,
        "unmatched_rows": len(rows) - attributed,
        "exact_duplicate_rows": duplicates,
        "conflicting_duplicate_rows": len(rejected),
        "excluded_or_unattributed_rows": cohorts["excluded"]["rows"] + cohorts["unattributed"]["rows"],
        "coverage_limited": bool(cohorts["excluded"]["rows"] or cohorts["unattributed"]["rows"]),
        "incomplete": status != GSC_OK
        or bool(rejected),
    }


def join_rows(articles, gsc_rows, ga4_rows, *, gsc_status="ok", ga4_status="ok", truncated=False):
    """Pure offline join of deployed articles to GSC page rows and GA4 landing rows.

    See the join contract above for input shapes and semantics.  Returns a
    JSON-serializable report whose ``measurement_status`` is ``ok`` only for
    complete, valid providers and input; ``incomplete`` or ``error`` mean callers
    must abstain rather than assert a number.  Per-article blocks use status
    ``ok``/``missing``/``error``, and every provider row that was not aggregated
    appears in ``unmatched`` with an explicit reason.  Raises ``ValueError`` for
    invalid, not-deployed, foreign, non-article, duplicate or ambiguous article
    input.
    """
    for name, value in (("gsc_status", gsc_status), ("ga4_status", ga4_status)):
        if value not in KNOWN_PROVIDER_STATUSES:
            raise ValueError(f"{name} must be one of {KNOWN_PROVIDER_STATUSES}, got {value!r}")
    if not isinstance(truncated, bool):
        raise ValueError(f"truncated must be a bool, got {truncated!r}")

    records, owners = _prepare_articles(articles)

    issues = []
    final_gsc_status = _provider_status(gsc_status, gsc_rows, "gsc_rows", issues, GSC_MISSING)
    final_ga4_status = _provider_status(ga4_status, ga4_rows, "ga4_rows", issues, GA4_MISSING)
    gsc_source = list(gsc_rows) if isinstance(gsc_rows, (list, tuple)) else []
    ga4_source = list(ga4_rows) if isinstance(ga4_rows, (list, tuple)) else []

    gsc_parsed = [_gsc_row(raw, index, issues) for index, raw in enumerate(gsc_source)]
    ga4_parsed = [_ga4_row(raw, index, issues) for index, raw in enumerate(ga4_source)]
    gsc_parsed, gsc_duplicates, gsc_rejected = _dedupe_rows(gsc_parsed, "gsc row", issues)
    ga4_parsed, ga4_duplicates, ga4_rejected = _dedupe_rows(ga4_parsed, "ga4 row", issues)
    gsc_all, ga4_all = gsc_parsed + gsc_rejected, ga4_parsed + ga4_rejected
    gsc_cohorts = _cohorts(gsc_all, "gsc", available=final_gsc_status == GSC_OK)
    ga4_cohorts = _cohorts(ga4_all, "ga4", available=final_ga4_status == GA4_OK)

    if final_gsc_status == GSC_OK:
        gsc_matched, gsc_unmatched = _match(gsc_parsed, owners)
    else:
        gsc_matched, gsc_unmatched = {}, list(gsc_parsed)
    if final_ga4_status == GA4_OK:
        ga4_matched, ga4_unmatched = _match(ga4_parsed, owners)
    else:
        ga4_matched, ga4_unmatched = {}, list(ga4_parsed)
    gsc_unmatched.extend(gsc_rejected)
    ga4_unmatched.extend(ga4_rejected)

    performance = []
    for record in records:
        performance.append({
            "id": record["id"],
            "canonical_url": record["canonical_url"],
            "deployed": True,
            "metadata": dict(record["metadata"]),
            "aliases": list(record["aliases"]),
            "gsc": _article_block(record, gsc_matched, final_gsc_status, "gsc"),
            "ga4": _article_block(record, ga4_matched, final_ga4_status, "ga4"),
        })

    unmatched = [
        _unmatched_entry(row, final_gsc_status if row["provider"] == "gsc" else final_ga4_status,
                         _unmatched_reason(row, final_gsc_status if row["provider"] == "gsc" else final_ga4_status))
        for row in gsc_unmatched + ga4_unmatched
    ]

    metric_errors = any(row["status"] != GSC_OK for row in gsc_parsed + ga4_parsed)
    aggregation_errors = []
    for provider, cohorts in (("gsc", gsc_cohorts), ("ga4", ga4_cohorts)):
        for label, cohort in cohorts.items():
            for error in cohort.get("aggregation_errors", []):
                aggregation_errors.append(f"{provider} {label}: {error}")
    for entry in performance:
        for provider in ("gsc", "ga4"):
            block = entry[provider]
            for error in block.get("reasons", []):
                if error.startswith("finite aggregate overflow"):
                    aggregation_errors.append(f"{provider} article {entry['id']}: {error}")
    issues.extend(aggregation_errors)
    conflicts = bool(gsc_rejected or ga4_rejected)
    provider_broken = final_gsc_status == GSC_ERROR or final_ga4_status == GSC_ERROR
    provider_missing = final_gsc_status == GSC_MISSING or final_ga4_status == GA4_MISSING
    if metric_errors or provider_broken or aggregation_errors:
        measurement_status = "error"
    elif truncated or conflicts or provider_missing:
        measurement_status = "incomplete"
    else:
        measurement_status = "ok"

    report = {
        "measurement_status": measurement_status,
        "truncated": truncated,
        "providers": {
            "gsc": _provider_summary(final_gsc_status, gsc_all, gsc_matched, gsc_duplicates, gsc_rejected, gsc_cohorts),
            "ga4": _provider_summary(final_ga4_status, ga4_all, ga4_matched, ga4_duplicates, ga4_rejected, ga4_cohorts),
        },
        "article_performance": performance,
        "cohorts": {"gsc": gsc_cohorts, "ga4": ga4_cohorts},
        "coverage": {
            "gsc": {
                "excluded_rows": gsc_cohorts["excluded"]["rows"],
                "unattributed_rows": gsc_cohorts["unattributed"]["rows"],
                "ordinary_untrusted_identity_is_limitation": True,
            },
            "ga4": {
                "excluded_rows": ga4_cohorts["excluded"]["rows"],
                "unattributed_rows": ga4_cohorts["unattributed"]["rows"],
                "ordinary_untrusted_identity_is_limitation": True,
            },
        },
        "unmatched": unmatched,
        "issues": issues,
        "limitations": list(LIMITATIONS),
    }
    if truncated:
        report["providers"]["gsc"]["incomplete"] = True
        report["providers"]["ga4"]["incomplete"] = True
        report["truncation_note"] = (
            "truncated provider response: totals are a lower bound on the window and cannot support certainty"
        )
    return report


# --- Read-only provider/catalog adapter --------------------------------------
#
# This layer deliberately sits below the pure join contract.  It only reads the
# deployed catalog and public pages, asks the existing analytics helper for
# read-only provider data, and maps verified payloads onto ``join_rows``.  No
# state directory is created and no provider response or credential detail is
# copied into an error artifact.

GA4_PROPERTY = "529369568"
GSC_SITE = "sc-domain:uutistenlukija.fi"
GA4_TIME_ZONE = "Europe/Helsinki"
GSC_TIME_ZONE = "America/Los_Angeles"
PROVIDER_ROW_CAP = 5000
DEFAULT_STATE_DIR = "/home/pertt/.local/share/uutistenlukija"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_ENDPOINT = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:runReport"
GSC_ENDPOINT = (
    "https://searchconsole.googleapis.com/webmasters/v3/sites/"
    + urllib.parse.quote(GSC_SITE, safe="")
    + "/searchAnalytics/query"
)


class _ProviderSchemaError(Exception):
    """Internal safe classification for a provider payload contract failure."""


class _LiveEvidenceError(Exception):
    """Internal safe classification for an unverified public catalog row."""


def _aware_datetime(value):
    if value is None:
        return dt.datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("now must be an ISO timezone-aware datetime") from error
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value


def _provider_requests(now):
    """Use the installed helper's date contract, adding only page dimensions/caps."""
    base = requests_for(now)
    if not isinstance(base, dict) or not isinstance(base.get("ga4"), dict) or not isinstance(base.get("gsc"), dict):
        raise _ProviderSchemaError("request contract")
    if not isinstance(base["ga4"].get("dateRanges"), list) or not base["ga4"]["dateRanges"]:
        raise _ProviderSchemaError("GA4 date window missing")
    if not all(isinstance(item, dict) and isinstance(item.get("startDate"), str)
               and isinstance(item.get("endDate"), str) for item in base["ga4"]["dateRanges"]):
        raise _ProviderSchemaError("GA4 date window invalid")
    if (not isinstance(base["gsc"].get("startDate"), str)
            or not isinstance(base["gsc"].get("endDate"), str)
            or base["gsc"].get("dataState") != "final"):
        raise _ProviderSchemaError("GSC final window invalid")
    ga4 = dict(base["ga4"])
    ga4["dimensions"] = [{"name": "landingPagePlusQueryString"}, {"name": "hostName"}]
    ga4["metrics"] = [
        {"name": "screenPageViews"},
        {"name": "activeUsers"},
        {"name": "sessions"},
    ]
    ga4["limit"], ga4["offset"] = PROVIDER_ROW_CAP, 0
    gsc = dict(base["gsc"])
    gsc["dimensions"], gsc["rowLimit"] = ["page"], PROVIDER_ROW_CAP
    return {"ga4": ga4, "gsc": gsc}


def _safe_count(value):
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count >= 0 else None


def _provider_number(value):
    """Decode Google string counts without turning malformed values into zero."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return value
    return value


def _header_names(data, field):
    headers = data.get(field)
    if not isinstance(headers, list):
        raise _ProviderSchemaError("missing response headers")
    names = []
    for header in headers:
        if not isinstance(header, dict) or not isinstance(header.get("name"), str):
            raise _ProviderSchemaError("invalid response headers")
        names.append(header["name"])
    return names


def _adapt_ga4(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("rows", []), list):
        raise _ProviderSchemaError("invalid GA4 response")
    if _header_names(payload, "dimensionHeaders") != ["landingPagePlusQueryString", "hostName"]:
        raise _ProviderSchemaError("unexpected GA4 dimensions")
    if _header_names(payload, "metricHeaders") != ["screenPageViews", "activeUsers", "sessions"]:
        raise _ProviderSchemaError("unexpected GA4 metrics")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("timeZone") != GA4_TIME_ZONE:
        raise _ProviderSchemaError("unexpected GA4 timezone")
    adapted = []
    for source in payload.get("rows", []):
        if not isinstance(source, dict):
            raise _ProviderSchemaError("invalid GA4 row")
        dimensions, metrics = source.get("dimensionValues"), source.get("metricValues")
        if not isinstance(dimensions, list) or len(dimensions) != 2 or not all(isinstance(item, dict) for item in dimensions):
            raise _ProviderSchemaError("invalid GA4 dimensions")
        if not isinstance(metrics, list) or len(metrics) != 3 or not all(isinstance(item, dict) for item in metrics):
            raise _ProviderSchemaError("invalid GA4 metrics")
        adapted.append({
            "landing_page": dimensions[0].get("value"),
            "hostname": dimensions[1].get("value"),
            "views": _provider_number(metrics[0].get("value")),
            "active_users": _provider_number(metrics[1].get("value")),
            "sessions": _provider_number(metrics[2].get("value")),
        })
    count = _safe_count(payload.get("rowCount", len(adapted)))
    if count is None:
        raise _ProviderSchemaError("invalid GA4 row count")
    return adapted, count > len(adapted) or len(adapted) >= PROVIDER_ROW_CAP


def _adapt_gsc(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("rows", []), list):
        raise _ProviderSchemaError("invalid GSC response")
    if "dimensionHeaders" in payload and _header_names(payload, "dimensionHeaders") != ["page"]:
        raise _ProviderSchemaError("unexpected GSC dimensions")
    if "metricHeaders" in payload and _header_names(payload, "metricHeaders") != [
        "clicks", "impressions", "ctr", "position"
    ]:
        raise _ProviderSchemaError("unexpected GSC metrics")
    adapted = []
    for source in payload.get("rows", []):
        if not isinstance(source, dict):
            raise _ProviderSchemaError("invalid GSC row")
        keys = source.get("keys")
        if isinstance(keys, list) and len(keys) == 1:
            page = keys[0]
        elif "page" in source:
            page = source.get("page")
        else:
            raise _ProviderSchemaError("invalid GSC dimensions")
        adapted.append({
            "page": page,
            "clicks": _provider_number(source.get("clicks")),
            "impressions": _provider_number(source.get("impressions")),
            "ctr": _provider_number(source.get("ctr")),
            "position": _provider_number(source.get("position")),
        })
    count_value = payload.get("rowCount", len(adapted))
    count = _safe_count(count_value)
    if count is None:
        raise _ProviderSchemaError("invalid GSC row count")
    return adapted, count > len(adapted) or len(adapted) >= PROVIDER_ROW_CAP


def _credential_token(scope):
    result = service_account_access_token([scope])
    if isinstance(result, str) and result:
        return result
    if not isinstance(result, (tuple, list)) or not result or not isinstance(result[0], str) or not result[0]:
        raise RuntimeError("credential unavailable")
    return result[0]


def _fetch_provider(kind, payload, timeout):
    """Return join rows plus a safe operator-facing fetch summary."""
    scope = GA4_SCOPE if kind == "ga4" else GSC_SCOPE
    endpoint = GA4_ENDPOINT if kind == "ga4" else GSC_ENDPOINT
    entry = {
        "status": "error", "read_only": True, "scope": scope.rsplit("/", 1)[-1],
        "cap": PROVIDER_ROW_CAP, "truncated": False, "rows": 0,
        "data_scope": "landing_page_rows" if kind == "ga4" else "page_rows",
    }
    try:
        token = _credential_token(scope)
    except Exception:
        entry["error"] = "credential_error"
        return None, "error", entry
    try:
        payload_data = query(endpoint, payload, token)
        if kind == "ga4":
            rows, truncated = _adapt_ga4(payload_data)
        else:
            rows, truncated = _adapt_gsc(payload_data)
    except _ProviderSchemaError:
        entry["error"] = "schema_error"
        return None, "error", entry
    except (TimeoutError, urllib.error.URLError):
        entry["error"] = "transport_timeout_or_error"
        return None, "error", entry
    except Exception:
        # The helper's own exception text is intentionally not copied into the artifact.
        entry["error"] = "provider_error"
        return None, "error", entry
    entry.update(status="ok", rows=len(rows), truncated=bool(truncated))
    return rows, GSC_OK, entry


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonicals = []
        self.canonical_ambiguous = False
        self.description = False
        self.og = False
        self.jsonld = False

    def handle_starttag(self, tag, attrs):
        lower_tag = tag.lower()
        if lower_tag == "link":
            rel_values = [value for key, value in attrs if str(key).lower() == "rel"]
            is_canonical = any(
                isinstance(value, str) and "canonical" in value.lower().split()
                for value in rel_values
            )
            if is_canonical:
                names = [str(key).lower() for key, _ in attrs]
                if len(names) != len(set(names)):
                    self.canonical_ambiguous = True
                    return
                attributes = {str(key).lower(): value for key, value in attrs}
                if attributes.get("href") is not None:
                    self.canonicals.append(attributes["href"])
        elif lower_tag == "meta":
            attributes = {str(key).lower(): value for key, value in attrs}
            name = (attributes.get("name") or "").lower()
            property_name = (attributes.get("property") or "").lower()
            if name == "description":
                self.description = True
            if property_name.startswith("og:"):
                self.og = True
        elif lower_tag == "script":
            attributes = {str(key).lower(): value for key, value in attrs}
            script_type = (attributes.get("type") or "").lower().split(";", 1)[0].strip()
            if script_type == "application/ld+json":
                self.jsonld = True


def _public_bytes(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "uutistenlukija-measurement/1"})
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, float(timeout))) as response:
            status = getattr(response, "status", None)
            if isinstance(status, int) and status >= 400:
                raise _LiveEvidenceError("HTTP failure")
            final_url = response.geturl() if hasattr(response, "geturl") else None
            data = response.read()
    except _LiveEvidenceError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise _LiveEvidenceError("public fetch failure") from error
    except Exception as error:
        raise _LiveEvidenceError("public fetch failure") from error
    if not isinstance(data, (bytes, bytearray)) or len(data) > 8 * 1024 * 1024:
        raise _LiveEvidenceError("public response invalid")
    if isinstance(final_url, str) and final_url != url:
        raise _LiveEvidenceError("public URL redirected")
    return bytes(data)


def _sitemap_paths(raw):
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, TypeError, ValueError) as error:
        raise _LiveEvidenceError("sitemap invalid") from error
    paths = set()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "loc" or not isinstance(element.text, str):
            continue
        raw_url = element.text.strip()
        path = normalize_url(raw_url)
        if path is not None and raw_url == SITE_ORIGIN + path:
            paths.add(path)
    return paths


def _verify_live_article(url, path, timeout):
    raw = _public_bytes(url, timeout)
    parser = _MetadataParser()
    metadata_unknown = False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        metadata_unknown = True
    try:
        parser.feed(text)
        parser.close()
    except (UnicodeError, ValueError):
        metadata_unknown = True
    if parser.canonical_ambiguous or parser.canonicals != [url]:
        raise _LiveEvidenceError("article canonical mismatch")
    return {
        "description": None if metadata_unknown else bool(parser.description),
        "og": None if metadata_unknown else bool(parser.og),
        "jsonld": None if metadata_unknown else bool(parser.jsonld),
    }


def _readback_evidence(state_dir, job_id, run_id, current_path, sitemap_paths):
    if run_id is None:
        return {"present": False, "canonical": None, "alias": None, "valid": False}
    path = Path(state_dir) / "deployments" / str(run_id) / "live-readback.json"
    if not path.is_file():
        return {"present": False, "canonical": None, "alias": None, "valid": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"present": True, "canonical": None, "alias": None, "valid": False}
    if not isinstance(data, dict):
        return {"present": True, "canonical": None, "alias": None, "valid": False}
    identity = data.get("job_id") == job_id or data.get("id") == job_id
    raw_canonical = data.get("canonical_article")
    canonical_path = normalize_url(raw_canonical)
    valid = identity and raw_canonical == (SITE_ORIGIN + canonical_path if canonical_path else None)
    alias = canonical_path if valid and canonical_path != current_path else None
    in_sitemap = bool(canonical_path and canonical_path in sitemap_paths)
    return {
        "present": True, "canonical": canonical_path, "alias": alias,
        "valid": bool(valid), "in_sitemap": in_sitemap,
    }


def _load_deployed_rows(state_dir):
    db_path = Path(state_dir) / "jobs.sqlite"
    if not db_path.is_file():
        raise _LiveEvidenceError("deployment catalog unavailable")
    try:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as error:
        raise _LiveEvidenceError("deployment catalog unavailable") from error
    connection.row_factory = sqlite3.Row
    try:
        try:
            rows = connection.execute(
                """SELECT j.id, j.draft, p.run_id
                     FROM jobs AS j JOIN publications AS p ON p.job_id = j.id
                    WHERE p.status = 'deployed' ORDER BY j.created_at DESC, j.id"""
            ).fetchall()
        except sqlite3.Error:
            rows = connection.execute(
                """SELECT j.id, j.draft, p.run_id
                     FROM jobs AS j JOIN publications AS p ON p.job_id = j.id
                    WHERE p.status = 'deployed' ORDER BY j.id"""
            ).fetchall()
    except sqlite3.Error as error:
        raise _LiveEvidenceError("deployment catalog schema unavailable") from error
    finally:
        connection.close()
    return rows


def _catalog(state_dir, timeout):
    """Read and verify the deployed article catalog without touching state."""
    result = {
        "status": "incomplete", "evidence": {}, "included": 0,
        "deployed": 0, "exclusions": [], "coverage": {}, "articles": [],
    }
    try:
        db_rows = _load_deployed_rows(state_dir)
    except _LiveEvidenceError:
        result["exclusions"].append({"reason": "deployed publication catalog unavailable"})
        result["coverage"] = {"complete": False, "reason": "deployed catalog unavailable"}
        return result
    result["deployed"] = len(db_rows)
    try:
        sitemap_raw = _public_bytes(SITE_ORIGIN + "/sitemap.xml", timeout)
        sitemap_paths = _sitemap_paths(sitemap_raw)
        sitemap_ok = True
    except _LiveEvidenceError:
        sitemap_paths, sitemap_ok = set(), False
    seen_ids, seen_paths, seen_aliases = set(), set(), {}
    readback_present = readback_in_current = readback_not_current = missing_readback = 0
    for source in db_rows:
        identifier = source["id"]
        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
            result["exclusions"].append({"id": str(identifier), "reason": "duplicate or invalid deployed identity"})
            continue
        seen_ids.add(identifier)
        try:
            draft = json.loads(source["draft"]) if isinstance(source["draft"], str) else source["draft"]
            if not isinstance(draft, dict):
                raise ValueError
            from .site import article_path
            candidate_path = normalize_url(SITE_ORIGIN + "/" + article_path({"id": identifier, "draft": draft}))
            if candidate_path is None or not candidate_path.startswith("/uutiset/"):
                raise ValueError
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            result["exclusions"].append({"id": identifier, "reason": "deployed article identity is malformed"})
            continue
        evidence = _readback_evidence(state_dir, identifier, source["run_id"], candidate_path, sitemap_paths)
        if evidence["present"]:
            readback_present += 1
            if evidence.get("canonical") in sitemap_paths:
                readback_in_current += 1
            elif evidence.get("canonical") is not None:
                readback_not_current += 1
        else:
            missing_readback += 1
        if not sitemap_ok:
            result["exclusions"].append({"id": identifier, "reason": "current public sitemap unavailable"})
            continue
        if candidate_path not in sitemap_paths:
            result["exclusions"].append({"id": identifier, "reason": "current article path is not in the public sitemap"})
            continue
        candidate_url = SITE_ORIGIN + candidate_path
        try:
            metadata = _verify_live_article(candidate_url, candidate_path, timeout)
        except _LiveEvidenceError:
            result["exclusions"].append({"id": identifier, "reason": "current article canonical proof unavailable"})
            continue
        aliases = []
        if evidence.get("alias") is not None:
            alias = evidence["alias"]
            if alias in seen_paths or alias in seen_aliases:
                result["exclusions"].append({"id": identifier, "reason": "duplicate historical canonical identity"})
                continue
            aliases.append(alias)
            seen_aliases[alias] = identifier
        if candidate_path in seen_paths or candidate_path in seen_aliases:
            result["exclusions"].append({"id": identifier, "reason": "duplicate current canonical identity"})
            continue
        seen_paths.add(candidate_path)
        result["articles"].append({
            "id": identifier, "canonical_url": candidate_url, "deployed": True,
            "aliases": aliases, "metadata": metadata,
        })
    result["included"] = len(result["articles"])
    result["evidence"] = {
        "deployed": result["deployed"], "readback_present": readback_present,
        "readback_canonical_in_current_sitemap": readback_in_current,
        "readback_canonical_not_in_current_sitemap": readback_not_current,
        "missing_readback": missing_readback,
        "current_sitemap_verified": sitemap_ok,
    }
    result["coverage"] = {
        "complete": not result["exclusions"] and sitemap_ok,
        "included": result["included"], "excluded": len(result["exclusions"]),
    }
    result["status"] = "ok" if result["coverage"]["complete"] else "incomplete"
    return result


def _catalog_public(result):
    return {key: value for key, value in result.items() if key != "articles"}


def collect(state_dir=DEFAULT_STATE_DIR, now=None, timeout=30):
    """Collect a read-only, canonical-provenance-bound measurement artifact."""
    anchor = _aware_datetime(now)
    generated = dt.datetime.now(timezone.utc).isoformat()
    catalog = _catalog(state_dir, timeout)
    request_error = None
    try:
        payloads = _provider_requests(anchor)
    except Exception:
        payloads = {"ga4": {}, "gsc": {}}
        request_error = "request_contract_error"
    provider_rows, provider_status, provider_fetch = {}, {}, {}
    for kind in ("gsc", "ga4"):
        if request_error:
            provider_rows[kind] = None
            provider_status[kind] = "error"
            provider_fetch[kind] = {
                "status": "error", "read_only": True, "scope": "unknown",
                "cap": PROVIDER_ROW_CAP, "truncated": False, "rows": 0,
                "data_scope": "landing_page_rows" if kind == "ga4" else "page_rows",
                "error": request_error,
            }
            continue
        rows, status, summary = _fetch_provider(kind, payloads[kind], timeout)
        provider_rows[kind], provider_status[kind], provider_fetch[kind] = rows, status, summary
    truncated = any(summary.get("truncated", False) for summary in provider_fetch.values())
    report = join_rows(
        catalog["articles"], provider_rows["gsc"], provider_rows["ga4"],
        gsc_status=provider_status["gsc"], ga4_status=provider_status["ga4"], truncated=truncated,
    )
    if catalog["status"] != "ok" and report["measurement_status"] == "ok":
        report["measurement_status"] = "incomplete"
    report["generated_at_utc"] = generated
    report["range_anchor_instant_utc"] = anchor.astimezone(timezone.utc).isoformat()
    report["windows"] = {
        "ga4": {**payloads["ga4"], "time_zone": GA4_TIME_ZONE},
        "gsc": {**payloads["gsc"], "time_zone": GSC_TIME_ZONE},
    }
    report["catalog"] = _catalog_public(catalog)
    report["provider_fetch"] = provider_fetch
    report["metric_semantics"] = [
        "GSC clicks are not GA4 views.",
        "GA4 landing-page views are grouped by session landing page; they are not direct article pageviews.",
        "GA4 active users are nonadditive and are never summed across landing rows.",
        "Same-domain legacy history remains in provider cohorts; it is not silently assigned to deployed articles.",
        "Privacy-suppressed or absent provider rows remain unknown, not zero.",
    ]
    report["coverage"]["catalog"] = {
        "status": catalog["status"], "deployed": catalog["deployed"],
        "included": catalog["included"], "excluded": len(catalog["exclusions"]),
    }
    if request_error:
        report["issues"].append(request_error)
    return report


def _main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only deployed article measurement artifact")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--now", default=None, help="timezone-aware ISO report instant")
    args = parser.parse_args(argv)
    result = collect(state_dir=args.state_dir, now=args.now, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI integration tests
    raise SystemExit(_main())
