#!/usr/bin/env python3
"""Credential-safety regressions for the supplementary Firehose source."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import firehose
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import firehose


FIREHOSE_SOURCE = Path(firehose.__file__).read_text(encoding="utf-8")


class FirehoseCredentialSafetyTests(unittest.TestCase):
    def test_token_is_loaded_from_environment_not_source(self) -> None:
        self.assertRegex(
            FIREHOSE_SOURCE,
            r'FIREHOSE_TOKEN\s*=\s*os\.environ\.get\("FIREHOSE_TOKEN",\s*""\)',
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
