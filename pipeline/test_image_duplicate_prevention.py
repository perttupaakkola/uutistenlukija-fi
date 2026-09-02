#!/usr/bin/env python3
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch


PIPELINE_DIR = Path(__file__).resolve().parent
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import image_candidate_guard  # noqa: E402
import image_query  # noqa: E402
import image_state  # noqa: E402
from image_provider_result import build_provider_result, search_photos  # noqa: E402
import pexels  # noqa: E402
import unsplash  # noqa: E402


class _Intent:
    def to_dict(self) -> dict[str, object]:
        return {"subject": "grounded test subject", "must_have": []}


class _Brief:
    intent = _Intent()


_RED_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg=="
)
_BLUE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGNkYPjPwMDAxMDAwMDAAAALHwEDmIWXfgAAAABJRU5ErkJggg=="
)


class _ImageResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        content_type: str = "image/png",
        content_length: bool = True,
    ) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {"Content-Type": content_type}
        if content_length:
            self.headers["Content-Length"] = str(len(payload))
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def _accept_all(candidates, **_kwargs):
    accepted = []
    for candidate in candidates:
        enriched = dict(candidate)
        source_url = candidate.get("photo_page") or candidate.get("pexels_url") or candidate.get("url") or ""
        enriched.update({
            "_image_decision": {
                "candidate_id": str(candidate.get("id")),
                "source_url": source_url,
                "score": 75,
                "reasons": ["grounded candidate accepted"],
            },
            "_image_visual_intent": _Brief.intent.to_dict(),
            "_image_visual_brief": {},
            "_image_visual_judge": {
                "score": 75,
                "accepted": True,
                "reasons": ["grounded candidate accepted"],
            },
            "_image_concept": "grounded test subject",
        })
        accepted.append(enriched)
    return accepted, []


