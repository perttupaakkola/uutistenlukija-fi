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
    ``/`` and the exact reboot prefixes ``/uutiset`` and ``/sivu`` (or
    ``/uutiset/...`` and ``/sivu/...``; e.g. ``/uutisetfake/`` is legacy) are
    ``reboot``; every other same-site path is ``legacy``; unnormalizable
    values are ``excluded``.

Pure and offline: no network, no state, no redirect resolution.
"""

from urllib.parse import unquote_to_bytes, urlsplit

SITE_HOST = "uutistenlukija.fi"
UNSAFE_DECODED = ("?", "#", "%")
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
