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


if __name__ == "__main__":
    unittest.main()
