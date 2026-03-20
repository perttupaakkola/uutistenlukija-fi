#!/usr/bin/env python3
"""
Lighthouse performance check — runs Google Lighthouse against the live site
and reports Core Web Vitals scores.

Requires: npm install -g lighthouse
"""

import subprocess
import json
import sys
from pathlib import Path

def run_lighthouse(url: str) -> dict:
    """Run Lighthouse and return results as JSON."""
    try:
        result = subprocess.run(
            ["lighthouse", url, "--output=json", "--chrome-flags=--headless"],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            print(f"[lighthouse] Error running lighthouse: {result.stderr}")
            return {}
        return json.loads(result.stdout)
    except FileNotFoundError:
        print("[lighthouse] lighthouse CLI not found. Install with: npm install -g lighthouse")
        return {}
    except Exception as e:
        print(f"[lighthouse] Exception: {e}")
        return {}


def extract_metrics(data: dict) -> dict:
    """Extract Core Web Vitals and key metrics from Lighthouse report."""
    if not data or "lighthouseResult" not in data:
        return {}
    
    lr = data["lighthouseResult"]
    audits = lr.get("audits", {})
    categories = lr.get("categories", {})
    
    return {
        "overall_performance": categories.get("performance", {}).get("score", 0),
        "overall_accessibility": categories.get("accessibility", {}).get("score", 0),
        "overall_seo": categories.get("seo", {}).get("score", 0),
        "overall_best_practices": categories.get("best-practices", {}).get("score", 0),
        "fcp": audits.get("first-contentful-paint", {}).get("displayValue", "N/A"),
        "lcp": audits.get("largest-contentful-paint", {}).get("displayValue", "N/A"),
        "cls": audits.get("cumulative-layout-shift", {}).get("displayValue", "N/A"),
        "ttfb": audits.get("server-response-time", {}).get("displayValue", "N/A"),
        "tti": audits.get("interactive", {}).get("displayValue", "N/A"),
    }


def main():
    url = "https://uutistenlukija.fi"
    if len(sys.argv) > 1:
        url = sys.argv[1]
    
    print(f"[lighthouse] Running Lighthouse against {url}...")
    print(f"[lighthouse] This may take 30-60 seconds...")
    
    data = run_lighthouse(url)
    if not data:
        print("[lighthouse] No results. Exiting.")
        sys.exit(1)
    
    metrics = extract_metrics(data)
    
    print("\n=== LIGHTHOUSE RESULTS ===\n")
    print(f"URL: {url}\n")
    
    print("OVERALL SCORES (0-100):")
    print(f"  Performance:      {metrics.get('overall_performance', 0)}")
    print(f"  Accessibility:    {metrics.get('overall_accessibility', 0)}")
    print(f"  SEO:              {metrics.get('overall_seo', 0)}")
    print(f"  Best Practices:   {metrics.get('overall_best_practices', 0)}\n")
    
    print("CORE WEB VITALS:")
    print(f"  FCP (First Contentful Paint):     {metrics.get('fcp', 'N/A')}")
    print(f"  LCP (Largest Contentful Paint):   {metrics.get('lcp', 'N/A')}")
    print(f"  CLS (Cumulative Layout Shift):    {metrics.get('cls', 'N/A')}")
    print(f"  TTFB (Time to First Byte):        {metrics.get('ttfb', 'N/A')}")
    print(f"  TTI (Time to Interactive):        {metrics.get('tti', 'N/A')}\n")
    
    # Write summary to file
    output_path = Path(__file__).parent.parent / "logs" / "lighthouse_latest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"[lighthouse] Results saved to {output_path}")
    
    perf_score = metrics.get('overall_performance', 0)
    if perf_score >= 90:
        print(f"\n✅ Performance score {perf_score} is excellent.")
    elif perf_score >= 75:
        print(f"\n⚠️  Performance score {perf_score} is good but room for improvement.")
    else:
        print(f"\n🔴 Performance score {perf_score} needs work.")


if __name__ == "__main__":
    main()
