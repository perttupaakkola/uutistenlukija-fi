#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_ope465_recovery import (
    EXPECTED_ORIGINAL_SHA256,
    VerificationError,
    file_snapshot,
    records_by_file,
    sha256_file,
    validate_summary,
    verify_failed_record,
    verify_surface_delta,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts" / "fixtures" / "ope465_recovery"
FILENAME = "20260717T145139Z_46c5cf6f44.json"
ORIGINAL_SHA256 = EXPECTED_ORIGINAL_SHA256[FILENAME]


def summary(records: list[dict[str, object]]) -> dict[str, object]:
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"count": len(records), "aggregate_sha256": hashlib.sha256(encoded).hexdigest(), "records": records}


def surfaces() -> tuple[dict[str, object], dict[str, object]]:
    failed = {FILENAME: "f" * 64}
    empty = summary([])
    pre = {
        "critical_blobs": {"pipeline/staged_publish.py": "blob"},
        "crontab_sha256": "paused",
        "content": summary([]),
        "queues": {
            "ready": copy.deepcopy(empty),
            "writing": summary([{"file": FILENAME, "sha256": ORIGINAL_SHA256}]),
            "outbox": copy.deepcopy(empty),
            "published": copy.deepcopy(empty),
            "failed": copy.deepcopy(empty),
        },
    }
    post = copy.deepcopy(pre)
    post["queues"]["writing"] = summary([])  # type: ignore[index]
    post["queues"]["failed"] = summary([{"file": FILENAME, "sha256": failed[FILENAME]}])  # type: ignore[index]
    return pre, post


class Ope465RecoveryVerifierTest(unittest.TestCase):
    def load_fixture(self, name: str) -> dict[str, object]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_accepted_nested_schema_passes_without_writing_fixture(self) -> None:
        path = FIXTURES / "accepted_nested.json"
        before = file_snapshot([path])
        verify_failed_record(self.load_fixture(path.name), FILENAME, ORIGINAL_SHA256)
        self.assertEqual(file_snapshot([path]), before)

    def test_top_level_only_action_fails_closed(self) -> None:
        with self.assertRaisesRegex(VerificationError, r"recovery_metadata\.action") as raised:
            verify_failed_record(self.load_fixture("top_level_only.json"), FILENAME, ORIGINAL_SHA256)
        self.assertEqual(raised.exception.code, "recovery_action")

    def test_wrong_failure_code_fails_closed(self) -> None:
        artifact = self.load_fixture("accepted_nested.json")
        artifact["failure_code"] = "stale_writing_orphan"
        with self.assertRaises(VerificationError) as raised:
            verify_failed_record(artifact, FILENAME, ORIGINAL_SHA256)
        self.assertEqual(raised.exception.code, "failure_code")

    def test_exact_queue_delta_passes(self) -> None:
        pre, post = surfaces()
        verify_surface_delta(pre, post, {FILENAME: ORIGINAL_SHA256}, {FILENAME: "f" * 64})

    def test_unrelated_queue_change_fails_closed(self) -> None:
        pre, post = surfaces()
        post["queues"]["outbox"] = summary([{"file": "unrelated.json", "sha256": "0" * 64}])  # type: ignore[index]
        with self.assertRaises(VerificationError) as raised:
            verify_surface_delta(pre, post, {FILENAME: ORIGINAL_SHA256}, {FILENAME: "f" * 64})
        self.assertEqual(raised.exception.code, "queue_drift")

    def test_summary_checksum_mismatch_fails_closed(self) -> None:
        broken = summary([{"file": FILENAME, "sha256": ORIGINAL_SHA256}])
        broken["aggregate_sha256"] = "0" * 64
        with self.assertRaises(VerificationError) as raised:
            validate_summary(broken, "fixture")
        self.assertEqual(raised.exception.code, "invalid_surface")

    def test_source_manifest_uses_observed_source_filename_key(self) -> None:
        records = [{"source_filename": FILENAME, "sha256": ORIGINAL_SHA256}]
        self.assertEqual(records_by_file(records, "source manifest", "source_filename")[FILENAME], records[0])

    def test_sha256_reader_does_not_change_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.json"
            path.write_bytes(b"{\"safe\":true}\n")
            before = file_snapshot([path])
            self.assertEqual(sha256_file(path), before[str(path.resolve())][3])
            self.assertEqual(file_snapshot([path]), before)


if __name__ == "__main__":
    unittest.main()
