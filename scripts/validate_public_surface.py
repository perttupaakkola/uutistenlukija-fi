#!/usr/bin/env python3
"""Fail deploys if internal operator surfaces are generated for visitors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FORBIDDEN_PUBLIC_PATHS = (
    Path("tila/index.html"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", default="public", type=Path)
    args = parser.parse_args()

    public_dir = args.public_dir
    if not public_dir.exists():
        raise SystemExit(f"[public-surface] Missing public directory: {public_dir}")

    found = [
        str(path)
        for rel in FORBIDDEN_PUBLIC_PATHS
        for path in [public_dir / rel]
        if path.exists()
    ]
    payload = {
        "status": "ok" if not found else "forbidden_public_surface",
        "public_dir": str(public_dir),
        "forbidden_paths": found,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not found else 1


if __name__ == "__main__":
    raise SystemExit(main())
