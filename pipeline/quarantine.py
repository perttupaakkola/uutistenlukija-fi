#!/usr/bin/env python3
"""
quarantine.py — persist writer failures for later inspection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from story_packet import ensure_queue_dirs


def save_writer_quarantine(packet: dict, reason: str, raw_response: str = "", extra: dict | None = None) -> Path:
    paths = ensure_queue_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = paths["quarantine"] / f"{ts}_{packet.get('packet_id', 'unknown')}.json"
    payload = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "packet": packet,
        "raw_response": raw_response,
        "extra": extra or {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
