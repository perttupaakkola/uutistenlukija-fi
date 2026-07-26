#!/usr/bin/env python3
"""Render guide lifecycle fixtures and assert fail-closed discovery parity."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from guide_lifecycle import evaluate_guide, parse_guide_document  # noqa: E402
from test_oppaat_built_contract import (  # noqa: E402
    GUIDE_PATH,
    GUIDE_URL,
    HUB_PATH,
    meta_content,
    page_path,
    read_page,
    schemas,
    sitemap_locations,
)


GUIDE_SOURCE = ROOT / "content/oppaat/kauppojen-aukioloajat.md"
HUB_SOURCE = ROOT / "content/oppaat/_index.md"
HUGO = Path(os.environ.get("HUGO_BIN", "/workspace/hugo"))
FIXTURE_TODAY = date(2026, 7, 26)
PROBE_SINGLE = """{{- $state := partial "guide-state.html" . -}}
<!doctype html>
<html lang="fi">
<head>
  {{- if or .Params.noindex $state.expired $state.invalid $state.draft }}
  <meta name="robots" content="noindex,follow">
  {{- end }}
</head>
<body><p id="guide-state">{{ $state.invalid }}|{{ $state.discoverable }}</p></body>
</html>
"""


def yaml_scalar(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def dump_guide_document(meta: dict, body: str) -> str:
    """Serialize the explicit YAML subset consumed by guide_lifecycle.py."""
    lines = ["---"]
    for key, value in meta.items():
        if not isinstance(value, list):
            lines.append(f"{key}: {yaml_scalar(value)}")
            continue
        if not value:
            lines.append(f"{key}: []")
            continue
        lines.append(f"{key}:")
        for item in value:
            if not isinstance(item, dict):
                lines.append(f"  - {yaml_scalar(item)}")
                continue
            fields = list(item.items())
            first_key, first_value = fields[0]
            lines.append(f"  - {first_key}: {yaml_scalar(first_value)}")
            for item_key, item_value in fields[1:]:
                lines.append(f"    {item_key}: {yaml_scalar(item_value)}")
    lines.extend(("---", "", body.strip()))
    return "\n".join(lines) + "\n"


def source_document() -> tuple[dict, str]:
    return parse_guide_document(GUIDE_SOURCE.read_text(encoding="utf-8"))


def document_with_flag(flag: str) -> str:
    meta, body = source_document()
    meta[flag] = True
    return dump_guide_document(meta, body)


def source_mismatch_document() -> str:
    meta, body = source_document()
    meta["sources"][0]["source_checked_at"] = "2026-07-25"
    return dump_guide_document(meta, body)


def invalid_parity_documents() -> dict[str, str]:
    """One invalid document per Python lifecycle invariant class."""
    source_meta, source_body = source_document()
    documents: dict[str, str] = {}

    def add(
        slug: str,
        mutate,
        *,
        body: str | None = None,
    ) -> None:
        meta = copy.deepcopy(source_meta)
        mutate(meta)
        document = dump_guide_document(
            meta,
            source_body if body is None else body,
        )
        parsed_meta, parsed_body = parse_guide_document(document)
        lifecycle = evaluate_guide(
            parsed_meta,
            parsed_body,
            today=FIXTURE_TODAY,
        )
        if lifecycle.state != "invalid":
            raise AssertionError(
                f"Python fixture {slug} did not fail closed: {lifecycle}"
            )
        documents[f"{slug}.md"] = document

    for field in (
        "title",
        "description",
        "date",
        "reviewed_at",
        "updated_at",
        "next_review_at",
        "expires_at",
        "correction_url",
        "search_terms",
    ):
        add(
            f"missing-{field.replace('_', '-')}",
            lambda meta, field=field: meta.pop(field),
        )

    add("body-899-words", lambda _meta: None, body=" ".join(["sana"] * 899))
    add("body-1501-words", lambda _meta: None, body=" ".join(["sana"] * 1501))

    for field in ("reviewed_at", "updated_at", "next_review_at", "expires_at"):
        add(
            f"invalid-{field.replace('_', '-')}",
            lambda meta, field=field: meta.__setitem__(field, "not-a-date"),
        )

    add(
        "updated-before-published",
        lambda meta: meta.__setitem__("updated_at", "2026-07-25"),
    )
    add(
        "updated-after-reviewed",
        lambda meta: meta.__setitem__("updated_at", "2026-07-27"),
    )
    add(
        "review-window-zero",
        lambda meta: meta.__setitem__("next_review_at", "2026-07-26"),
    )
    add(
        "review-window-fifteen",
        lambda meta: meta.__setitem__("next_review_at", "2026-08-10"),
    )
    add(
        "expiry-window-zero",
        lambda meta: meta.__setitem__("expires_at", "2026-07-26"),
    )
    add(
        "expiry-window-thirty-one",
        lambda meta: meta.__setitem__("expires_at", "2026-08-26"),
    )

    def next_after_expiry(meta: dict) -> None:
        meta["next_review_at"] = "2026-08-09"
        meta["expires_at"] = "2026-08-08"

    add("next-review-after-expiry", next_after_expiry)
    add(
        "correction-scheme",
        lambda meta: meta.__setitem__(
            "correction_url",
            "http://example.invalid/correction",
        ),
    )
    add(
        "too-few-sources",
        lambda meta: meta.__setitem__("sources", meta["sources"][:2]),
    )
    add(
        "source-not-mapping",
        lambda meta: meta["sources"].__setitem__(0, "not-a-mapping"),
    )
    add(
        "source-missing-name",
        lambda meta: meta["sources"][0].pop("name"),
    )
    add(
        "source-not-https",
        lambda meta: meta["sources"][0].__setitem__(
            "url",
            "http://www.k-ryhma.fi/kauppojen-aukioloajat",
        ),
    )
    add(
        "source-duplicate-domain",
        lambda meta: meta["sources"][1].__setitem__(
            "url",
            "https://www.k-ryhma.fi/toinen",
        ),
    )
    add(
        "source-not-official",
        lambda meta: meta["sources"][0].__setitem__("official", False),
    )
    add(
        "source-missing-checked-at",
        lambda meta: meta["sources"][0].pop("source_checked_at"),
    )
    add(
        "source-invalid-checked-at",
        lambda meta: meta["sources"][0].__setitem__(
            "source_checked_at",
            "not-a-date",
        ),
    )
    add(
        "source-checked-at-mismatch",
        lambda meta: meta["sources"][0].__setitem__(
            "source_checked_at",
            "2026-07-25",
        ),
    )
    add(
        "source-no-checker",
        lambda meta: meta["sources"][0].pop("authoritative_checker"),
    )
    add(
        "source-two-checkers",
        lambda meta: meta["sources"][1].__setitem__(
            "authoritative_checker",
            True,
        ),
    )
    return documents


def render_documents(
    root: Path,
    name: str,
    documents: dict[str, str],
    *,
    clock: str,
    probe_layout: bool = False,
) -> Path:
    if not HUGO.is_file():
        raise AssertionError(f"Hugo binary is unavailable: {HUGO}")
    fixture = root / name
    content = fixture / "content"
    guides = content / "oppaat"
    public = fixture / "public"
    guides.mkdir(parents=True)
    shutil.copy2(HUB_SOURCE, guides / "_index.md")
    for filename, document in documents.items():
        (guides / filename).write_text(document, encoding="utf-8")

    command = [
        str(HUGO),
        "--contentDir",
        str(content),
        "--destination",
        str(public),
        "--environment",
        "production",
        "--clock",
        clock,
        "--cacheDir",
        str(fixture / "cache"),
        "--noBuildLock",
        "--minify",
    ]
    if probe_layout:
        layouts = fixture / "layouts"
        shutil.copytree(ROOT / "layouts", layouts)
        (layouts / "oppaat/single.html").write_text(
            PROBE_SINGLE,
            encoding="utf-8",
        )
        command.extend(("--layoutDir", str(layouts)))

    env = os.environ.copy()
    env["HUGO_PORTAL_CSS_VERSION"] = "ope377-lifecycle-fixture"
    env["HUGO_RESOURCEDIR"] = str(fixture / "resources")
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise AssertionError(
            f"{name} Hugo fixture failed:\n{result.stdout}\n{result.stderr}"
        )
    return public


class BuiltSuppressionStateTest(unittest.TestCase):
    fixture_root: tempfile.TemporaryDirectory[str]
    noindex: Path
    draft: Path
    exact_expiry: Path
    source_mismatch: Path
    invalid_matrix: Path
    invalid_slugs: tuple[str, ...]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_root = tempfile.TemporaryDirectory(
            prefix=".ope377-lifecycle-",
            dir=ROOT,
        )
        root = Path(cls.fixture_root.name)
        source = GUIDE_SOURCE.read_text(encoding="utf-8")
        cls.noindex = render_documents(
            root,
            "noindex",
            {GUIDE_SOURCE.name: document_with_flag("noindex")},
            clock="2026-07-26T12:00:00Z",
        )
        cls.draft = render_documents(
            root,
            "draft",
            {GUIDE_SOURCE.name: document_with_flag("draft")},
            clock="2026-07-26T12:00:00Z",
        )
        cls.exact_expiry = render_documents(
            root,
            "exact-expiry",
            {GUIDE_SOURCE.name: source},
            clock="2026-08-25T12:00:00Z",
        )
        cls.source_mismatch = render_documents(
            root,
            "source-mismatch",
            {GUIDE_SOURCE.name: source_mismatch_document()},
            clock="2026-07-26T12:00:00Z",
        )
        invalid_documents = invalid_parity_documents()
        cls.invalid_slugs = tuple(
            Path(filename).stem for filename in invalid_documents
        )
        cls.invalid_matrix = render_documents(
            root,
            "invalid-matrix",
            invalid_documents,
            clock="2026-07-26T12:00:00Z",
            probe_layout=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_root.cleanup()

    def assert_hub_has_no_promoted_guides(self, public: Path) -> None:
        hub = read_page(public, HUB_PATH)
        self.assertNotIn("class=guide-card>", hub)
        collection = next(
            item
            for item in schemas(hub)
            if item.get("@type") == "CollectionPage"
        )
        self.assertEqual(collection["mainEntity"]["itemListElement"], [])

    def assert_guide_is_noindex_and_absent_from_sitemap(
        self,
        public: Path,
        *,
        route: str = GUIDE_PATH,
        absolute_url: str = GUIDE_URL,
    ) -> str:
        guide = read_page(public, route)
        self.assertEqual(meta_content(guide, "robots"), ["noindex,follow"])
        self.assertEqual(
            sitemap_locations(public / "sitemap.xml").count(absolute_url),
            0,
        )
        return guide

    def test_noindex_keeps_html_but_leaves_hub_and_sitemap(self) -> None:
        self.assert_guide_is_noindex_and_absent_from_sitemap(self.noindex)
        self.assert_hub_has_no_promoted_guides(self.noindex)

    def test_draft_is_absent_from_html_hub_and_sitemap(self) -> None:
        self.assertFalse(page_path(self.draft, GUIDE_PATH).exists())
        self.assert_hub_has_no_promoted_guides(self.draft)
        self.assertEqual(
            sitemap_locations(self.draft / "sitemap.xml").count(GUIDE_URL),
            0,
        )

    def test_exact_expiry_fails_closed_in_rendered_discovery(self) -> None:
        guide = self.assert_guide_is_noindex_and_absent_from_sitemap(
            self.exact_expiry
        )
        self.assertIn("Tämän oppaan voimassaolo on päättynyt", guide)
        self.assert_hub_has_no_promoted_guides(self.exact_expiry)

    def test_source_check_mismatch_is_rendered_invalid_and_excluded(self) -> None:
        guide = self.assert_guide_is_noindex_and_absent_from_sitemap(
            self.source_mismatch
        )
        self.assertIn(
            "Oppaan tarkistus- tai lähdetiedot ovat puutteelliset",
            guide,
        )
        self.assert_hub_has_no_promoted_guides(self.source_mismatch)

    def test_every_python_invalid_invariant_fails_closed_in_hugo(self) -> None:
        self.assert_hub_has_no_promoted_guides(self.invalid_matrix)
        locations = sitemap_locations(self.invalid_matrix / "sitemap.xml")
        for slug in self.invalid_slugs:
            with self.subTest(slug=slug):
                route = f"/oppaat/{slug}/"
                absolute_url = f"https://uutistenlukija.fi{route}"
                guide = self.assert_guide_is_noindex_and_absent_from_sitemap(
                    self.invalid_matrix,
                    route=route,
                    absolute_url=absolute_url,
                )
                self.assertIn(">true|false<", guide)
                self.assertNotIn(absolute_url, locations)

    def test_invalid_native_date_stops_hugo_before_discovery(self) -> None:
        meta, body = source_document()
        meta["date"] = "not-a-date"
        document = dump_guide_document(meta, body)
        parsed_meta, parsed_body = parse_guide_document(document)
        self.assertEqual(
            evaluate_guide(
                parsed_meta,
                parsed_body,
                today=FIXTURE_TODAY,
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(
            AssertionError,
            'front matter field is not a parsable date',
        ):
            render_documents(
                Path(self.fixture_root.name),
                "invalid-native-date",
                {"invalid-native-date.md": document},
                clock="2026-07-26T12:00:00Z",
                probe_layout=True,
            )


if __name__ == "__main__":
    unittest.main()
