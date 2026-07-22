#!/usr/bin/env python3
"""Fail-closed, read-only verification for the preserved OPE-465 recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


INDEX_NAME = "SHA256SUMS.v2"
EXPECTED_INDEX_SHA256 = "89729a77f0b1fef97e99e9b79a165ec8658c139dccf3179fd40ed114f9ebc270"
EXPECTED_ACTION = "moved_writing_to_failed"
EXPECTED_FAILURE_CODE = "stale-writing-orphan"
EXPECTED_CRONTAB_SHA256 = "76ab6476986ceda7fb997257a5030a8c19d8d0deca0012af08792c98f91f9bc1"
EXPECTED_ORIGINAL_SHA256 = {
    "20260717T145139Z_46c5cf6f44.json": "a0a7131e2496f948020a2cadc9cdc5d97d4e30a1f791233ee705e5d13ec557fd",
    "20260720T062123Z_71881b398b.json": "40a093d42f4652780d3c48f87ca66a6b33ef606c3b098812ccf08528cc9e941f",
    "20260721T085129Z_492c9c0275.json": "9e4edbadae3d0a239a2f47bfba54387a87b15b8b46ace6d8d3ae020408389656",
}
EXPECTED_FAILED_SHA256 = {
    "20260717T145139Z_46c5cf6f44.json": "4a42781b3d05893377ae19405f34e5f0a1385e39d890301ad65f19aa034dc807",
    "20260720T062123Z_71881b398b.json": "c4bd8f64ad4ab1de10023fd4688030137a45c6027ddfb195a3013746c9158003",
    "20260721T085129Z_492c9c0275.json": "7b7bd9d9660d218180267ed0ec44701feb6108ba05c2b7deac7e92df0464084d",
}
EXPECTED_QUEUE_COUNTS = {
    "pre": {"ready": 0, "writing": 3, "outbox": 143, "published": 2458, "failed": 4663},
    "post": {"ready": 0, "writing": 0, "outbox": 143, "published": 2458, "failed": 4666},
}


class VerificationError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise VerificationError(code, detail)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("invalid_json", f"{label} is not readable JSON: {type(exc).__name__}") from exc
    require(isinstance(value, dict), "invalid_json", f"{label} must be a JSON object")
    return value


def file_snapshot(paths: Iterable[Path]) -> dict[str, tuple[int, int, int, str]]:
    snapshot: dict[str, tuple[int, int, int, str]] = {}
    for path in sorted(set(paths), key=str):
        require(path.is_file(), "missing_file", f"missing required file: {path.name}")
        require(not path.is_symlink(), "unsafe_path", f"symlink is not allowed: {path.name}")
        info = path.stat()
        snapshot[str(path.resolve())] = (info.st_size, info.st_mtime_ns, stat.S_IMODE(info.st_mode), sha256_file(path))
    return snapshot


def recovery_files(root: Path) -> list[Path]:
    files = [path for path in root.rglob("*") if path.is_file()]
    require(all(not path.is_symlink() for path in files), "unsafe_path", "recovery directory contains a symlink")
    return files


def verify_checksum_index(root: Path) -> int:
    index = root / INDEX_NAME
    require(index.is_file() and not index.is_symlink(), "missing_index", f"{INDEX_NAME} is missing or unsafe")
    require(
        sha256_file(index) == EXPECTED_INDEX_SHA256,
        "index_checksum",
        f"{INDEX_NAME} checksum does not match the accepted OPE-465 value",
    )

    root_real = root.resolve()
    indexed: dict[Path, str] = {}
    for line_number, line in enumerate(index.read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split("  ", 1)
        require(len(parts) == 2 and len(parts[0]) == 64, "invalid_index", f"invalid checksum line {line_number}")
        expected_hash, raw_path = parts
        require(all(ch in "0123456789abcdef" for ch in expected_hash), "invalid_index", f"invalid hash on line {line_number}")
        candidate = Path(raw_path)
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root_real)
        except (FileNotFoundError, ValueError) as exc:
            raise VerificationError("unsafe_index_path", f"checksum line {line_number} escapes or is missing") from exc
        require(resolved.name != INDEX_NAME, "invalid_index", "checksum index must not include itself")
        require(resolved not in indexed, "invalid_index", f"duplicate checksum entry: {resolved.name}")
        require(resolved.is_file() and not resolved.is_symlink(), "unsafe_index_path", f"unsafe checksum entry: {resolved.name}")
        indexed[resolved] = expected_hash

    actual = {path.resolve() for path in recovery_files(root) if path.name != INDEX_NAME}
    require(set(indexed) == actual, "index_coverage", "checksum index does not exactly cover recovery files")
    for path, expected_hash in indexed.items():
        require(sha256_file(path) == expected_hash, "artifact_checksum", f"checksum mismatch: {path.name}")
    return len(indexed)


def records_by_file(records: Any, label: str, filename_key: str = "file") -> dict[str, dict[str, Any]]:
    require(isinstance(records, list), "invalid_surface", f"{label}.records must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in records:
        require(
            isinstance(item, dict) and isinstance(item.get(filename_key), str),
            "invalid_surface",
            f"{label} has an invalid record",
        )
        filename = item[filename_key]
        require(filename not in result, "invalid_surface", f"{label} has duplicate file {filename}")
        result[filename] = item
    return result


def validate_summary(summary: Any, label: str) -> dict[str, dict[str, Any]]:
    require(isinstance(summary, dict), "invalid_surface", f"{label} must be an object")
    records = records_by_file(summary.get("records"), label)
    require(summary.get("count") == len(records), "invalid_surface", f"{label} count does not match records")
    encoded = json.dumps(summary["records"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    require(hashlib.sha256(encoded).hexdigest() == summary.get("aggregate_sha256"), "invalid_surface", f"{label} aggregate mismatch")
    return records


def verify_surface_delta(
    pre: Mapping[str, Any],
    post: Mapping[str, Any],
    original_sha256: Mapping[str, str],
    failed_sha256: Mapping[str, str],
    expected_counts: Mapping[str, Mapping[str, int]] | None = None,
) -> None:
    require(pre.get("critical_blobs") == post.get("critical_blobs"), "surface_drift", "runtime-critical blobs changed")
    require(pre.get("crontab_sha256") == post.get("crontab_sha256"), "surface_drift", "crontab hash changed")
    require(pre.get("content") == post.get("content"), "surface_drift", "content surface changed")

    pre_queues = pre.get("queues")
    post_queues = post.get("queues")
    require(isinstance(pre_queues, dict) and isinstance(post_queues, dict), "invalid_surface", "queue summaries are missing")
    pre_records: dict[str, dict[str, dict[str, Any]]] = {}
    post_records: dict[str, dict[str, dict[str, Any]]] = {}
    for box in ("ready", "writing", "outbox", "published", "failed"):
        pre_records[box] = validate_summary(pre_queues.get(box), f"pre.{box}")
        post_records[box] = validate_summary(post_queues.get(box), f"post.{box}")
        if expected_counts is not None:
            require(pre_queues[box]["count"] == expected_counts["pre"][box], "queue_count", f"unexpected pre {box} count")
            require(post_queues[box]["count"] == expected_counts["post"][box], "queue_count", f"unexpected post {box} count")

    for box in ("ready", "outbox", "published"):
        require(pre_queues[box] == post_queues[box], "queue_drift", f"unrelated {box} queue changed")

    require(
        {name: row.get("sha256") for name, row in pre_records["writing"].items()} == dict(original_sha256),
        "writing_set",
        "pre writing queue is not the exact accepted source set",
    )
    require(not post_records["writing"], "writing_set", "post writing queue is not empty")

    expected_names = set(failed_sha256)
    require(expected_names.isdisjoint(pre_records["failed"]), "failed_set", "accepted failed names already existed before recovery")
    require(
        {name: post_records["failed"].get(name, {}).get("sha256") for name in expected_names} == dict(failed_sha256),
        "failed_set",
        "post failed queue is missing an accepted artifact or checksum",
    )
    require(
        {name: row for name, row in post_records["failed"].items() if name not in expected_names} == pre_records["failed"],
        "failed_set",
        "failed queue changed outside the exact accepted artifact set",
    )


def verify_failed_record(data: Mapping[str, Any], filename: str, original_sha256: str) -> None:
    require(data.get("failure_code") == EXPECTED_FAILURE_CODE, "failure_code", f"unexpected failure_code: {filename}")
    metadata = data.get("recovery_metadata")
    require(isinstance(metadata, dict), "recovery_metadata", f"recovery_metadata is missing: {filename}")
    require(
        metadata.get("action") == EXPECTED_ACTION,
        "recovery_action",
        f"recovery_metadata.action is missing or invalid: {filename}",
    )
    require(metadata.get("original_sha256") == original_sha256, "original_checksum", f"original checksum mismatch: {filename}")
    require(Path(str(metadata.get("backup_path", ""))).name == filename, "recovery_path", f"backup filename mismatch: {filename}")
    require(Path(str(metadata.get("source_path", ""))).name == filename, "recovery_path", f"source filename mismatch: {filename}")
    age_seconds = metadata.get("age_seconds")
    require(isinstance(age_seconds, (int, float)) and age_seconds >= 0, "recovery_age", f"invalid age_seconds: {filename}")


def verify_recovery(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    require(root.is_dir() and not root.is_symlink(), "invalid_root", "recovery root is not a safe directory")
    recovery_before = file_snapshot(recovery_files(root))
    indexed_count = verify_checksum_index(root)

    manifest = load_object(root / "source-manifest.redacted.json", "source manifest")
    manifest_records = records_by_file(manifest.get("records"), "source manifest", "source_filename")
    require(set(manifest_records) == set(EXPECTED_ORIGINAL_SHA256), "source_set", "source manifest set is not exact")

    failed_paths: dict[str, Path] = {}
    for filename, expected_hash in EXPECTED_ORIGINAL_SHA256.items():
        record = manifest_records[filename]
        require(record.get("sha256") == expected_hash, "original_checksum", f"source checksum mismatch: {filename}")
        backup_path = Path(str(record.get("backup_path", ""))).resolve()
        require(backup_path == (root / "original" / filename).resolve(), "recovery_path", f"backup path mismatch: {filename}")
        require(sha256_file(backup_path) == expected_hash, "original_checksum", f"backup checksum mismatch: {filename}")
        failed_path = Path(str(record.get("failed_destination_path", "")))
        require(failed_path.name == filename, "recovery_path", f"failed destination mismatch: {filename}")
        failed_paths[filename] = failed_path

    result = load_object(root / "mutation-result.redacted.json", "mutation result")
    require(result.get("original_sha256") == EXPECTED_ORIGINAL_SHA256, "result_set", "mutation result original set is not exact")
    failed_result = records_by_file(result.get("failed_artifacts"), "mutation result failed artifacts")
    require(
        {name: row.get("failed_sha256") for name, row in failed_result.items()} == EXPECTED_FAILED_SHA256,
        "result_set",
        "mutation result failed set is not exact",
    )
    require(
        (result.get("source_count"), result.get("backup_count"), result.get("failed_artifact_count"), result.get("writing_count_after"))
        == (3, 3, 3, 0),
        "result_counts",
        "mutation result counts are not exact",
    )

    pre = load_object(root / "pre-surfaces.json", "pre surfaces")
    post = load_object(root / "post-surfaces.json", "post surfaces")
    require(
        pre.get("crontab_sha256") == EXPECTED_CRONTAB_SHA256,
        "crontab_identity",
        "pre crontab hash is not the accepted paused identity",
    )
    verify_surface_delta(pre, post, EXPECTED_ORIGINAL_SHA256, EXPECTED_FAILED_SHA256, EXPECTED_QUEUE_COUNTS)

    failed_before = file_snapshot(failed_paths.values())
    verified_artifacts: list[dict[str, str]] = []
    for filename, path in sorted(failed_paths.items()):
        require(sha256_file(path) == EXPECTED_FAILED_SHA256[filename], "failed_checksum", f"failed checksum mismatch: {filename}")
        verify_failed_record(load_object(path, f"failed artifact {filename}"), filename, EXPECTED_ORIGINAL_SHA256[filename])
        verified_artifacts.append({"file": filename, "sha256": EXPECTED_FAILED_SHA256[filename]})

    require(file_snapshot(recovery_files(root)) == recovery_before, "write_detected", "recovery directory changed during verification")
    require(file_snapshot(failed_paths.values()) == failed_before, "write_detected", "failed artifacts changed during verification")
    return {
        "status": "pass",
        "read_only": True,
        "recovery_index_sha256": EXPECTED_INDEX_SHA256,
        "indexed_artifact_count": indexed_count,
        "verified_failed_artifacts": verified_artifacts,
        "queue_counts": EXPECTED_QUEUE_COUNTS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovery_dir", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_recovery(args.recovery_dir), sort_keys=True, indent=2))
        return 0
    except VerificationError as exc:
        print(json.dumps({"status": "fail", "read_only": True, "code": exc.code, "detail": exc.detail}, sort_keys=True), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(
            json.dumps({"status": "fail", "read_only": True, "code": "unexpected_io", "detail": type(exc).__name__}, sort_keys=True),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