class PexelsDownloadSecurityTests(unittest.TestCase):
    def test_same_slug_new_candidate_cannot_reuse_stale_cached_bytes(self) -> None:
        first_response = _ImageResponse(_RED_PNG + (b"\0" * 1200))
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pexels, "_cache_dir", return_value=tmp), \
             patch.object(
                 pexels.urllib.request,
                 "urlopen",
                 side_effect=[first_response, OSError("second download failed")],
             ) as urlopen:
            first = pexels._download_image(
                "https://images.pexels.com/photos/101/first.png",
                "shared-story",
                candidate_identity="pexels:id:101",
            )
            second = pexels._download_image(
                "https://images.pexels.com/photos/202/second.png",
                "shared-story",
                candidate_identity="pexels:id:202",
            )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(urlopen.call_count, 2)

    def test_untrusted_initial_download_origin_is_rejected_without_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pexels, "_cache_dir", return_value=tmp), \
             patch.object(pexels.urllib.request, "urlopen") as urlopen:
            result = pexels._download_image(
                "https://attacker.example/photos/101/image.png",
                "story",
                candidate_identity="pexels:id:101",
            )

        self.assertIsNone(result)
        urlopen.assert_not_called()

    def test_download_requires_image_mime_and_decodable_supported_raster(self) -> None:
        cases = (
            ("text/html", _RED_PNG + (b"x" * 1200)),
            ("image/png", b"not an image" * 200),
        )
        for content_type, payload in cases:
            with self.subTest(content_type=content_type), \
                 tempfile.TemporaryDirectory() as tmp, \
                 patch.object(pexels, "_cache_dir", return_value=tmp), \
                 patch.object(
                     pexels.urllib.request,
                     "urlopen",
                     return_value=_ImageResponse(payload, content_type=content_type),
                 ):
                result = pexels._download_image(
                    "https://images.pexels.com/photos/101/image.png",
                    "story",
                    candidate_identity="pexels:id:101",
                )

                self.assertIsNone(result)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_streaming_download_is_bounded_even_without_content_length(self) -> None:
        response = _ImageResponse(
            _RED_PNG + (b"x" * 4096),
            content_length=False,
        )
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pexels, "_cache_dir", return_value=tmp), \
             patch.object(pexels, "_MAX_IMAGE_DOWNLOAD_BYTES", 128, create=True), \
             patch.object(pexels.urllib.request, "urlopen", return_value=response):
            result = pexels._download_image(
                "https://images.pexels.com/photos/101/image.png",
                "story",
                candidate_identity="pexels:id:101",
            )

        self.assertIsNone(result)
        self.assertTrue(response.read_sizes)
        self.assertTrue(all(size > 0 for size in response.read_sizes))
        self.assertLessEqual(len(response.read_sizes), 3)

    def test_atomic_replace_failure_leaves_no_final_or_partial_file(self) -> None:
        response = _ImageResponse(_RED_PNG)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pexels, "_cache_dir", return_value=tmp), \
             patch.object(pexels.urllib.request, "urlopen", return_value=response), \
             patch.object(pexels.os, "replace", side_effect=OSError("replace failed")) as replace:
            result = pexels._download_image(
                "https://images.pexels.com/photos/101/image.png",
                "story",
                candidate_identity="pexels:id:101",
            )

            self.assertIsNone(result)
            replace.assert_called_once()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_missing_pillow_fails_closed_and_cleans_temporary_file(self) -> None:
        response = _ImageResponse(_RED_PNG + (b"\0" * 1200))
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pexels, "_cache_dir", return_value=tmp), \
             patch.object(pexels.urllib.request, "urlopen", return_value=response), \
             patch.dict(sys.modules, {"PIL": None}):
            result = pexels._download_image(
                "https://images.pexels.com/photos/101/image.png",
                "story",
                candidate_identity="pexels:id:101",
            )

            self.assertIsNone(result)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class CanonicalImageIdentityTests(unittest.TestCase):
    def test_provider_id_is_stable_across_transformed_urls_and_provider_aware(self) -> None:
        first = image_state.canonical_image_identity("unsplash", {
            "id": "rxLGSOM0e3U",
            "url_regular": "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b?w=1080&q=80",
        })
        second = image_state.canonical_image_identity("UNSPLASH", {
            "id": "rxLGSOM0e3U",
            "url_full": "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b?crop=entropy&fm=webp&w=400",
        })

        self.assertEqual(first, "unsplash:id:rxLGSOM0e3U")
        self.assertEqual(second, first)
        self.assertNotEqual(
            image_state.canonical_image_identity("pexels", "rxLGSOM0e3U"),
            first,
        )

    def test_provider_page_urls_recover_same_ids_when_frontmatter_id_is_absent(self) -> None:
        self.assertEqual(
            image_state.canonical_image_identity(
                "unsplash",
                source_url=(
                    "https://unsplash.com/photos/brown-wooden-fence-filled-with-snow-during-winter-"
                    "rxLGSOM0e3U?utm_source=uutistenlukija"
                ),
            ),
            "unsplash:id:rxLGSOM0e3U",
        )
        self.assertEqual(
            image_state.canonical_image_identity(
                "pexels",
                source_url="https://www.pexels.com/photo/coins-on-documents-12932891/?auto=compress",
            ),
            "pexels:id:12932891",
        )
        self.assertEqual(
            image_state.canonical_image_identity(
                "pexels",
                image_url="https://images.pexels.com/photos/12932891/pexels-photo-12932891.jpeg?w=1200",
            ),
            "pexels:id:12932891",
        )

    def test_transformed_full_and_thumb_urls_have_one_asset_identity(self) -> None:
        self.assertEqual(
            image_state.canonical_image_identity(
                "unsplash",
                {
                    "url": (
                        "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                        "?crop=entropy&fm=jpg&w=1080"
                    )
                },
            ),
            image_state.canonical_image_identity(
                "unsplash",
                {
                    "url_thumb": (
                        "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                        "?fit=crop&fm=webp&w=400"
                    )
                },
            ),
        )
        self.assertEqual(
            image_state.canonical_image_identity(
                "pexels",
                {
                    "url": (
                        "https://images.pexels.com/photos/12932891/"
                        "pexels-photo-12932891.jpeg?w=1920"
                    )
                },
            ),
            image_state.canonical_image_identity(
                "pexels",
                {
                    "thumb_url": (
                        "https://images.pexels.com/photos/12932891/"
                        "pexels-photo-12932891.jpeg?h=350"
                    )
                },
            ),
        )

    def test_unsplash_id_candidate_exposes_legacy_cdn_asset_alias(self) -> None:
        candidate = {
            "id": "rxLGSOM0e3U",
            "photo_page": "https://unsplash.com/photos/snowy-fence-rxLGSOM0e3U",
            "url_regular": (
                "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                "?crop=entropy&fm=jpg&w=1080"
            ),
            "url_thumb": (
                "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                "?fit=crop&fm=webp&w=400"
            ),
        }

        self.assertEqual(
            image_state.image_identity_aliases("unsplash", candidate),
            frozenset({
                "unsplash:id:rxLGSOM0e3U",
                "unsplash:asset:photo-1511803471753-da23b1a92d4b",
            }),
        )
        self.assertEqual(
            image_state.canonical_image_identity("unsplash", candidate),
            "unsplash:id:rxLGSOM0e3U",
        )

    def test_recent_post_index_records_stock_aliases_and_skips_old_or_fallback(self) -> None:
        reference = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            posts = Path(tmp)
            self._write_post(
                posts / "2026-09-02-recent.md",
                date=reference,
                source="unsplash",
                candidate_id="rxLGSOM0e3U",
                image="https://images.unsplash.com/photo-1511803471753-da23b1a92d4b?w=1080",
                thumb="https://images.unsplash.com/photo-1511803471753-da23b1a92d4b?w=400",
            )
            self._write_post(
                posts / "2026-09-01-pexels.md",
                date=reference - timedelta(days=1),
                source="pexels",
                source_url="https://www.pexels.com/photo/coins-on-documents-12932891/",
                image="/images/articles/one-hero.jpg",
                thumb="/images/articles/one-thumb.jpg",
            )
            self._write_post(
                posts / "2026-07-01-old.md",
                date=reference - timedelta(days=63),
                source="unsplash",
                candidate_id="old-candidate",
            )
            self._write_post(
                posts / "2026-09-02-fallback.md",
                date=reference,
                source="category_fallback",
                candidate_id="fallback-candidate",
                category_fallback=True,
            )

            identities = image_state.recent_tracked_image_identities(
                posts,
                now=reference,
                window_days=30,
            )

        self.assertEqual(
            identities,
            {
                "unsplash:id:rxLGSOM0e3U",
                "unsplash:asset:photo-1511803471753-da23b1a92d4b",
                "pexels:id:12932891",
            },
        )

    def test_legacy_url_only_recent_post_blocks_id_bearing_candidate(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            posts = root / "posts"
            posts.mkdir()
            self._write_post(
                posts / f"{now.date().isoformat()}-legacy.md",
                date=now,
                source="unsplash",
                image="/images/articles/legacy-hero.jpg",
                thumb=(
                    "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                    "?fit=crop&fm=jpg&w=400"
                ),
            )
            state_file = root / "cache" / "used_images.json"

            with patch.object(image_state, "POSTS_DIR", posts), \
                 patch.object(image_state, "_STATE_FILE", str(state_file)), \
                 patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                 patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                 patch.object(image_state, "_PROCESS_USED_ALIASES", set()):
                identity = image_state.canonical_image_identity("unsplash", {
                    "id": "rxLGSOM0e3U",
                    "url_regular": (
                        "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                        "?w=1200&q=80"
                    ),
                })

                self.assertEqual(identity, "unsplash:id:rxLGSOM0e3U")
                self.assertTrue(image_state.is_image_used(identity))

    def test_corrupt_or_unreadable_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            posts = root / "posts"
            posts.mkdir()
            state_file = root / "used_images.json"

            for corrupt_state in ("{not-json", "[]", '{"used_ids": []}'):
                with self.subTest(state=corrupt_state):
                    state_file.write_text(corrupt_state, encoding="utf-8")
                    with patch.object(image_state, "POSTS_DIR", posts), \
                         patch.object(image_state, "_STATE_FILE", str(state_file)), \
                         patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                         patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                         patch.object(image_state, "_PROCESS_USED_ALIASES", set()):
                        self.assertTrue(
                            image_state.is_image_used("unsplash:id:unseen-candidate")
                        )

            state_file.write_text(
                json.dumps({"used_ids": {}, "query_indices": {}}),
                encoding="utf-8",
            )
            with patch.object(image_state, "POSTS_DIR", posts), \
                 patch.object(image_state, "_STATE_FILE", str(state_file)), \
                 patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                 patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                 patch.object(image_state, "_PROCESS_USED_ALIASES", set()), \
                 patch("builtins.open", side_effect=PermissionError("denied")):
                self.assertTrue(
                    image_state.is_image_used("unsplash:id:unseen-candidate")
                )

    def test_missing_or_malformed_recent_post_index_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_file = root / "used_images.json"
            state_file.write_text(
                json.dumps({"used_ids": {}, "query_indices": {}}),
                encoding="utf-8",
            )
            cases = (root / "missing-posts", root / "posts")
            (root / "posts").mkdir()
            (root / "posts" / f"{datetime.now(timezone.utc).date()}-broken.md").write_text(
                "not front matter\n",
                encoding="utf-8",
            )

            for posts in cases:
                with self.subTest(posts=posts), patch.object(image_state, "POSTS_DIR", posts), \
                     patch.object(image_state, "_STATE_FILE", str(state_file)), \
                     patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                     patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                     patch.object(image_state, "_PROCESS_USED_ALIASES", set()):
                    self.assertTrue(
                        image_state.is_image_used("unsplash:id:unseen-candidate")
                    )

    def test_partially_malformed_recent_provenance_invalidates_index(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            posts = root / "posts"
            posts.mkdir()
            (posts / f"{now.date().isoformat()}-partial.md").write_text(
                "\n".join((
                    "---",
                    'title: "Plausible recent post"',
                    f"date: {now.isoformat()}",
                    "  image_source: unsplash",
                    "  image_candidate_id: hidden-by-indentation",
                    "---",
                    "Body",
                    "",
                )),
                encoding="utf-8",
            )
            state_file = root / "used_images.json"
            state_file.write_text(
                json.dumps({"used_ids": {}, "query_indices": {}}),
                encoding="utf-8",
            )

            with patch.object(image_state, "POSTS_DIR", posts), \
                 patch.object(image_state, "_STATE_FILE", str(state_file)), \
                 patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                 patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                 patch.object(image_state, "_PROCESS_USED_ALIASES", set()):
                self.assertTrue(
                    image_state.is_image_used("unsplash:id:unseen-candidate")
                )

    def test_atomic_write_failure_preserves_file_and_process_local_alias_mark(self) -> None:
        initial_state = {
            "used_ids": {"pexels:id:existing": "2026-09-01T00:00:00+00:00"},
            "query_indices": {"existing query": 2},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            posts = root / "posts"
            posts.mkdir()
            cache = root / "cache"
            cache.mkdir()
            state_file = cache / "used_images.json"
            state_file.write_text(json.dumps(initial_state), encoding="utf-8")

            with patch.object(image_state, "POSTS_DIR", posts), \
                 patch.object(image_state, "_STATE_FILE", str(state_file)), \
                 patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                 patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                 patch.object(image_state, "_PROCESS_USED_ALIASES", set()), \
                 patch.object(
                     image_state.os,
                     "replace",
                     side_effect=OSError("simulated replace failure"),
                 ) as replace, \
                 patch("builtins.print"):
                identity = image_state.canonical_image_identity("unsplash", {
                    "id": "rxLGSOM0e3U",
                    "url_regular": (
                        "https://images.unsplash.com/photo-1511803471753-da23b1a92d4b"
                        "?w=1080"
                    ),
                })
                image_state.mark_image_used(identity)

                replace.assert_called_once()
                self.assertTrue(image_state.is_image_used(identity))
                self.assertTrue(
                    image_state.is_image_used(
                        "unsplash:asset:photo-1511803471753-da23b1a92d4b"
                    )
                )
                self.assertEqual(
                    json.loads(state_file.read_text(encoding="utf-8")),
                    initial_state,
                )
                self.assertEqual(list(cache.glob(".used_images.json.*.tmp")), [])

    def test_fresh_checkout_uses_recent_posts_and_runtime_state(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            posts = root / "posts"
            posts.mkdir()
            self._write_post(
                posts / f"{now.date().isoformat()}-recent.md",
                date=now,
                source="unsplash",
                candidate_id="tracked",
            )
            state_file = root / "cache" / "used_images.json"

            with patch.object(image_state, "POSTS_DIR", posts), \
                 patch.object(image_state, "_STATE_FILE", str(state_file)), \
                 patch.object(image_state, "_RECENT_INDEX_CACHE", None), \
                 patch.object(image_state, "_IDENTITY_ALIAS_CACHE", {}), \
                 patch.object(image_state, "_PROCESS_USED_ALIASES", set()):
                self.assertTrue(image_state.is_image_used("unsplash:id:tracked"))
                self.assertFalse(image_state.is_image_used("pexels:id:tracked"))

                image_state.mark_image_used("pexels:id:runtime")
                self.assertTrue(image_state.is_image_used("pexels:id:runtime"))
                self.assertFalse(image_state.is_image_used("unsplash:id:runtime"))

    @staticmethod
    def _write_post(
        path: Path,
        *,
        date: datetime,
        source: str,
        candidate_id: str = "",
        source_url: str = "",
        image: str = "",
        thumb: str = "",
        category_fallback: bool = False,
    ) -> None:
        lines = [
            "---",
            'title: "Fixture"',
            f"date: {date.isoformat()}",
            f'image_source: "{source}"',
        ]
        if candidate_id:
            lines.append(f'image_candidate_id: "{candidate_id}"')
        if source_url:
            lines.append(f'image_source_url: "{source_url}"')
        if image:
            lines.append(f'image: "{image}"')
        if thumb:
            lines.append(f'image_thumb: "{thumb}"')
        lines.extend([
            f"image_category_fallback: {'true' if category_fallback else 'false'}",
            "---",
            "Fixture body.",
        ])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ProviderCanonicalDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = _Brief()
        self.stock_queries = [("grounded query", "grounded concept", self.brief)]

    def test_unsplash_filters_and_marks_canonical_identity_with_truthful_counts(self) -> None:
        duplicate = self._unsplash_candidate("duplicate")
        selected = self._unsplash_candidate("selected")
        photos = search_photos(
            [duplicate, selected],
            provider="unsplash",
            attempted=True,
            succeeded=True,
            outcome="search_succeeded",
            reason="response_received",
        )

        with patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(image_query, "generate_image_query", return_value="grounded query"), \
             patch.object(image_candidate_guard, "build_stock_queries", return_value=self.stock_queries) as build_queries, \
             patch.object(image_candidate_guard, "filter_image_candidates", side_effect=_accept_all) as filter_candidates, \
             patch.object(unsplash, "_search", return_value=photos), \
             patch.object(unsplash, "_trigger_download", return_value=(True, True)) as trigger_download, \
             patch.object(image_state, "is_image_used", side_effect=lambda identity: identity.endswith(":duplicate")) as used, \
             patch.object(image_state, "mark_image_used") as marked, \
             patch.object(image_state, "get_query_index", return_value=0), \
             patch.object(image_state, "set_query_index"), \
             patch.object(unsplash.time, "sleep"):
            result, receipt = unsplash.fetch_image_for_article(
                "Grounded article",
                "Talous",
                source_evidence="source dossier",
                inter_request_delay=0,
                return_result=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["url"], selected["url_regular"])
        self.assertEqual(
            used.call_args_list,
            [
                call("unsplash:id:duplicate"),
                call("unsplash:asset:photo-duplicate"),
                call("unsplash:id:selected"),
                call("unsplash:asset:photo-selected"),
            ],
        )
        self.assertEqual(
            marked.call_args_list,
            [
                call("unsplash:id:selected"),
                call("unsplash:asset:photo-selected"),
            ],
        )
        trigger_download.assert_called_once()
        self.assertEqual(receipt["candidate_count"], 2)
        self.assertEqual(receipt["fresh_candidate_count"], 1)
        self.assertEqual(receipt["rejected_count"], 0)
        self.assertEqual(receipt["accepted_count"], 1)
        self.assertTrue(receipt["semantic_accepted"])
        self.assertTrue(receipt["attribution_complete"])
        self.assertEqual(receipt["delivery_mode"], "hotlink")
        self.assertTrue(receipt["delivery_succeeded"])
        self.assertTrue(receipt["thumbnail_delivery_succeeded"])
        self.assertTrue(receipt["tracking_attempted"])
        self.assertTrue(receipt["tracking_succeeded"])
        self.assertEqual(build_queries.call_args.kwargs["source_evidence"], "source dossier")
        self.assertEqual(filter_candidates.call_args.kwargs["source_evidence"], "source dossier")
        self.assertEqual(filter_candidates.call_args.kwargs["category"], "Talous")

    def test_unsplash_cdn_alias_alone_blocks_id_bearing_candidate(self) -> None:
        candidate = self._unsplash_candidate("rxLGSOM0e3U")
        photos = search_photos(
            [candidate],
            provider="unsplash",
            attempted=True,
            succeeded=True,
            outcome="search_succeeded",
            reason="response_received",
        )

        with patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(image_query, "generate_image_query", return_value="grounded query"), \
             patch.object(image_candidate_guard, "build_stock_queries", return_value=self.stock_queries), \
             patch.object(image_candidate_guard, "filter_image_candidates", side_effect=_accept_all), \
             patch.object(unsplash, "_search", return_value=photos), \
             patch.object(unsplash, "_trigger_download") as trigger_download, \
             patch.object(
                 image_state,
                 "is_image_used",
                 side_effect=lambda identity: ":asset:" in identity,
             ) as used, \
             patch.object(image_state, "mark_image_used") as marked:
            result, receipt = unsplash.fetch_image_for_article(
                "Grounded article",
                "Other",
                source_evidence="source dossier",
                inter_request_delay=0,
                return_result=True,
            )

        self.assertIsNone(result)
        self.assertEqual(
            used.call_args_list,
            [
                call("unsplash:id:rxLGSOM0e3U"),
                call("unsplash:asset:photo-rxLGSOM0e3U"),
            ],
        )
        marked.assert_not_called()
        trigger_download.assert_not_called()
        self.assertEqual(receipt["outcome"], "no_fresh_candidates")
        self.assertEqual(receipt["candidate_count"], 1)
        self.assertEqual(receipt["fresh_candidate_count"], 0)
        self.assertEqual(receipt["accepted_count"], 0)

    def test_missing_duplicate_guard_is_provider_fault_for_both_providers(self) -> None:
        for module, key_name, search_name in (
            (unsplash, "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "PEXELS_API_KEY", "_search_pexels"),
        ):
            with self.subTest(provider=module.__name__), \
                 patch.object(module, key_name, "key"), \
                 patch.object(image_query, "generate_image_query", return_value="grounded query"), \
                 patch.object(module, "_load_image_pipeline_guards", return_value=None), \
                 patch.object(module, search_name) as search:
                kwargs = {"inter_request_delay": 0, "return_result": True}
                if module is pexels:
                    kwargs["download"] = False
                result, receipt = module.fetch_image_for_article(
                    "Grounded article",
                    "Talous",
                    **kwargs,
                )

            self.assertIsNone(result)
            search.assert_not_called()
            self.assertEqual(receipt["outcome"], "provider_fault")
            self.assertEqual(receipt["reason"], "duplicate_guard_unavailable")
            self.assertEqual(receipt["fault_count"], 1)
            self.assertEqual(receipt["accepted_count"], 0)

    def test_duplicate_guard_runtime_failure_is_provider_fault(self) -> None:
        cases = (
            (unsplash, "UNSPLASH_ACCESS_KEY", "_search", self._unsplash_candidate("one")),
            (pexels, "PEXELS_API_KEY", "_search_pexels", self._pexels_candidate(101)),
        )
        for module, key_name, search_name, candidate in cases:
            provider = module.__name__.rsplit(".", 1)[-1]
            photos = search_photos(
                [candidate],
                provider=provider,
                attempted=True,
                succeeded=True,
                outcome="search_succeeded",
                reason="response_received",
            )
            with self.subTest(provider=provider), \
                 patch.object(module, key_name, "key"), \
                 patch.object(image_query, "generate_image_query", return_value="grounded query"), \
                 patch.object(image_candidate_guard, "build_stock_queries", return_value=self.stock_queries), \
                 patch.object(image_candidate_guard, "filter_image_candidates") as filter_candidates, \
                 patch.object(module, search_name, return_value=photos), \
                 patch.object(image_state, "is_image_used", side_effect=OSError("state unavailable")):
                kwargs = {"inter_request_delay": 0, "return_result": True}
                if module is pexels:
                    kwargs["download"] = False
                result, receipt = module.fetch_image_for_article(
                    "Grounded article",
                    "Other",
                    **kwargs,
                )

            self.assertIsNone(result)
            filter_candidates.assert_not_called()
            self.assertEqual(receipt["outcome"], "provider_fault")
            self.assertEqual(receipt["reason"], "duplicate_guard_check_failed")
            self.assertEqual(receipt["fault_count"], 1)
            self.assertEqual(receipt["accepted_count"], 0)

    def test_pexels_marks_selected_candidate_once_for_hero_and_thumb(self) -> None:
        duplicate = self._pexels_candidate(101)
        selected = self._pexels_candidate(202)
        photos = search_photos(
            [duplicate, selected],
            provider="pexels",
            attempted=True,
            succeeded=True,
            outcome="search_succeeded",
            reason="response_received",
        )

        with patch.object(pexels, "PEXELS_API_KEY", "key"), \
             patch.object(image_query, "generate_image_query", return_value="grounded query"), \
             patch.object(image_candidate_guard, "build_stock_queries", return_value=self.stock_queries) as build_queries, \
             patch.object(image_candidate_guard, "filter_image_candidates", side_effect=_accept_all) as filter_candidates, \
             patch.object(pexels, "_search_pexels", return_value=photos), \
             patch.object(image_state, "is_image_used", side_effect=lambda identity: identity.endswith(":101")) as used, \
             patch.object(image_state, "mark_image_used") as marked, \
             patch.object(image_state, "get_query_index", return_value=0), \
             patch.object(image_state, "set_query_index"), \
             patch.object(
                 pexels,
                 "_download_image",
                 side_effect=["/images/articles/story-hero.jpg", "/images/articles/story-thumb.jpg"],
             ) as download, \
             patch.object(pexels.time, "sleep"):
            result, receipt = pexels.fetch_image_for_article(
                "Grounded article",
                "Talous",
                source_evidence="source dossier",
                slug="story",
                inter_request_delay=0,
                return_result=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["local_path"], "/images/articles/story-hero.jpg")
        self.assertEqual(result["thumb_path"], "/images/articles/story-thumb.jpg")
        self.assertEqual(
            used.call_args_list,
            [call("pexels:id:101"), call("pexels:id:202")],
        )
        marked.assert_called_once_with("pexels:id:202")
        self.assertEqual(download.call_count, 2)
        self.assertEqual(receipt["candidate_count"], 2)
        self.assertEqual(receipt["fresh_candidate_count"], 1)
        self.assertEqual(receipt["rejected_count"], 0)
        self.assertEqual(receipt["accepted_count"], 1)
        self.assertTrue(receipt["semantic_accepted"])
        self.assertTrue(receipt["attribution_complete"])
        self.assertEqual(receipt["delivery_mode"], "download")
        self.assertTrue(receipt["delivery_attempted"])
        self.assertTrue(receipt["delivery_succeeded"])
        self.assertTrue(receipt["thumbnail_delivery_succeeded"])
        self.assertFalse(receipt["tracking_attempted"])
        self.assertEqual(build_queries.call_args.kwargs["source_evidence"], "source dossier")
        self.assertEqual(filter_candidates.call_args.kwargs["source_evidence"], "source dossier")
        self.assertEqual(filter_candidates.call_args.kwargs["category"], "Talous")

    def test_pexels_uses_hero_when_thumbnail_download_fails(self) -> None:
        selected = self._pexels_candidate(202)
        photos = search_photos(
            [selected],
            provider="pexels",
            attempted=True,
            succeeded=True,
            outcome="search_succeeded",
            reason="response_received",
        )

        with patch.object(pexels, "PEXELS_API_KEY", "key"), \
             patch.object(image_query, "generate_image_query", return_value="grounded query"), \
             patch.object(image_candidate_guard, "build_stock_queries", return_value=self.stock_queries), \
             patch.object(image_candidate_guard, "filter_image_candidates", side_effect=_accept_all), \
             patch.object(pexels, "_search_pexels", return_value=photos), \
             patch.object(image_state, "is_image_used", return_value=False), \
             patch.object(image_state, "mark_image_used") as marked, \
             patch.object(image_state, "get_query_index", return_value=0), \
             patch.object(image_state, "set_query_index"), \
             patch.object(
                 pexels,
                 "_download_image",
                 side_effect=["/images/articles/story-hero.jpg", None],
             ), \
             patch.object(pexels.time, "sleep"):
            result, receipt = pexels.fetch_image_for_article(
                "Grounded article",
                "Talous",
                slug="story",
                inter_request_delay=0,
                return_result=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["local_path"], "/images/articles/story-hero.jpg")
        self.assertEqual(result["thumb_path"], "/images/articles/story-hero.jpg")
        marked.assert_called_once_with("pexels:id:202")
        self.assertEqual(receipt["outcome"], "accepted")
        self.assertEqual(receipt["accepted_count"], 1)
        self.assertTrue(receipt["delivery_succeeded"])
        self.assertTrue(receipt["thumbnail_delivery_succeeded"])

    def test_batch_wrappers_forward_article_source_evidence(self) -> None:
        for module in (unsplash, pexels):
            provider = module.__name__.rsplit(".", 1)[-1]
            provider_result = build_provider_result(
                provider=provider,
                attempted=False,
                succeeded=False,
                outcome="empty_search",
                reason="no_grounded_stock_queries",
            )
            article = {
                "title": "Grounded article",
                "category": "Talous",
                "summary": "Summary",
                "key_points": ["verified point"],
                "tags": ["hallucinated railway"],
                "content": "Article body",
                "source_text": "primary source evidence",
                "research": "secondary research evidence",
            }
            with self.subTest(provider=provider), \
                 patch.object(
                     module,
                     "fetch_image_for_article",
                     return_value=(None, provider_result),
                 ) as fetch, \
                 patch.object(
                     image_candidate_guard,
                     "category_fallback_fields",
                     return_value={"image_category_fallback": True},
                 ):
                module.fetch_images_for_articles([article], delay=0)

            self.assertEqual(
                fetch.call_args.kwargs["source_evidence"],
                "primary source evidence",
            )
            self.assertEqual(fetch.call_args.kwargs["key_points"], ["verified point"])

    def test_empty_grounded_query_plan_skips_provider_and_category_fallback(self) -> None:
        for module, key_name, search_name in (
            (unsplash, "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "PEXELS_API_KEY", "_search_pexels"),
        ):
            with self.subTest(provider=module.__name__), \
                 patch.object(module, key_name, "key"), \
                 patch.object(image_query, "generate_image_query", return_value="unsupported query"), \
                 patch.object(image_candidate_guard, "build_stock_queries", return_value=[]), \
                 patch.object(module, search_name) as search:
                kwargs = {"inter_request_delay": 0, "return_result": True}
                if module is pexels:
                    kwargs["download"] = False
                result, receipt = module.fetch_image_for_article(
                    "Sensitive ambiguous article",
                    "Ulkomaat",
                    **kwargs,
                )

            self.assertIsNone(result)
            search.assert_not_called()
            self.assertFalse(receipt["attempted"])
            self.assertFalse(receipt["succeeded"])
            self.assertEqual(receipt["outcome"], "empty_search")
            self.assertEqual(receipt["reason"], "no_grounded_stock_queries")
            self.assertEqual(receipt["query_count"], 0)
            self.assertEqual(receipt["candidate_count"], 0)
            self.assertEqual(receipt["fresh_candidate_count"], 0)
            self.assertEqual(receipt["accepted_count"], 0)

    @staticmethod
    def _unsplash_candidate(candidate_id: str) -> dict[str, object]:
        return {
            "id": candidate_id,
            "url_regular": f"https://images.unsplash.com/photo-{candidate_id}?w=1080",
            "url_full": f"https://images.unsplash.com/photo-{candidate_id}?w=2400",
            "url_small": f"https://images.unsplash.com/photo-{candidate_id}?w=400",
            "url_thumb": f"https://images.unsplash.com/photo-{candidate_id}?w=200",
            "download_location": f"https://api.unsplash.com/photos/{candidate_id}/download",
            "photographer": "Test Photographer",
            "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
            "photo_page": (
                f"https://unsplash.com/photos/{candidate_id}"
                "?utm_source=uutistenlukija&utm_medium=referral"
            ),
            "alt": "grounded test subject",
        }

    @staticmethod
    def _pexels_candidate(candidate_id: int) -> dict[str, object]:
        return {
            "id": candidate_id,
            "url": f"https://images.pexels.com/photos/{candidate_id}/photo.jpeg?w=1200",
            "thumb_url": f"https://images.pexels.com/photos/{candidate_id}/photo.jpeg?w=400",
            "photographer": "Test Photographer",
            "photographer_url": "https://www.pexels.com/@test",
            "pexels_url": f"https://www.pexels.com/photo/grounded-subject-{candidate_id}/",
            "alt": "grounded test subject",
        }


if __name__ == "__main__":
    unittest.main()
