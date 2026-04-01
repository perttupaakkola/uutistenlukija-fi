"""
filler_gate.py — Stub for filler phrase detection in articles.

This module was imported by quality_gate.py but never created.
This is a minimal stub that makes the pipeline functional.
TODO: Implement real filler phrase detection if needed.
"""

from __future__ import annotations
from typing import NamedTuple


class FillerResult(NamedTuple):
    matches: list[str] = []
    labels: list[str] = []
    total_penalty: int = 0


def analyze_article(article: dict) -> FillerResult:
    """Analyze an article for filler phrases. Returns empty result (stub)."""
    return FillerResult(matches=[], labels=[], total_penalty=0)


def log_hits(article: dict, result: FillerResult) -> None:
    """Log filler phrase hits. No-op stub."""
    pass
