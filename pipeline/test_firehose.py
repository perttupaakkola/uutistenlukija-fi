#!/usr/bin/env python3
"""Credential-safety regressions for the supplementary Firehose source."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from . import firehose
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import firehose


FIREHOSE_SOURCE = Path(firehose.__file__).read_text(encoding="utf-8")


class FirehoseCredentialSafetyTests(unittest.TestCase):
    def test_token_is_loaded_from_environment_not_source(self) -> None:
        assignments = [
            line.strip()
            for line in FIREHOSE_SOURCE.splitlines()
            if line.startswith("FIREHOSE_TOKEN =")
        ]
        self.assertEqual(
            assignments,
            ['FIREHOSE_TOKEN = os.environ.get("FIREHOSE_TOKEN", "").strip()'],
        )
        self.assertNotRegex(FIREHOSE_SOURCE, r'FIREHOSE_TOKEN\s*=\s*["\']fh_')

    def test_missing_token_skips_poll_without_network_or_state_mutation(self) -> None:
        with (
            patch.object(firehose, "FIREHOSE_TOKEN", ""),
            patch.object(firehose.urllib.request, "urlopen") as urlopen,
            patch.object(firehose, "_load_state") as load_state,
            patch.object(firehose, "_save_state") as save_state,
        ):
            self.assertEqual(firehose.poll_firehose(), [])
        urlopen.assert_not_called()
        load_state.assert_not_called()
        save_state.assert_not_called()

    def test_authenticated_http_error_never_reads_or_logs_reflected_token(self) -> None:
        synthetic_token = "synthetic-reflected-token"
        response_body = Mock()
        response_body.read.return_value = (
            f'{{"error":"reflected-body:{synthetic_token}"}}'.encode()
        )
        error = firehose.urllib.error.HTTPError(
            url=f"{firehose.FIREHOSE_BASE}/stream",
            code=401,
            msg=f"unauthorized:{synthetic_token}",
            hdrs=None,
            fp=response_body,
        )

        with (
            patch.object(firehose, "FIREHOSE_TOKEN", synthetic_token),
            patch.object(firehose, "_load_state", return_value={}) as load_state,
            patch.object(firehose, "_save_state") as save_state,
            patch.object(
                firehose.urllib.request,
                "urlopen",
                side_effect=error,
            ) as urlopen,
            patch("builtins.print") as output,
        ):
            self.assertEqual(firehose.poll_firehose(), [])

        rendered = "\n".join(
            " ".join(map(str, call.args)) for call in output.call_args_list
        )
        urlopen.assert_called_once()
        load_state.assert_called_once()
        save_state.assert_not_called()
        response_body.read.assert_not_called()
        self.assertIn("HTTP 401", rendered)
        self.assertNotIn("reflected-body", rendered)
        self.assertNotIn(synthetic_token, rendered)

    def test_exception_text_redacts_configured_synthetic_token(self) -> None:
        synthetic_token = "synthetic-exception-token"
        with (
            patch.object(firehose, "FIREHOSE_TOKEN", synthetic_token),
            patch.object(firehose, "_load_state", return_value={}),
            patch.object(firehose, "_save_state") as save_state,
            patch.object(
                firehose.urllib.request,
                "urlopen",
                side_effect=RuntimeError(f"transport reflected {synthetic_token}"),
            ),
            patch("builtins.print") as output,
        ):
            self.assertEqual(firehose.poll_firehose(), [])

        rendered = "\n".join(
            " ".join(map(str, call.args)) for call in output.call_args_list
        )
        save_state.assert_not_called()
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn(synthetic_token, rendered)

    def test_dry_run_never_renders_the_token(self) -> None:
        with (
            patch.object(firehose, "FIREHOSE_TOKEN", "test-private-value"),
            patch.object(firehose, "list_rules", return_value=[]),
            patch("builtins.print") as output,
        ):
            firehose.register_rules(dry_run=True)
        rendered = "\n".join(" ".join(map(str, call.args)) for call in output.call_args_list)
        self.assertNotIn("test-private-value", rendered)
        self.assertIn("$FIREHOSE_TOKEN", rendered)


if __name__ == "__main__":
    unittest.main()
