import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.stale_outbox_archive import apply_plan, rollback, sha256


def words(count, prefix):
    return " ".join(f"{prefix}{index}" for index in range(count))


def record(*, eligible=False, completed_at="2026-08-01T00:00:00Z"):
    source_words = 220 if eligible else 100
    return {
        "completed_at": completed_at,
        "packet": {
            "category": "Ulkomaat",
            "clean_source_blocks": [{
                "source": "Fixture",
                "source_url": "https://example.test/story",
                "text": words(source_words, "source"),
            }],
        },
        "payload": {"category": "Ulkomaat"},
        "article": {
            "category": "Ulkomaat",
            "content": words(220, "article"),
            "source_url": "https://example.test/story",
        },
    }


class ArchiveTests(unittest.TestCase):
    def setup_fixture(self, root, specs=(("one.json", False),)):
        outbox = root / "pipeline/queues/staged/outbox"
        outbox.mkdir(parents=True)
        entries = []
        for name, eligible in specs:
            path = outbox / name
            path.write_text(json.dumps(record(eligible=eligible)), encoding="utf-8")
            entries.append({"source": path.relative_to(root).as_posix(), "sha256": sha256(path)})
        plan = root / "plan.json"
        plan.write_text(json.dumps({
            "schema": "uutistenlukija.stale_outbox_archive_plan.v1",
            "stale_before": "2026-08-01T00:00:00Z",
            "entries": entries,
        }), encoding="utf-8")
        return plan, entries

    def inventory(self, root):
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()
        }

    def test_dry_run_is_byte_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            before = self.inventory(root)
            result = apply_plan(root, plan, "20260829T170000Z")
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(self.inventory(root), before)

    def test_stale_cutoff_rejects_new_missing_naive_and_malformed_timestamps(self):
        cases = (
            ("2026-08-01T00:00:01Z", "newer"),
            (None, "completed_at"),
            ("2026-08-01T00:00:00", "timezone-aware UTC"),
            ("not-a-time", "completed_at"),
        )
        for value, message in cases:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); plan, entries = self.setup_fixture(root)
                source = root / entries[0]["source"]
                data = json.loads(source.read_text(encoding="utf-8"))
                if value is None:
                    data.pop("completed_at")
                else:
                    data["completed_at"] = value
                source.write_text(json.dumps(data), encoding="utf-8")
                plan_data = json.loads(plan.read_text(encoding="utf-8"))
                plan_data["entries"][0]["sha256"] = sha256(source)
                plan.write_text(json.dumps(plan_data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    apply_plan(root, plan, "20260829T170000Z")

    def test_exact_stale_boundary_is_accepted_with_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            result = apply_plan(root, plan, "20260829T170000Z")
            self.assertEqual(result["stale_before"], "2026-08-01T00:00:00Z")
            self.assertEqual(result["entries"][0]["record_time_field"], "completed_at")
            self.assertEqual(result["entries"][0]["record_time"], result["stale_before"])

    def test_apply_manifest_and_rollback_restore_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root, (("b.json", False), ("a.json", False)))
            before = self.inventory(root)
            result = apply_plan(root, plan, "20260829T170000Z", apply=True)
            self.assertEqual(result["schema"], "uutistenlukija.stale_outbox_archive.v1")
            self.assertTrue(result["reversible"])
            self.assertEqual([row["source"] for row in result["entries"]], sorted(row["source"] for row in result["entries"]))
            manifest = root / result["manifest"]
            self.assertEqual(rollback(root, manifest)["restored"], 2)
            after = self.inventory(root)
            after.pop(manifest.relative_to(root).as_posix())
            self.assertEqual(after, before)

    def test_hash_drift_and_collision_fail_before_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, entries = self.setup_fixture(root)
            source = root / entries[0]["source"]
            source.write_text("drift", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash drift"):
                apply_plan(root, plan, "20260829T170000Z", apply=True)
            self.assertTrue(source.exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, entries = self.setup_fixture(root)
            destination = root / "pipeline/queues/staged/failed_archive/20260829T170000Z/stale_outbox/one.json"
            destination.parent.mkdir(parents=True)
            destination.write_text("collision", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "collision"):
                apply_plan(root, plan, "20260829T170000Z", apply=True)
            self.assertTrue((root / entries[0]["source"]).exists())

    def test_publish_eligible_packet_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, entries = self.setup_fixture(root, (("eligible.json", True),))
            with self.assertRaisesRegex(ValueError, "publish-eligible"):
                apply_plan(root, plan, "20260829T170000Z", apply=True)
            self.assertTrue((root / entries[0]["source"]).exists())

    def test_existing_manifest_fails_before_write_or_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            manifest = root / "pipeline/queues/staged/failed_archive/20260829T170000Z/stale_outbox-manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(b"immutable prior recovery evidence\n")
            before = self.inventory(root)
            with self.assertRaisesRegex(ValueError, "manifest already exists"):
                apply_plan(root, plan, "20260829T170000Z", apply=True)
            self.assertEqual(self.inventory(root), before)

    def test_archive_id_escape_and_invalid_grammar_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            for archive_id in ("../../../../../../tmp/ope584-escape", "/tmp/escape", "20260829T170000Z/extra", "bad"):
                with self.subTest(archive_id=archive_id), self.assertRaisesRegex(ValueError, "archive id"):
                    apply_plan(root, plan, archive_id, apply=True)

    def test_rollback_rejects_malicious_manifest_paths_without_moving_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            archive_id = "20260829T170000Z"
            manifest = apply_plan(root, plan, archive_id, apply=True)
            manifest_path = root / manifest["manifest"]
            attacker = root / "misc/attacker.json"
            victim = root / "content/victim.json"
            attacker.parent.mkdir(parents=True); victim.parent.mkdir(parents=True)
            attacker.write_text("attacker", encoding="utf-8")
            victim.write_text("victim", encoding="utf-8")
            tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
            tampered["entries"] = [{
                "source": "content/victim.json",
                "destination": "misc/attacker.json",
                "sha256": sha256(attacker),
            }]
            manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(ValueError):
                rollback(root, manifest_path)
            self.assertEqual(attacker.read_text(encoding="utf-8"), "attacker")
            self.assertEqual(victim.read_text(encoding="utf-8"), "victim")

    def test_rollback_rejects_manifest_not_bound_to_exact_archive_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            result = apply_plan(root, plan, "20260829T170000Z", apply=True)
            manifest = root / result["manifest"]
            copied = root / "manifest.json"
            copied.write_bytes(manifest.read_bytes())
            with self.assertRaisesRegex(ValueError, "manifest path"):
                rollback(root, copied)

    def test_partial_apply_rollback_restores_exact_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, entries = self.setup_fixture(root, (("one.json", False), ("two.json", False)))
            before = self.inventory(root)
            real_sha256 = sha256
            destination_calls = 0

            def fail_first_destination(path):
                nonlocal destination_calls
                digest = real_sha256(path)
                if "failed_archive" in path.parts:
                    destination_calls += 1
                    if destination_calls == 1:
                        return "0" * 64
                return digest

            with mock.patch("scripts.stale_outbox_archive.sha256", side_effect=fail_first_destination):
                with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                    apply_plan(root, plan, "20260829T170000Z", apply=True)
            manifest = root / "pipeline/queues/staged/failed_archive/20260829T170000Z/stale_outbox-manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "partial")
            self.assertEqual(len(data["moved_entries"]), 1)
            self.assertEqual(rollback(root, manifest)["restored"], 1)
            after = self.inventory(root)
            after.pop(manifest.relative_to(root).as_posix())
            self.assertEqual(after, before)

    def test_partial_manifest_rejects_empty_duplicate_unknown_and_hash_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            result = apply_plan(root, plan, "20260829T170000Z", apply=True)
            manifest = root / result["manifest"]
            baseline = json.loads(manifest.read_text(encoding="utf-8"))
            cases = (
                [],
                [baseline["entries"][0], baseline["entries"][0]],
                [{**baseline["entries"][0], "sha256": "0" * 64}],
            )
            for moved in cases:
                with self.subTest(moved=moved):
                    data = {**baseline, "status": "partial", "moved_entries": moved}
                    manifest.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        rollback(root, manifest)

    def test_partial_rollback_rejects_complete_entry_tampering_before_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _ = self.setup_fixture(root)
            result = apply_plan(root, plan, "20260829T170000Z", apply=True)
            manifest = root / result["manifest"]
            baseline = json.loads(manifest.read_text(encoding="utf-8"))
            archived = root / baseline["entries"][0]["destination"]
            source = root / baseline["entries"][0]["source"]
            cases = (
                ("record_time", "2025-01-01T00:00:00Z"),
                ("stale_before", "2026-07-31T00:00:00Z"),
                ("record_time_field", "created_at"),
                ("source", "pipeline/queues/staged/outbox/tampered.json"),
                ("destination", "pipeline/queues/staged/failed_archive/20260829T170000Z/stale_outbox/tampered.json"),
                ("sha256", "0" * 64),
            )
            for field, value in cases:
                with self.subTest(field=field):
                    moved = {**baseline["entries"][0], field: value}
                    tampered = {**baseline, "status": "partial", "moved_entries": [moved]}
                    manifest.write_text(json.dumps(tampered), encoding="utf-8")
                    before = self.inventory(root)
                    with self.assertRaises(ValueError):
                        rollback(root, manifest)
                    self.assertEqual(self.inventory(root), before)
                    self.assertTrue(archived.is_file())
                    self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
