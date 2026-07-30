#!/usr/bin/env python3
"""Regression tests for Kie.ai generated-image downloads."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import image_gen
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import image_gen


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, content_type: str) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class GeneratedImageDownloadTests(unittest.TestCase):
    def test_download_uses_image_headers_and_preserves_png_extension(self) -> None:
        payload = b"\x89PNG\r\n\x1a\n" + b"test-png-payload"
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            image_gen.urllib.request,
            "urlopen",
            return_value=_Response(payload, "image/png"),
        ) as urlopen:
            output_stem = str(Path(temp_dir) / "story")
            filepath = image_gen._download_generated_image(
                "https://tempfile.example/generated",
                output_stem,
            )

            self.assertEqual(filepath, f"{output_stem}.png")
            self.assertEqual(Path(filepath).read_bytes(), payload)
            self.assertFalse(Path(f"{output_stem}.part").exists())

            request = urlopen.call_args.args[0]
            self.assertEqual(
                request.get_header("User-agent"),
                image_gen.IMAGE_DOWNLOAD_USER_AGENT,
            )
            self.assertIn("image/png", request.get_header("Accept"))

    def test_download_rejects_non_image_payload_and_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            image_gen.urllib.request,
            "urlopen",
            return_value=_Response(b"forbidden", "text/plain"),
        ):
            output_stem = str(Path(temp_dir) / "story")
            with self.assertRaisesRegex(ValueError, "not a supported image"):
                image_gen._download_generated_image(
                    "https://tempfile.example/generated",
                    output_stem,
                )

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_download_enforces_stream_cap_without_content_length(self) -> None:
        payload = b"\x89PNG\r\n\x1a\n" + b"oversized"
        response = _Response(payload, "image/png")
        response.headers.pop("Content-Length")
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            image_gen,
            "IMAGE_DOWNLOAD_MAX_BYTES",
            12,
        ), patch.object(
            image_gen.urllib.request,
            "urlopen",
            return_value=response,
        ):
            output_stem = str(Path(temp_dir) / "story")
            with self.assertRaisesRegex(ValueError, "exceeds 12 bytes"):
                image_gen._download_generated_image(
                    "https://tempfile.example/generated",
                    output_stem,
                )

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_generation_preserves_http_status_class_without_raw_error(self) -> None:
        http_error = image_gen.urllib.error.HTTPError(
            "https://api.kie.ai/api/v1/jobs/createTask",
            403,
            "Forbidden",
            {},
            None,
        )
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(image_gen, "IMAGE_DIR", temp_dir), \
             patch.object(image_gen, "_kie_request", side_effect=http_error):
            result = image_gen.generate_article_image(
                "Kuvaton artikkeli",
                "Talous",
                "kuvaton-artikkeli",
            )

        self.assertIsNone(result.image_path)
        self.assertEqual(
            result.terminal["reason"],
            image_gen.REASON_PROVIDER_HTTP,
        )
        self.assertEqual(result.terminal["http_status_class"], "4xx")
        self.assertTrue(result.terminal["provider_fault"])
        serialized = str(result.terminal)
        self.assertNotIn("403", serialized)
        self.assertNotIn("Forbidden", serialized)

    def test_generation_ignores_provider_exif_for_semantic_evidence(self) -> None:
        from PIL import Image

        payload = io.BytesIO()
        exif = Image.Exif()
        exif[270] = "boat repair workshop and small craft restoration"
        Image.new("RGB", (160, 90), "navy").save(payload, format="JPEG", exif=exif)

        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(image_gen, "IMAGE_DIR", temp_dir), \
             patch.object(
                 image_gen,
                 "_kie_request",
                 return_value={"data": {"taskId": "task-observed"}},
             ), \
             patch.object(
                 image_gen,
                 "_poll_task_with_timeout",
                 return_value=image_gen._PollResult(
                     "https://tempfile.example/generated.jpg",
                 ),
             ), \
             patch.object(
                 image_gen.urllib.request,
                 "urlopen",
                 return_value=_Response(payload.getvalue(), "image/jpeg"),
             ):
            result = image_gen.generate_article_image(
                "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
                "Talous",
                "veneenkorjaus",
            )

        self.assertEqual(result.image_path, "/images/articles/veneenkorjaus.jpg")
        self.assertEqual(result.raster_properties["image_format"], "jpeg")
        self.assertEqual(result.raster_properties["image_width"], 160)
        self.assertEqual(result.raster_properties["image_height"], 90)
        self.assertNotIn("description", result.raster_properties)
        self.assertEqual(result.pixel_semantics, {})
        self.assertTrue(result.terminal["provider_succeeded"])

    def test_poll_retries_transient_http_and_transport_failures_until_success(self) -> None:
        transient_http = image_gen.urllib.error.HTTPError(
            "https://api.kie.ai/api/v1/jobs/recordInfo",
            503,
            "Unavailable",
            {},
            None,
        )
        transient_transport = image_gen.urllib.error.URLError(
            TimeoutError("temporary timeout"),
        )
        success = {
            "data": {
                "state": "success",
                "resultJson": (
                    '{"resultUrls":["https://tempfile.example/generated.jpg"]}'
                ),
            },
        }

        with patch.object(
            image_gen,
            "_kie_get",
            side_effect=[transient_http, transient_transport, success],
        ) as get_task, patch.object(image_gen.time, "sleep") as delayed:
            result = image_gen._poll_task_with_timeout("task-transient", timeout_sec=30)

        self.assertEqual(result.image_url, "https://tempfile.example/generated.jpg")
        self.assertFalse(result.provider_fault)
        self.assertEqual(get_task.call_count, 3)
        self.assertEqual(delayed.call_count, 2)
        delayed.assert_called_with(image_gen.POLL_INTERVAL_SEC)

    def test_poll_stops_immediately_on_permanent_http_failure(self) -> None:
        permanent_http = image_gen.urllib.error.HTTPError(
            "https://api.kie.ai/api/v1/jobs/recordInfo",
            403,
            "Forbidden",
            {},
            None,
        )

        with patch.object(
            image_gen,
            "_kie_get",
            side_effect=permanent_http,
        ) as get_task, patch.object(image_gen.time, "sleep") as delayed:
            result = image_gen._poll_task_with_timeout("task-permanent", timeout_sec=1)

        self.assertIsNone(result.image_url)
        self.assertTrue(result.provider_fault)
        self.assertEqual(result.reason, image_gen.REASON_PROVIDER_HTTP)
        self.assertEqual(result.http_status_class, "4xx")
        get_task.assert_called_once()
        delayed.assert_not_called()

    def test_poll_transient_failures_stop_at_existing_deadline(self) -> None:
        transient_transport = image_gen.urllib.error.URLError(
            TimeoutError("temporary timeout"),
        )
        started = image_gen.time.monotonic()

        with patch.object(
            image_gen,
            "_kie_get",
            side_effect=transient_transport,
        ) as get_task:
            result = image_gen._poll_task_with_timeout(
                "task-deadline",
                timeout_sec=0.03,
            )

        elapsed = image_gen.time.monotonic() - started
        self.assertIsNone(result.image_url)
        self.assertTrue(result.provider_fault)
        self.assertEqual(result.reason, image_gen.REASON_TIMEOUT)
        self.assertGreaterEqual(get_task.call_count, 1)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
