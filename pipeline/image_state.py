"""Persistent and repository-backed state for the image pipeline.

The ignored cache prevents duplicate choices inside one long-lived process or
checkout. GitHub Actions starts from a fresh checkout, however, so recent
published post frontmatter is also indexed before a stock candidate is used.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Mapping
from urllib.parse import unquote, urlparse


_PIPELINE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PIPELINE_DIR.parent
_STATE_FILE = str(_PIPELINE_DIR / "cache" / "used_images.json")
POSTS_DIR = _PROJECT_ROOT / "content" / "posts"
RECENT_REUSE_DAYS = 30

_UNSPLASH_ID_RE = re.compile(r"(?:^|-)([A-Za-z0-9_-]{11})$")
_PEXELS_PAGE_ID_RE = re.compile(r"-(\d+)$")
_PEXELS_CDN_ID_RE = re.compile(r"/photos/(\d+)(?:/|$)")
_UNSPLASH_ASSET_RE = re.compile(r"/(photo-[A-Za-z0-9_-]+)(?:/|$)")
_RECENT_INDEX_CACHE: tuple[str, int, str, int, frozenset[str]] | None = None
_IDENTITY_ALIAS_CACHE: dict[str, frozenset[str]] = {}
_PROCESS_USED_ALIASES: set[str] = set()
_STATE_LOCK = threading.RLock()


def _normalized_provider(provider: str, *urls: str) -> str:
    value = str(provider or "").strip().lower()
    aliases = {
        "images.unsplash.com": "unsplash",
        "www.unsplash.com": "unsplash",
        "images.pexels.com": "pexels",
        "www.pexels.com": "pexels",
    }
    value = aliases.get(value, value)
    if value in {"unsplash", "pexels"}:
        return value

    for raw_url in urls:
        parsed = urlparse(str(raw_url or ""))
        host = parsed.netloc.lower().split(":", 1)[0]
        if host == "unsplash.com" or host.endswith(".unsplash.com"):
            return "unsplash"
        if host == "pexels.com" or host.endswith(".pexels.com"):
            return "pexels"
    return value


def _candidate_values(
    candidate: Mapping[str, Any] | str | int | None,
    *,
    candidate_id: Any = "",
    source_url: str = "",
    image_url: str = "",
) -> tuple[str, list[str]]:
    identifier = str(candidate_id or "").strip()
    urls = [str(source_url or "").strip(), str(image_url or "").strip()]

    if isinstance(candidate, Mapping):
        if not identifier:
            identifier = str(
                candidate.get("id")
                or candidate.get("candidate_id")
                or candidate.get("image_candidate_id")
                or ""
            ).strip()
        for key in (
            "photo_page",
            "pexels_url",
            "image_candidate_url",
            "image_source_url",
            "url",
            "url_full",
            "url_regular",
            "url_small",
            "url_thumb",
            "thumb_url",
            "image",
            "image_thumb",
        ):
            value = str(candidate.get(key) or "").strip()
            if value:
                urls.append(value)
    elif candidate is not None:
        value = str(candidate).strip()
        if "://" in value or value.startswith("/"):
            urls.append(value)
        elif not identifier:
            identifier = value

    return identifier, [value for value in urls if value]


def _provider_id_from_url(provider: str, raw_url: str) -> str:
    parsed = urlparse(raw_url)
    path = unquote(parsed.path or "").rstrip("/")
    if provider == "unsplash":
        host = parsed.netloc.lower().split(":", 1)[0]
        if host == "unsplash.com" or host.endswith(".unsplash.com"):
            segment = path.rsplit("/", 1)[-1]
            match = _UNSPLASH_ID_RE.search(segment)
            if match:
                return match.group(1)
    elif provider == "pexels":
        match = _PEXELS_CDN_ID_RE.search(path)
        if match:
            return match.group(1)
        segment = path.rsplit("/", 1)[-1]
        match = _PEXELS_PAGE_ID_RE.search(segment)
        if match:
            return match.group(1)
    return ""


def _canonical_url_fallback(provider: str, raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if not parsed.netloc:
        path = re.sub(r"/+", "/", parsed.path or raw_url).rstrip("/")
        return f"{provider}:path:{path}" if provider and path else ""

    host = parsed.netloc.lower().split(":", 1)[0]
    path = re.sub(r"/+", "/", unquote(parsed.path or "")).rstrip("/")
    if provider == "unsplash" and host.endswith("images.unsplash.com"):
        match = _UNSPLASH_ASSET_RE.search(path)
        if match:
            return f"unsplash:asset:{match.group(1)}"
    if provider == "pexels":
        match = _PEXELS_CDN_ID_RE.search(path)
        if match:
            return f"pexels:id:{match.group(1)}"
    if not host or not path:
        return ""
    return f"{provider or host}:url:{host}{path}"


def image_identity_aliases(
    provider: str,
    candidate: Mapping[str, Any] | str | int | None = None,
    *,
    candidate_id: Any = "",
    source_url: str = "",
    image_url: str = "",
) -> frozenset[str]:
    """Return every stable provider identity evidenced by a candidate.

    A provider ID remains the preferred persisted identity. Provider CDN asset
    paths are retained as aliases so an ID-bearing API result also matches an
    older post that persisted only a transformed image URL.
    """

    identifier, urls = _candidate_values(
        candidate,
        candidate_id=candidate_id,
        source_url=source_url,
        image_url=image_url,
    )
    normalized_provider = _normalized_provider(provider, *urls)
    aliases: set[str] = set()

    if identifier and identifier.lower() not in {"none", "null", "unknown"}:
        aliases.add(f"{normalized_provider or 'image'}:id:{identifier}")

    for raw_url in urls:
        extracted = _provider_id_from_url(normalized_provider, raw_url)
        if extracted:
            aliases.add(f"{normalized_provider}:id:{extracted}")

    fallbacks = {
        fallback
        for raw_url in urls
        if (fallback := _canonical_url_fallback(normalized_provider, raw_url))
    }
    stable_asset_fallbacks = {
        fallback
        for fallback in fallbacks
        if ":asset:" in fallback or ":id:" in fallback
    }
    aliases.update(stable_asset_fallbacks)

    # Generic normalized URLs and local paths are a last resort only. Keeping
    # them out of an ID-bearing alias group avoids coupling a provider asset to
    # a generated local filename.
    if not aliases:
        aliases.update(fallbacks)
    return frozenset(aliases)


def _register_identity_aliases(identity: str, aliases: frozenset[str]) -> None:
    if not identity:
        return
    combined = set(aliases)
    combined.add(identity)
    with _STATE_LOCK:
        for alias in tuple(combined):
            combined.update(_IDENTITY_ALIAS_CACHE.get(alias, ()))
        registered = frozenset(combined)
        for alias in registered:
            _IDENTITY_ALIAS_CACHE[alias] = registered


def _aliases_for_identity(identity: str) -> frozenset[str]:
    with _STATE_LOCK:
        return _IDENTITY_ALIAS_CACHE.get(identity, frozenset({identity}))


def canonical_image_identity(
    provider: str,
    candidate: Mapping[str, Any] | str | int | None = None,
    *,
    candidate_id: Any = "",
    source_url: str = "",
    image_url: str = "",
) -> str:
    """Return one stable, provider-aware stock candidate identity.

    Provider IDs take precedence over resize/crop/format URLs. When an older
    post lacks the persisted ID, provider page/CDN URLs are parsed and query
    parameters are ignored. The provider prefix prevents numeric IDs from
    colliding across Unsplash and Pexels.
    """

    identifier, urls = _candidate_values(
        candidate,
        candidate_id=candidate_id,
        source_url=source_url,
        image_url=image_url,
    )
    normalized_provider = _normalized_provider(provider, *urls)
    identity = ""
    if identifier and identifier.lower() not in {"none", "null", "unknown"}:
        identity = f"{normalized_provider or 'image'}:id:{identifier}"
    else:
        for raw_url in urls:
            extracted = _provider_id_from_url(normalized_provider, raw_url)
            if extracted:
                identity = f"{normalized_provider}:id:{extracted}"
                break
        if not identity:
            for raw_url in urls:
                fallback = _canonical_url_fallback(normalized_provider, raw_url)
                if fallback:
                    identity = fallback
                    break

    if identity:
        aliases = image_identity_aliases(
            provider,
            candidate,
            candidate_id=candidate_id,
            source_url=source_url,
            image_url=image_url,
        )
        _register_identity_aliases(identity, aliases)
    return identity


def _empty_state() -> dict[str, Any]:
    return {"used_ids": {}, "query_indices": {}}


def _load_state() -> dict[str, Any] | None:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return _empty_state()
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(state, dict):
        return None
    used_ids = state.get("used_ids", {})
    query_indices = state.get("query_indices", {})
    if not isinstance(used_ids, dict) or not isinstance(query_indices, dict):
        return None
    state["used_ids"] = used_ids
    state["query_indices"] = query_indices
    return state


def _save_state(state: dict[str, Any]) -> bool:
    temp_path = ""
    descriptor: int | None = None
    try:
        parent = os.path.dirname(_STATE_FILE) or "."
        os.makedirs(parent, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(_STATE_FILE)}.",
            suffix=".tmp",
            dir=parent,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(state, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, _STATE_FILE)
        temp_path = ""
        return True
    except Exception as exc:
        print(f"[image_state] Failed to save state: {exc}")
        return False
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


_TRACKED_FRONTMATTER_FIELDS = frozenset({
    "date",
    "image",
    "image_thumb",
    "image_source",
    "image_source_url",
    "image_candidate_id",
    "image_candidate_url",
    "image_category_fallback",
})


def _flat_frontmatter(path: Path) -> dict[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        return None

    fields: dict[str, str] = {}
    for line in lines[1:closing_index]:
        if not line:
            continue
        if line[0].isspace():
            nested_key = re.match(r"\s*(?:-\s*)?([A-Za-z0-9_-]+)\s*:", line)
            if nested_key and nested_key.group(1) in _TRACKED_FRONTMATTER_FIELDS:
                return None
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in _TRACKED_FRONTMATTER_FIELDS and key in fields:
            return None
        fields[key] = _strip_scalar(value)
    return fields


def _frontmatter_datetime(fields: Mapping[str, str], path: Path) -> datetime | None:
    value = str(fields.get("date") or "").strip()
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    match = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.name)
    if match:
        try:
            return datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _is_true(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def recent_tracked_image_identities(
    posts_dir: Path | str = POSTS_DIR,
    *,
    now: datetime | None = None,
    window_days: int = RECENT_REUSE_DAYS,
    _fail_on_unavailable: bool = False,
) -> set[str]:
    """Index all stable stock identity aliases from recent persisted posts."""

    root = Path(posts_dir)
    if not root.is_dir():
        if _fail_on_unavailable:
            raise FileNotFoundError(f"recent post index unavailable: {root}")
        return set()
    if window_days <= 0:
        return set()
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    cutoff = reference - timedelta(days=window_days)

    identities: set[str] = set()
    for path in root.glob("*.md"):
        fields = _flat_frontmatter(path)
        if fields is None or not fields:
            filename_date = _frontmatter_datetime({}, path)
            if _fail_on_unavailable and (
                filename_date is None or filename_date >= cutoff
            ):
                raise ValueError(f"recent post evidence unreadable or malformed: {path.name}")
            continue
        if _is_true(fields.get("image_category_fallback", "")):
            continue
        published_at = _frontmatter_datetime(fields, path)
        if published_at is None or published_at < cutoff:
            continue

        provider = _normalized_provider(
            fields.get("image_source", ""),
            fields.get("image_candidate_url", ""),
            fields.get("image_source_url", ""),
            fields.get("image", ""),
        )
        if provider not in {"unsplash", "pexels"}:
            continue
        aliases = image_identity_aliases(
            provider,
            {
                "image_candidate_id": fields.get("image_candidate_id", ""),
                "image_candidate_url": fields.get("image_candidate_url", ""),
                "image_source_url": fields.get("image_source_url", ""),
                "image": fields.get("image", ""),
                "image_thumb": fields.get("image_thumb", ""),
            },
        )
        identities.update(aliases)
    return identities


def _recent_index() -> frozenset[str] | None:
    global _RECENT_INDEX_CACHE
    root = Path(POSTS_DIR)
    try:
        directory_mtime = root.stat().st_mtime_ns
    except OSError:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    cache_key = (str(root.resolve()), directory_mtime, today, RECENT_REUSE_DAYS)
    if _RECENT_INDEX_CACHE and _RECENT_INDEX_CACHE[:4] == cache_key:
        return _RECENT_INDEX_CACHE[4]
    try:
        identities = frozenset(
            recent_tracked_image_identities(root, _fail_on_unavailable=True)
        )
    except (OSError, ValueError):
        return None
    _RECENT_INDEX_CACHE = (*cache_key, identities)
    return identities


def is_image_used(image_identity: str) -> bool:
    identity = str(image_identity or "").strip()
    if not identity:
        return True

    aliases = _aliases_for_identity(identity)
    with _STATE_LOCK:
        if not aliases.isdisjoint(_PROCESS_USED_ALIASES):
            return True
        state = _load_state()
    # Existing but unreadable/malformed duplicate state must not silently make
    # every image appear fresh.
    if state is None:
        return True

    used_ids = state["used_ids"]
    recent_index = _recent_index()
    if recent_index is None:
        return True
    if not aliases.isdisjoint(used_ids) or not aliases.isdisjoint(recent_index):
        return True

    # Honor pre-migration local cache entries, which stored only the raw ID.
    for alias in aliases:
        if ":id:" in alias and alias.rsplit(":id:", 1)[1] in used_ids:
            return True
    return False


def mark_image_used(image_identity: str) -> None:
    identity = str(image_identity or "").strip()
    if not identity:
        return
    aliases = _aliases_for_identity(identity)
    timestamp = datetime.now(timezone.utc).isoformat()
    with _STATE_LOCK:
        # Retain the mark even if the cache cannot be read or atomically
        # replaced. This closes the duplicate window for the running process.
        _PROCESS_USED_ALIASES.update(aliases)
        state = _load_state()
        if state is None:
            return
        for alias in aliases:
            state["used_ids"][alias] = timestamp
        if len(state["used_ids"]) > 2000:
            items = sorted(
                state["used_ids"].items(),
                key=lambda item: str(item[1]),
                reverse=True,
            )
            state["used_ids"] = dict(items[:1000])
        _save_state(state)


def get_query_index(query: str) -> int:
    with _STATE_LOCK:
        state = _load_state()
    if state is None:
        return 0
    return state["query_indices"].get(query, 0)


def set_query_index(query: str, index: int) -> None:
    with _STATE_LOCK:
        state = _load_state()
        if state is None:
            return
        state["query_indices"][query] = index
        if len(state["query_indices"]) > 500:
            state["query_indices"] = dict(list(state["query_indices"].items())[-300:])
        _save_state(state)
