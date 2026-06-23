#!/usr/bin/env python3
"""
test_templates.py — Hugo edge-case template harness.

Creates draft-only edge-case content under content/test/, runs a Hugo build that
includes drafts, captures warnings from stderr, then cleans up the generated
content unless --keep is set.

Usage:
    python3 pipeline/test_templates.py
    python3 pipeline/test_templates.py --keep
    python3 pipeline/test_templates.py --hugo-bin /path/to/hugo

Exit codes:
    0 = build passed
    1 = build failed
    2 = Hugo binary missing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_TEST_DIR = PROJECT_DIR / "content" / "test"
DEFAULT_HUGO_BIN = Path("/workspace/hugo")
WARNING_RE = re.compile(r"\b(?:warn(?:ing)?|deprecated|deprecation)\b", re.IGNORECASE)


@dataclass
class BuildResult:
    returncode: int
    stdout: str
    stderr: str
    missing_hugo: bool = False
    timed_out: bool = False


@dataclass
class TestArticle:
    filename: str
    frontmatter: dict
    body: str


def yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    return json.dumps(str(value), ensure_ascii=False)


def render_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def detect_hugo_bin(cli_value: str) -> str:
    if cli_value:
        return cli_value
    env_value = os.environ.get("HUGO_BIN")
    if env_value:
        return env_value
    if DEFAULT_HUGO_BIN.exists():
        return str(DEFAULT_HUGO_BIN)
    discovered = shutil.which("hugo")
    if discovered:
        return discovered
    return str(DEFAULT_HUGO_BIN)


def build_test_articles() -> list[TestArticle]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    future = now + timedelta(days=7)
    long_title = (
        "Tämä on tarkoituksella erittäin pitkä otsikko, jolla testataan Hugo-mallien "
        "otsikkokatkaisu, meta-tagit, Open Graph -rakenteet, JSON-LD-headline-rajoitukset, "
        "korttinäkymät sekä kaikki muut paikat, joissa yli 200 merkin otsikko voi rikkoa asettelun tai renderöinnin"
    )

    base = {
        "draft": True,
        "categories": ["Kotimaa"],
        "tags": ["template-test", "edge-case"],
        "description": "Template edge-case test article for Hugo build validation.",
        "date": now.isoformat(),
    }

    def article(filename: str, title: str, body: str, **overrides) -> TestArticle:
        fm = dict(base)
        fm["title"] = title
        fm.update(overrides)
        return TestArticle(filename=filename, frontmatter=fm, body=body)

    return [
        article(
            "template-edge-empty-body.md",
            "Template test: empty body",
            "",
            keywords=["template test", "empty body"],
            source_name="Yle",
            source_url="https://yle.fi/",
        ),
        article(
            "template-edge-no-image.md",
            "Template test: no image",
            "Tässä jutussa ei ole kuvaa, jotta hero-, kortti- ja OG-polut käyttävät varajärjestelyjä.\n",
            keywords=["template test", "no image"],
            source_name="Iltalehti",
            source_url="https://www.iltalehti.fi/",
        ),
        article(
            "template-edge-no-keywords.md",
            "Template test: no keywords",
            "Tässä jutussa jätetään keywords-frontmatter pois kokonaan.\n\nNäin varmistetaan, että mallit eivät oleta kentän aina olevan olemassa.\n",
            source_name="Helsingin Sanomat",
            source_url="https://www.hs.fi/",
        ),
        article(
            "template-edge-long-title.md",
            long_title,
            "Pitkä otsikko testaa erityisesti meta- ja korttitason leikkauslogiikkaa.\n",
            keywords=["pitkä otsikko", "template test"],
            source_name="Tekniikka & Talous",
            source_url="https://www.tekniikkatalous.fi/",
        ),
        article(
            "template-edge-special-chars.md",
            'Erikoismerkit: "lainaus", kaksoispiste: testi — ja vielä &-merkki mukana',
            "Otsikossa on lainausmerkkejä, kaksoispisteitä, ajatusviiva ja ampersand.\n",
            keywords=["erikoismerkit", "template test"],
            source_name="MTV Uutiset",
            source_url="https://www.mtvuutiset.fi/",
        ),
        article(
            "template-edge-no-source.md",
            "Template test: no source name or URL",
            "Tässä jutussa source_name ja source_url puuttuvat kokonaan.\n",
            keywords=["no source", "template test"],
        ),
        article(
            "template-edge-all-optional.md",
            "Template test: all optional fields",
            "Kaikki yleiset valinnaiset frontmatter-kentät on täytetty tätä testiä varten.\n\nJos jokin malli tekee virheellisen tyyppioletuksen, se näkyy tässä.\n",
            keywords=["template test", "optional fields", "frontmatter"],
            source_name="Reuters",
            source_url="https://www.reuters.com/",
            source_domain="reuters.com",
            summary="Tiivistelmä valinnaisten kenttien renderöintitestiin.",
            key_points=[
                "Ensimmäinen testikohta varmistaa, että lista renderöityy.",
                "Toinen kohta tarkistaa, että otsikko näkyy artikkelin alussa.",
                "Kolmas kohta pitää rakenteen kolmen bulletin mittaisena.",
            ],
            image="https://images.unsplash.com/photo-1497366754035-f200968a6e72",
            image_thumb="https://images.unsplash.com/photo-1497366754035-f200968a6e72?w=400",
            image_alt="Testikuva newsroom-ympäristöstä",
            image_credit="Photo by Campaign Creators on Unsplash",
            image_source_url="https://unsplash.com/photos/QZ9tYzXq6j0",
            related_articles=[
                "template-edge-no-image",
                "template-edge-long-title",
            ],
            author="Toimitus",
            author_id="toimitus",
            author_title="Uutistoimitus",
            author_bio="Automaattinen testihahmo templaatteja varten.",
            author_image="/images/authors/toimitus.jpg",
            content_type="analysis",
            editorial_reviewed=True,
            reading_time=5,
        ),
        article(
            "template-edge-future-date.md",
            "Template test: future-dated article",
            "Tämä juttu on päivätty tulevaisuuteen, jotta aikalogiikka ja tuoreuslabelit kestävät sen.\n",
            date=future.isoformat(),
            keywords=["future date", "template test"],
            source_name="STT",
            source_url="https://www.stt.fi/",
        ),
    ]


def write_test_articles(test_dir: Path) -> list[Path]:
    test_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    for item in build_test_articles():
        path = test_dir / item.filename
        content = f"{render_frontmatter(item.frontmatter)}\n\n{item.body.strip()}\n"
        path.write_text(content, encoding="utf-8")
        created.append(path)
    return created


def cleanup_test_articles(paths: list[Path], test_dir: Path) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    try:
        if test_dir.exists() and not any(test_dir.iterdir()):
            test_dir.rmdir()
    except OSError:
        pass


def run_hugo_build(hugo_bin: str, destination: Path, timeout: int) -> BuildResult:
    command = [hugo_bin, "--minify", "-D", "--destination", str(destination)]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return BuildResult(result.returncode, result.stdout or "", result.stderr or "")
    except (FileNotFoundError, PermissionError):
        return BuildResult(127, "", f"Hugo binary not found or not executable: {hugo_bin}", missing_hugo=True)
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        return BuildResult(124, stdout, stderr or f"Hugo build timed out after {timeout}s", timed_out=True)


def parse_warnings(stderr: str) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()

    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if WARNING_RE.search(line):
            if line not in seen:
                seen.add(line)
                warnings.append(line)
    return warnings


def assert_404_and_stale_subpath_coverage(destination: Path) -> list[str]:
    failures: list[str] = []
    not_found = destination / "404.html"

    if not not_found.exists():
        return ["404.html was not generated"]

    html = not_found.read_text(encoding="utf-8", errors="replace")
    if not re.search(r'class=(?:"page-404 container"|page-404\b)', html):
        failures.append("404.html missing page-404 container")
    if not re.search(r'id="?error-latest-heading"?', html):
        failures.append("404.html missing latest-article fallback section")
    if not re.search(r'href="?/css/404(?:\.min)?\.[^"\s>]+\.css"?', html):
        failures.append("404.html missing fingerprinted 404 stylesheet")

    css_files = sorted((destination / "css").glob("404*.css"))
    if not css_files:
        failures.append("fingerprinted 404 stylesheet was not emitted")
    else:
        css = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in css_files)
        required_css = [
            ".page-404",
            "overflow-wrap:anywhere",
            "grid-template-columns:repeat(3,minmax(0,1fr))",
            "grid-template-columns:minmax(0,1fr)",
        ]
        compact_css = re.sub(r"\s+", "", css)
        for token in required_css:
            if token not in compact_css:
                failures.append(f"404 stylesheet missing overflow containment rule: {token}")

    article_path = destination / "test" / "template-edge-long-title" / "index.html"
    stale_subpath = destination / "test" / "template-edge-long-title" / "stale-subpath" / "index.html"
    if not article_path.exists():
        failures.append("test article page was not generated for stale-subpath assertion")
    if stale_subpath.exists():
        failures.append("stale article subpath unexpectedly generated an index.html instead of falling through to 404")

    return failures


def assert_finnish_category_alias_coverage(destination: Path) -> list[str]:
    failures: list[str] = []

    if not (destination / "kategoriat" / "index.html").exists():
        failures.append("/kategoriat/ index was not generated")

    for slug in ("kotimaa", "talous"):
        alias_path = destination / "kategoriat" / slug / "index.html"
        if not alias_path.exists():
            failures.append(f"/kategoriat/{slug}/ alias page was not generated")
            continue
        html = alias_path.read_text(encoding="utf-8", errors="replace")
        if f"/categories/{slug}/" not in html:
            failures.append(f"/kategoriat/{slug}/ alias does not point to /categories/{slug}/")

    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Hugo edge-case template tests against draft-only content.")
    parser.add_argument("--keep", action="store_true", help="Keep generated content/test files and build output for inspection.")
    parser.add_argument("--hugo-bin", default="", help="Override Hugo binary path.")
    parser.add_argument("--output-dir", default="", help="Override Hugo destination directory.")
    parser.add_argument("--timeout", type=int, default=120, help="Hugo build timeout in seconds (default: 120).")
    parser.add_argument("--verbose", action="store_true", help="Print full stdout/stderr even on success.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hugo_bin = detect_hugo_bin(args.hugo_bin)
    created: list[Path] = []

    if args.output_dir:
        destination = Path(args.output_dir)
        if not destination.is_absolute():
            destination = PROJECT_DIR / destination
        temp_dir = None
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="template-hugo-build-"))
        destination = temp_dir / "public"

    print("═" * 60)
    print(" Hugo Template Edge-Case Harness")
    print("═" * 60)
    print(f"[templates] Hugo binary: {hugo_bin}")
    print(f"[templates] Destination: {destination}")
    print(f"[templates] Content dir: {CONTENT_TEST_DIR}")

    try:
        created = write_test_articles(CONTENT_TEST_DIR)
        print(f"[templates] Created {len(created)} test articles")
        for path in created:
            print(f"[templates]   + {path.relative_to(PROJECT_DIR)}")

        result = run_hugo_build(hugo_bin, destination, args.timeout)
        warnings = parse_warnings(result.stderr)

        print(f"[templates] Exit code: {result.returncode}")
        print(f"[templates] Warnings found in stderr: {len(warnings)}")
        for warning in warnings:
            print(f"[templates]   WARN {warning}")

        if args.verbose and result.stdout.strip():
            print("[templates] ── stdout ──")
            print(result.stdout.strip())
        if (args.verbose or result.returncode != 0) and result.stderr.strip():
            print("[templates] ── stderr ──")
            print(result.stderr.strip())

        if result.missing_hugo:
            print(f"[templates] Hugo binary missing: {hugo_bin}")
            return 2
        if result.timed_out:
            print("[templates] Hugo build timed out")
            return 1
        if result.returncode != 0:
            print("[templates] Hugo build failed")
            return 1

        regression_failures = assert_404_and_stale_subpath_coverage(destination)
        regression_failures.extend(assert_finnish_category_alias_coverage(destination))
        if regression_failures:
            print("[templates] template regression checks failed")
            for failure in regression_failures:
                print(f"[templates]   FAIL {failure}")
            return 1

        print("[templates] Hugo build passed")
        print("[templates] 404/stale-subpath regression checks passed")
        print("[templates] Finnish category alias regression checks passed")
        return 0
    finally:
        if args.keep:
            print("[templates] Keeping generated test content and build output")
            if created:
                for path in created:
                    print(f"[templates]   kept {path.relative_to(PROJECT_DIR)}")
        else:
            cleanup_test_articles(created, CONTENT_TEST_DIR)
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            print("[templates] Cleanup complete")


if __name__ == "__main__":
    sys.exit(main())
