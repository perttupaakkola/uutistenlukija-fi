#!/usr/bin/env python3
"""Regression checks for category-aware related article rendering."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path


CASES = {
    "2026-07-12-sahkon-futuurihinnat-nousivat-jyrkasti-loppuvuodelle-2026": (
        "talous",
        ("mariano-rajoyta", "sonya-luopumasta-fyysisist"),
    ),
    "2026-07-12-etela-afrikka-kasittelee-yli-53-000-ulkomaalaisen-palauttami": (
        "ulkomaat",
        (),
    ),
}


class RelatedCardsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_related = False
        self.depth = 0
        self.categories: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "section" and "related-articles" in classes:
            self.in_related = True
            self.depth = 1
            return
        if not self.in_related:
            return
        if tag == "section":
            self.depth += 1
        if tag == "span" and "related-card__cat" in classes:
            category_class = next(
                value.removeprefix("related-card__cat--")
                for value in classes
                if value.startswith("related-card__cat--")
            )
            self.categories.append(category_class)
        if tag == "a" and "href" in values and len(self.hrefs) < len(self.categories):
            self.hrefs.append(values["href"] or "")

    def handle_endtag(self, tag: str) -> None:
        if self.in_related and tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.in_related = False


def check_page(
    public_dir: Path,
    slug: str,
    expected_category: str,
    forbidden_href_fragments: tuple[str, ...],
) -> None:
    page = public_dir / "posts" / slug / "index.html"
    parser = RelatedCardsParser()
    parser.feed(page.read_text(encoding="utf-8"))

    assert parser.categories == [expected_category] * 3, (
        f"{slug}: expected three {expected_category} cards, got {parser.categories}"
    )
    assert len(parser.hrefs) == 3, f"{slug}: expected three related links"
    assert len(set(parser.hrefs)) == 3, f"{slug}: duplicate related links: {parser.hrefs}"
    assert all(slug not in href for href in parser.hrefs), (
        f"{slug}: current article appeared in related links: {parser.hrefs}"
    )
    assert not any(
        fragment in href
        for fragment in forbidden_href_fragments
        for href in parser.hrefs
    ), f"{slug}: prohibited semantic mismatch remained: {parser.hrefs}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-dir", type=Path, required=True)
    args = parser.parse_args()
    for slug, (expected_category, forbidden_href_fragments) in CASES.items():
        check_page(args.public_dir, slug, expected_category, forbidden_href_fragments)
    print("related article selection: 2 pages, 6 unique same-category cards — PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
