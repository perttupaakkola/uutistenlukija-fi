#!/usr/bin/env python3
"""Backward-compatible wrapper for structured data validation.

Primary implementation lives in scripts/validate_structured_data.py.
"""

from pathlib import Path
import runpy

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_DIR / "scripts" / "validate_structured_data.py"

if __name__ == "__main__":
    runpy.run_path(str(SCRIPT), run_name="__main__")
