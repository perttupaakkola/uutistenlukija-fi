#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parents[1] / 'static' / 'newsletter'
dates = [path.stem.replace('daily-', '') for path in sorted(base.glob('daily-*.html'))]
script = Path(__file__).resolve().parents[1] / 'pipeline' / 'daily_briefing.py'
for d in dates:
    result = subprocess.run([sys.executable, str(script), '--date', d], check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
