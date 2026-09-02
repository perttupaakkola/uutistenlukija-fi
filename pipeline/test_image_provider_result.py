#!/usr/bin/env python3
from __future__ import annotations

import unittest
import json
from unittest.mock import patch

try:
    from . import image_query, image_state, pexels, unsplash
    from .image_provider_result import (
        IMAGE_PROVIDER_RESULT_SCHEMA,
        MAX_PROVIDER_COUNT,
        build_provider_result,
        combine_provider_results,
        get_provider_result,
        search_photos,
        set_provider_result,
    )
except ImportError:  # pragma: no cover - direct pipeline execution
    import image_query
    import image_state
    import pexels
    import unsplash
    from image_provider_result import (
        IMAGE_PROVIDER_RESULT_SCHEMA,
        MAX_PROVIDER_COUNT,
        build_provider_result,
        combine_provider_results,
        get_provider_result,
        search_photos,
        set_provider_result,
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

    def test_provider_compliance_failures_are_explicit_fault_receipts(self) -> None:
        cases = (
            (
                "delivery_failed",
                dict(
                    semantic_accepted=True,
                    attribution_complete=True,
                    delivery_mode="hotlink",
                    delivery_attempted=True,
                    delivery_succeeded=True,
                    thumbnail_delivery_succeeded=False,
                ),
            ),
            (
                "tracking_failed",
                dict(
                    semantic_accepted=True,
                    attribution_complete=True,
                    delivery_mode="hotlink",
                    delivery_attempted=True,
                    delivery_succeeded=True,
                    thumbnail_delivery_succeeded=True,
                    tracking_attempted=True,
                    tracking_succeeded=False,
                ),
            ),
            (
                "attribution_incomplete",
                dict(
                    semantic_accepted=True,
                    attribution_complete=False,
                    delivery_mode="hotlink",
                    delivery_attempted=True,
                    delivery_succeeded=True,
                    thumbnail_delivery_succeeded=True,
                ),
            ),
        )
        search = build_provider_result(
            provider="unsplash",
            attempted=True,
            succeeded=True,
            outcome="search_succeeded",
            reason="response_received",
        )

        for expected, facts in cases:
            with self.subTest(outcome=expected):
                result = combine_provider_results(
                    provider="unsplash",
                    searches=[search],
                    candidate_count=1,
                    fresh_candidate_count=1,
                    rejected_count=0,
                    # Even a wrapper that mistakenly reports an accepted row
                    # must be normalized fail-closed when compliance facts fail.
                    accepted_count=1,
                    **facts,
                )

                self.assertEqual(result["outcome"], expected)
                self.assertEqual(result["accepted_count"], 0)
                self.assertGreater(result["fault_count"], 0)

    def test_stored_accepted_receipt_requires_complete_compliance_facts(self) -> None:
        article: dict = {}
        set_provider_result(article, build_provider_result(
            provider="unsplash",
            attempted=True,
            succeeded=True,
            outcome="accepted",
            reason="candidate_accepted",
            accepted_count=1,
        ))

        stored = get_provider_result(article, "unsplash")

        self.assertIsNotNone(stored)
        self.assertEqual(stored["outcome"], "provider_fault")
        self.assertEqual(stored["reason"], "invalid_acceptance_receipt")
        self.assertEqual(stored["accepted_count"], 0)
        self.assertGreater(stored["fault_count"], 0)

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
                "url_regular": "https://images.unsplash.com/photo-sunny?w=1080",
                "url_full": "https://images.unsplash.com/photo-sunny?w=1600",
                "url_small": "https://images.unsplash.com/photo-sunny?w=400",
                "url_thumb": "https://images.unsplash.com/photo-sunny?w=200",
                "photographer": "Test",
                "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
                "photo_page": "https://unsplash.com/photos/sunny?utm_source=uutistenlukija&utm_medium=referral",
            },
            "pexels": {
                "id": 2,
                "alt": "sunny blue sky over green field",
                "url": "https://images.pexels.com/photos/2/pexels-photo-2.jpeg?w=1920",
                "thumb_url": "https://images.pexels.com/photos/2/pexels-photo-2.jpeg?w=400",
                "photographer": "Test",
                "photographer_url": "https://www.pexels.com/@test",
                "pexels_url": "https://www.pexels.com/photo/sunny-field-2/",
            },
        }
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            with self.subTest(provider=provider), patch.object(module, key_name, "key"), \
                 patch.object(module, search_name, return_value=[candidates[provider]]), \
                 patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"):
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
                     patch.object(image_query, "generate_image_query", return_value="public opinion survey ballot"):
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
                 patch.object(image_query, "generate_image_query", return_value="business entrepreneur"), \
                 patch.object(image_state, "is_image_used", return_value=False):
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
                "url_regular": "https://images.unsplash.com/photo-sunny?w=1080",
                "url_full": "https://images.unsplash.com/photo-sunny?w=1600",
                "url_small": "https://images.unsplash.com/photo-sunny?w=400",
                "url_thumb": "https://images.unsplash.com/photo-sunny?w=200",
                "photographer": "Test",
                "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
                "photo_page": "https://unsplash.com/photos/sunny?utm_source=uutistenlukija&utm_medium=referral",
            },
            "pexels": {
                "id": 2,
                "alt": "sunny blue sky over green field",
                "url": "https://images.pexels.com/photos/2/pexels-photo-2.jpeg?w=1920",
                "thumb_url": "https://images.pexels.com/photos/2/pexels-photo-2.jpeg?w=400",
                "photographer": "Test",
                "photographer_url": "https://www.pexels.com/@test",
                "pexels_url": "https://www.pexels.com/photo/sunny-field-2/",
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
                 patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
                 patch.object(image_state, "is_image_used", return_value=False), \
                 patch.object(image_state, "mark_image_used"), \
                 patch.object(unsplash, "_trigger_download", return_value=(True, True)):
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
            self.assertTrue(result["semantic_accepted"])
            self.assertTrue(result["attribution_complete"])
            self.assertTrue(result["delivery_succeeded"])
            self.assertTrue(result["thumbnail_delivery_succeeded"])
            if provider == "unsplash":
                self.assertEqual(result["delivery_mode"], "hotlink")
                self.assertTrue(result["tracking_attempted"])
                self.assertTrue(result["tracking_succeeded"])
            else:
                self.assertEqual(result["delivery_mode"], "hotlink")
                self.assertFalse(result["tracking_attempted"])

    def test_provider_attribution_requires_official_https_links(self) -> None:
        fixtures = (
            (
                unsplash,
                {
                    "id": "sunny",
                    "photographer": "Test",
                    "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
                    "photo_page": "https://unsplash.com/photos/sunny?utm_source=uutistenlukija&utm_medium=referral",
                },
                "photo_page",
            ),
            (
                pexels,
                {
                    "id": 2,
                    "photographer": "Test",
                    "photographer_url": "https://www.pexels.com/@test",
                    "pexels_url": "https://www.pexels.com/photo/sunny-field-2/",
                },
                "pexels_url",
            ),
        )
        for module, valid, source_key in fixtures:
            with self.subTest(provider=module.__name__):
                self.assertTrue(module._attribution_complete(valid))
                spoofed = dict(valid)
                spoofed[source_key] = "https://attacker.invalid/provider-photo"
                self.assertFalse(module._attribution_complete(spoofed))
                insecure = dict(valid)
                insecure["photographer_url"] = insecure["photographer_url"].replace(
                    "https://", "http://", 1
                )
                self.assertFalse(module._attribution_complete(insecure))
                if module is unsplash:
                    missing_utm = dict(valid)
                    missing_utm["photo_page"] = "https://unsplash.com/photos/sunny"
                    self.assertFalse(module._attribution_complete(missing_utm))

    def test_each_provider_classifies_missing_attribution_independently(self) -> None:
        candidates = {
            "unsplash": {
                "id": "sunny-bad-attribution",
                "alt": "sunny blue sky over green field",
                "url_regular": "https://images.unsplash.com/photo-sunny?w=1080",
                "url_small": "https://images.unsplash.com/photo-sunny?w=400",
                "photographer": "Test",
                "photographer_url": "https://attacker.invalid/@test",
                "photo_page": "https://unsplash.com/photos/sunny-bad-attribution?utm_source=uutistenlukija&utm_medium=referral",
            },
            "pexels": {
                "id": 31,
                "alt": "sunny blue sky over green field",
                "url": "https://images.pexels.com/photos/31/pexels-photo-31.jpeg?w=1920",
                "thumb_url": "https://images.pexels.com/photos/31/pexels-photo-31.jpeg?w=400",
                "photographer": "Test",
                "photographer_url": "https://attacker.invalid/@test",
                "pexels_url": "https://www.pexels.com/photo/sunny-field-31/",
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
                 patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
                 patch.object(image_state, "is_image_used", return_value=False), \
                 patch.object(image_state, "mark_image_used") as marked, \
                 patch.object(unsplash, "_trigger_download") as tracked:
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, receipt = module.fetch_image_for_article(
                    "Loppuviikon sää on aurinkoinen",
                    "Kotimaa",
                    summary="Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä.",
                    **kwargs,
                )

            self.assertIsNone(image)
            self.assertEqual(receipt["outcome"], "attribution_incomplete")
            self.assertTrue(receipt["semantic_accepted"])
            self.assertFalse(receipt["attribution_complete"])
            self.assertEqual(receipt["accepted_count"], 0)
            marked.assert_not_called()
            if provider == "unsplash":
                tracked.assert_not_called()

    def test_each_provider_rejects_untrusted_asset_hosts(self) -> None:
        candidates = {
            "unsplash": {
                "id": "sunny-untrusted",
                "alt": "sunny blue sky over green field",
                "url_regular": "https://attacker.invalid/sunny.jpg",
                "url_small": "https://attacker.invalid/sunny-thumb.jpg",
                "photographer": "Test",
                "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
                "photo_page": "https://unsplash.com/photos/sunny-untrusted?utm_source=uutistenlukija&utm_medium=referral",
            },
            "pexels": {
                "id": 29,
                "alt": "sunny blue sky over green field",
                "url": "https://attacker.invalid/sunny.jpg",
                "thumb_url": "https://attacker.invalid/sunny-thumb.jpg",
                "photographer": "Test",
                "photographer_url": "https://www.pexels.com/@test",
                "pexels_url": "https://www.pexels.com/photo/sunny-field-29/",
            },
        }
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            photos = search_photos(
                [candidates[provider]],
                provider=provider,
                attempted=True,
                succeeded=True,
                outcome="search_succeeded",
                reason="response_received",
            )
            with self.subTest(provider=provider), patch.object(module, key_name, "key"), \
                 patch.object(module, search_name, return_value=photos), \
                 patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
                 patch.object(image_state, "is_image_used", return_value=False), \
                 patch.object(image_state, "mark_image_used") as marked, \
                 patch.object(unsplash, "_trigger_download", return_value=(True, True)) as tracked:
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, receipt = module.fetch_image_for_article(
                    "Loppuviikon sää on aurinkoinen",
                    "Kotimaa",
                    summary="Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä.",
                    **kwargs,
                )

            self.assertIsNone(image)
            self.assertEqual(receipt["outcome"], "delivery_failed")
            self.assertEqual(receipt["accepted_count"], 0)
            marked.assert_not_called()
            if provider == "unsplash":
                tracked.assert_not_called()

    def test_unsplash_tracking_never_sends_credentials_to_untrusted_host(self) -> None:
        with patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), patch.object(
            unsplash.urllib.request,
            "urlopen",
        ) as opened:
            attempted, succeeded = unsplash._trigger_download({
                "id": "sunny",
                "download_location": "https://attacker.invalid/collect",
            })

        self.assertFalse(attempted)
        self.assertFalse(succeeded)
        opened.assert_not_called()

    def test_unsplash_tracking_endpoint_must_exactly_bind_selected_photo_id(self) -> None:
        invalid_locations = (
            "https://api.unsplash.com/photos/different/download",
            "https://api.unsplash.com/photos/%73unny/download",
            "https://api.unsplash.com/photos/sunny%2Fother/download",
            "https://api.unsplash.com/photos/sunny/../different/download",
            "https://api.unsplash.com/photos/sunny/download/extra",
        )
        for location in invalid_locations:
            with self.subTest(location=location), patch.object(
                unsplash,
                "UNSPLASH_ACCESS_KEY",
                "key",
            ), patch.object(unsplash.urllib.request, "urlopen") as opened:
                attempted, succeeded = unsplash._trigger_download({
                    "id": "sunny",
                    "download_location": location,
                })

            self.assertFalse(attempted)
            self.assertFalse(succeeded)
            opened.assert_not_called()

    def test_provider_candidate_id_must_bind_asset_and_attribution_urls(self) -> None:
        candidates = {
            "unsplash": {
                "id": "sunny",
                "alt": "sunny blue sky over green field",
                "url_regular": "https://images.unsplash.com/photo-sunny?w=1080",
                "url_small": "https://images.unsplash.com/photo-sunny?w=400",
                "download_location": "https://api.unsplash.com/photos/sunny/download",
                "photographer": "Test",
                "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
                "photo_page": "https://unsplash.com/photos/different?utm_source=uutistenlukija&utm_medium=referral",
            },
            "pexels": {
                "id": 202,
                "alt": "sunny blue sky over green field",
                "url": "https://images.pexels.com/photos/999/pexels-photo-999.jpeg?w=1920",
                "thumb_url": "https://images.pexels.com/photos/999/pexels-photo-999.jpeg?w=400",
                "photographer": "Test",
                "photographer_url": "https://www.pexels.com/@test",
                "pexels_url": "https://www.pexels.com/photo/sunny-field-888/",
            },
        }
        for module, provider, key_name, search_name in (
            (unsplash, "unsplash", "UNSPLASH_ACCESS_KEY", "_search"),
            (pexels, "pexels", "PEXELS_API_KEY", "_search_pexels"),
        ):
            self.assertFalse(module._attribution_complete(candidates[provider]))
            photos = search_photos(
                [candidates[provider]],
                provider=provider,
                attempted=True,
                succeeded=True,
                outcome="search_succeeded",
                reason="response_received",
            )
            with self.subTest(provider=provider), patch.object(module, key_name, "key"), \
                 patch.object(module, search_name, return_value=photos), \
                 patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
                 patch.object(image_state, "is_image_used", return_value=False), \
                 patch.object(image_state, "mark_image_used") as marked, \
                 patch.object(unsplash, "_trigger_download", return_value=(True, True)) as tracked:
                kwargs = {"return_result": True, "inter_request_delay": 0}
                if provider == "pexels":
                    kwargs["download"] = False
                image, receipt = module.fetch_image_for_article(
                    "Loppuviikon sää on aurinkoinen",
                    "Kotimaa",
                    summary="Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä.",
                    **kwargs,
                )

            self.assertIsNone(image)
            self.assertIn(receipt["outcome"], {"provider_fault", "attribution_incomplete"})
            self.assertEqual(receipt["reason"], "provider_identity_mismatch")
            self.assertEqual(receipt["accepted_count"], 0)
            self.assertGreater(receipt["fault_count"], 0)
            marked.assert_not_called()
            if provider == "unsplash":
                tracked.assert_not_called()

    def test_provider_identity_binding_rejects_encoded_or_ambiguous_paths(self) -> None:
        valid_unsplash = {
            "id": "sunny",
            "photo_page": "https://unsplash.com/photos/bright-day-sunny?utm_source=uutistenlukija&utm_medium=referral",
            "download_location": "https://api.unsplash.com/photos/sunny/download",
        }
        valid_pexels = {
            "id": 202,
            "url": "https://images.pexels.com/photos/202/pexels-photo-202.jpeg?w=1920",
            "thumb_url": "https://images.pexels.com/photos/202/pexels-photo-202.jpeg?w=400",
            "pexels_url": "https://www.pexels.com/photo/sunny-field-202/",
        }
        self.assertTrue(unsplash._candidate_identity_consistent(valid_unsplash))
        self.assertTrue(pexels._candidate_identity_consistent(valid_pexels))

        for key, value in (
            ("photo_page", "https://unsplash.com/photos/bright-day-%73unny?utm_source=uutistenlukija&utm_medium=referral"),
            ("photo_page", "https://unsplash.com/photos/sunny/../sunny?utm_source=uutistenlukija&utm_medium=referral"),
            ("download_location", "https://api.unsplash.com/photos/%73unny/download"),
        ):
            candidate = dict(valid_unsplash)
            candidate[key] = value
            with self.subTest(provider="unsplash", key=key, value=value):
                self.assertFalse(unsplash._candidate_identity_consistent(candidate))

        for key, value in (
            ("url", "https://images.pexels.com/photos/%32%30%32/pexels-photo-202.jpeg"),
            ("thumb_url", "https://images.pexels.com/photos/202/../999/pexels-photo-202.jpeg"),
            ("pexels_url", "https://www.pexels.com/photo/sunny-field-%32%30%32/"),
        ):
            candidate = dict(valid_pexels)
            candidate[key] = value
            with self.subTest(provider="pexels", key=key, value=value):
                self.assertFalse(pexels._candidate_identity_consistent(candidate))

    def test_unsplash_missing_delivery_urls_cannot_be_accepted(self) -> None:
        candidate = {
            "id": "sunny-missing-delivery",
            "alt": "sunny blue sky over green field",
            "url_regular": None,
            "url_full": None,
            "url_small": None,
            "url_thumb": None,
            "download_location": "https://api.unsplash.com/photos/sunny-missing-delivery/download",
            "photographer": "Test",
            "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
            "photo_page": "https://unsplash.com/photos/sunny-missing-delivery?utm_source=uutistenlukija&utm_medium=referral",
        }
        photos = search_photos(
            [candidate], provider="unsplash", attempted=True, succeeded=True,
            outcome="search_succeeded", reason="response_received",
        )
        with patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(unsplash, "_search", return_value=photos), \
             patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
             patch.object(image_state, "is_image_used", return_value=False), \
             patch.object(image_state, "mark_image_used") as marked, \
             patch.object(unsplash, "_trigger_download") as tracked:
            image, receipt = unsplash.fetch_image_for_article(
                "Loppuviikon sää on aurinkoinen",
                "Kotimaa",
                summary="Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä.",
                return_result=True,
                inter_request_delay=0,
            )

        self.assertIsNone(image)
        self.assertEqual(receipt["outcome"], "delivery_failed")
        self.assertTrue(receipt["semantic_accepted"])
        self.assertFalse(receipt["delivery_succeeded"])
        self.assertEqual(receipt["accepted_count"], 0)
        tracked.assert_not_called()
        marked.assert_not_called()

    def test_unsplash_tracking_failure_is_a_separate_fail_closed_receipt(self) -> None:
        candidate = {
            "id": "sunny-tracking-failure",
            "alt": "sunny blue sky over green field",
            "url_regular": "https://images.unsplash.com/photo-sunny?w=1080",
            "url_small": "https://images.unsplash.com/photo-sunny?w=400",
            "download_location": "https://api.unsplash.com/photos/sunny-tracking-failure/download",
            "photographer": "Test",
            "photographer_url": "https://unsplash.com/@test?utm_source=uutistenlukija&utm_medium=referral",
            "photo_page": "https://unsplash.com/photos/sunny-tracking-failure?utm_source=uutistenlukija&utm_medium=referral",
        }
        photos = search_photos(
            [candidate], provider="unsplash", attempted=True, succeeded=True,
            outcome="search_succeeded", reason="response_received",
        )
        with patch.object(unsplash, "UNSPLASH_ACCESS_KEY", "key"), \
             patch.object(unsplash, "_search", return_value=photos), \
             patch.object(image_query, "generate_image_query", return_value="sunny weather Finland"), \
             patch.object(image_state, "is_image_used", return_value=False), \
             patch.object(image_state, "mark_image_used") as marked, \
             patch.object(unsplash, "_trigger_download", return_value=(True, False)):
            image, receipt = unsplash.fetch_image_for_article(
                "Loppuviikon sää on aurinkoinen",
                "Kotimaa",
                summary="Poutainen ja aurinkoinen sää jatkuu vihreiden peltojen yllä.",
                return_result=True,
                inter_request_delay=0,
            )

        self.assertIsNone(image)
        self.assertEqual(receipt["outcome"], "tracking_failed")
        self.assertTrue(receipt["semantic_accepted"])
        self.assertTrue(receipt["delivery_succeeded"])
        self.assertTrue(receipt["tracking_attempted"])
        self.assertFalse(receipt["tracking_succeeded"])
        self.assertEqual(receipt["accepted_count"], 0)
        marked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
