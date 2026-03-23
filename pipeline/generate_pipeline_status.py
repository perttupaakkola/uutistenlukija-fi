#!/usr/bin/env python3
"""
generate_pipeline_status.py — Write pipeline dashboard data to static/api/pipeline-status.json

Called by auto_publish.sh after each pipeline run.
Output served at: https://uutistenlukija.fi/api/pipeline-status.json

Consumers: /tila/ page (live dashboard widget)
"""
import json
import sys
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
OUT_FILE    = PROJECT_DIR / "static" / "api" / "pipeline-status.json"

def main():
    # Import dashboard from same directory
    sys.path.insert(0, str(SCRIPT_DIR))
    from dashboard import build_dashboard

    data = build_dashboard(hours=24)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    print(f"[generate_pipeline_status] Written: {OUT_FILE.relative_to(PROJECT_DIR)}"
          f" (published={data['articles']['published']} runs={data['runs']['total']})")

if __name__ == "__main__":
    main()
