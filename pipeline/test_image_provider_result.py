#!/usr/bin/env python3
from __future__ import annotations

import unittest
import json
from unittest.mock import patch

try:
    from . import pexels, unsplash
    from .image_provider_result import (
        IMAGE_PROVIDER_RESULT_SCHEMA,
        MAX_PROVIDER_COUNT,
        build_provider_result,
        search_photos,
    )
except ImportError:  # pragma: no cover - direct pipeline execution
    import pexels
    import unsplash
    from image_provider_result import (
        IMAGE_PROVIDER_RESULT_SCHEMA,
        MAX_PROVIDER_COUNT,
        build_provider_result,
        search_photos,
    )


class ImageProviderResultTests(unittest.TestCase):
    def test_provider_normalization_never_substitutes_query_for_missing_caption(self) -> None:
        class Response:
            headers = {"X-Ratelimit-Remaining": "100", "X-Ratelimit-Reset": "0"}

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        fixtures = (
            (
                unsplash, "UNSPLASH_ACCESS_KEY", "_search", "captionless-unsplash|30",
                {
                    "results": [{
                        "id": "one", "alt_description": None,
                        "urls": {"regular": "https://images.example/one.jpg"},
                        "links": {"html": "https://example.test/one"},
                        "user": {"name": "Test", "links": {"html": "https://example.test/user"}},
                    }],
                },
                "captionless-unsplash",
            ),
            (
                pexels, "PEXELS_API_KEY", "_search_pexels", "captionless-pexels|80",
                {
                    "photos": [{
                        "id": 1, "alt": None,
                        "src": {"large": "https://images.example/one.jpg"},
                        "url": "https://example.test/one",
                    }],
                },
                "captionless-pexels",
            ),
        )
        for module, key_name, search_name, cache_key, payload, query in fixtures:
            module._query_cache.pop(cache_key, None)
            try:
                with self.subTest(provider=module.__name__), patch.object(module, key_name, "key"), \
                     patch.object(module.urllib.request, "urlopen", return_value=Response(payload)):
                    photos = getattr(module, search_name)(query)
                self.assertEqual(photos[0]["alt"], "")
                self.assertNotEqual(photos[0]["alt"], query)
                self.assertTrue(photos.provider_result["attempted"])
                self.assertTrue(photos.provider_result["succeeded"])
            finally:
                module._query_cache.pop(cache_key, None)

    def test_receipt_is_bounded_and_contains_no_query_or_url(self) -> None:
        result = build_provider_result(
            provider="UNSPLASH",
            attempted=True,
            succeeded=True,
            outcome="accepted",
            reason="candidate_accepted",
            query_count=MAX_PROVIDER_COUNT + 1,
            candidate_count=MAX_PROVIDER_COUNT + 2,
            fresh_candidate_count=-1,
            accepted_count=1,
        )

        self.assertEqual(result["schema"], IMAGE_PROVIDER_RESULT_SCHEMA)
        self.assertEqual(result["provider"], "unsplash")
        self.assertEqual(result["query_count"], MAX_PROVIDER_COUNT)
        self.assertEqual(result["candidate_count"], MAX_PROVIDER_COUNT)
        self.assertEqual(result["fresh_candidate_count"], 0)
        self.assertFalse(any("query" in key and key != "query_count" for key in result))
        self.assertFalse(any("url" in key for key in result))

    def test_each_provider_reports_missing_key_without_attempt(self) -> None:
        for module, provider, key_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY"),
            (pexels, "pexels", "PEXELS_API_KEY"),
        ):
            with self.subTest(provider=provider), patch.object(module, key_name, ""):
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, result = module.fetch_image_for_article("Testi", "Kotimaa", **kwargs)
                self.assertIsNone(image)
                self.assertEqual(result["outcome"], "no_key")
                self.assertFalse(result["attempted"])
                self.assertFalse(result["succeeded"])

    def test_each_provider_cache_hit_does_not_claim_request_attempt(self) -> None:
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            query = f"cache-{provider}"
            cache_key = f"{query}|{30 if provider == 'unsplash' else 80}"
            module._query_cache[cache_key] = [{"id": 1}]
            try:
                with self.subTest(provider=provider), patch.object(module, key_name, "key"):
                    photos = getattr(module, search_name)(query)
                receipt = photos.provider_result
                self.assertEqual(receipt["outcome"], "cache_hit")
                self.assertFalse(receipt["attempted"])
                self.assertTrue(receipt["succeeded"])
                self.assertEqual(receipt["candidate_count"], 1)
            finally:
                module._query_cache.pop(cache_key, None)

    def test_each_provider_rejects_candidates_from_adapter_without_receipt(self) -> None:
        candidates = {
            "unsplash": {
                "id": "sunny",
                "alt": "sunny blue sky over green field",
                "url_regular": "https://images.example/sunny.jpg",
                "url_full": "https://images.example/sunny-full.jpg",
                "url_small": "https://images.example/sunny-small.jpg",
                "url_thumb": "https://images.example/sunny-thumb.jpg",
                "photographer": "Test",
                "photographer_url": "https://example.test/photographer",
                "photo_page": "https://example.test/sunny",
            },
            "pexels": {
                "id": 2,
                "alt": "sunny blue sky over green field",
                "url": "https://images.example/sunny.jpg",
                "thumb_url": "https://images.example/sunny-thumb.jpg",
                "photographer": "Test",
                "photographer_url": "https://example.test/photographer",
                "pexels_url": "https://example.test/sunny",
            },
        }
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            with self.subTest(provider=provider), patch.object(module, key_name, "key"), \
                 patch.object(module, search_name, return_value=[candidates[provider]]), \
                 patch("image_query.generate_image_query", return_value="sunny weather Finland"):
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, result = module.fetch_image_for_article(
                    "Loppuviikon sää on aurinkoinen", "Kotimaa",
                    summary="Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä.",
                    **kwargs,
                )
            self.assertIsNone(image)
            self.assertEqual(result["outcome"], "provider_fault")
            self.assertEqual(result["reason"], "provider_request_failed")
            self.assertFalse(result["attempted"])
            self.assertFalse(result["succeeded"])
            self.assertGreater(result["fault_count"], 0)

    def test_each_provider_distinguishes_fault_from_valid_empty_search(self) -> None:
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            for succeeded, outcome in ((False, "provider_fault"), (True, "empty_search")):
                photos = search_photos(
                    [],
                    provider=provider,
                    attempted=True,
                    succeeded=succeeded,
                    outcome="search_succeeded" if succeeded else "provider_fault",
                    reason="response_received" if succeeded else "request_exception",
                    fault_count=0 if succeeded else 1,
                )
                with self.subTest(provider=provider, outcome=outcome), \
                     patch.object(module, key_name, "key"), \
                     patch.object(module, search_name, return_value=photos), \
                     patch("image_query.generate_image_query", return_value="public opinion survey ballot"):
                    kwargs = {"return_result": True, "inter_request_delay": 0}
                    if provider == "pexels":
                        kwargs["download"] = False
                    image, result = module.fetch_image_for_article(
                        "Kysely hallituksen kannatuksesta",
                        "Kotimaa",
                        content="Kansalaisilta kysyttiin hallituksen kannatusta.",
                        **kwargs,
                    )
                self.assertIsNone(image)
                self.assertEqual(result["outcome"], outcome)
                self.assertTrue(result["attempted"])
                self.assertEqual(result["succeeded"], succeeded)

    def test_each_provider_reports_policy_rejection_separately(self) -> None:
        title = "Akselin veneenkorjaus lähti kesätyön puutteesta"
        content = "Nuori korjaa soutuveneitä ja moottoriveneitä kotipihalla."
        for module, provider, key_name, search_name, candidate in (
            (
                unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search",
                {
                    "id": "tower",
                    "alt": "modern glass skyscrapers and business district",
                    "url_regular": "https://images.example/tower.jpg",
                    "url_full": "https://images.example/tower-full.jpg",
                    "url_small": "https://images.example/tower-small.jpg",
                    "url_thumb": "https://images.example/tower-thumb.jpg",
                    "photographer": "Test",
                    "photographer_url": "https://example.test/photographer",
                    "photo_page": "https://example.test/tower",
                },
            ),
            (
                pexels, "pexels", "PEXELS_API_KEY", "_search_pexels",
                {
                    "id": 1,
                    "alt": "modern glass skyscrapers and business district",
                    "url": "https://images.example/tower.jpg",
                    "thumb_url": "https://images.example/tower-thumb.jpg",
                    "photographer": "Test",
                    "photographer_url": "https://example.test/photographer",
                    "pexels_url": "https://example.test/tower",
                },
            ),
        ):
            photos = search_photos(
                [candidate], provider=provider, attempted=True, succeeded=True,
                outcome="search_succeeded", reason="response_received",
            )
            with self.subTest(provider=provider), patch.object(module, key_name, "key"), \
                 patch.object(module, search_name, return_value=photos), \
                 patch("image_query.generate_image_query", return_value="business entrepreneur"), \
                 patch("image_state.is_image_used", return_value=False):
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, result = module.fetch_image_for_article(
                    title, "Talous", content=content, **kwargs,
                )
            self.assertIsNone(image)
            self.assertEqual(result["outcome"], "all_policy_rejected")
            self.assertTrue(result["attempted"])
            self.assertTrue(result["succeeded"])
            self.assertGreater(result["rejected_count"], 0)
            self.assertEqual(result["accepted_count"], 0)

    def test_each_provider_reports_accepted_candidate(self) -> None:
        title = "Loppuviikon sää on aurinkoinen"
        summary = "Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä."
        candidates = {
            "unsplash": {
                "id": "sunny",
                "alt": "sunny blue sky over green field",
                "url_regular": "https://images.example/sunny.jpg",
                "url_full": "https://images.example/sunny-full.jpg",
                "url_small": "https://images.example/sunny-small.jpg",
                "url_thumb": "https://images.example/sunny-thumb.jpg",
                "photographer": "Test",
                "photographer_url": "https://example.test/photographer",
                "photo_page": "https://example.test/sunny",
            },
            "pexels": {
                "id": 2,
                "alt": "sunny blue sky over green field",
                "url": "https://images.example/sunny.jpg",
                "thumb_url": "https://images.example/sunny-thumb.jpg",
                "photographer": "Test",
                "photographer_url": "https://example.test/photographer",
                "pexels_url": "https://example.test/sunny",
            },
        }
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            photos = search_photos(
                [candidates[provider]], provider=provider, attempted=True, succeeded=True,
                outcome="search_succeeded", reason="response_received",
            )
            with self.subTest(provider=provider), patch.object(module, key_name, "key"), \
                 patch.object(module, search_name, return_value=photos), \
                 patch("image_query.generate_image_query", return_value="sunny weather Finland"), \
                 patch("image_state.is_image_used", return_value=False), \
                 patch("image_state.mark_image_used"), \
                 patch.object(unsplash, "_trigger_download"):
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, result = module.fetch_image_for_article(
                    title, "Kotimaa", summary=summary, **kwargs,
                )
            self.assertIsNotNone(image)
            self.assertEqual(result["outcome"], "accepted")
            self.assertTrue(result["attempted"])
            self.assertTrue(result["succeeded"])
            self.assertEqual(result["accepted_count"], 1)


if __name__ == "__main__":
    unittest.main()
